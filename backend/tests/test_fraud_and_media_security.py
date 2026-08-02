"""Travas anti-fraude e proteção de mídia — regressões de segurança."""
from decimal import Decimal
from unittest import mock

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import override_settings
from django.urls import reverse

from apps.catalog.models import Product
from apps.core.media_signing import sign_media_path, verify_media_signature
from apps.payments.checkout import confirm_paid_order, expire_order
from apps.payments.models import Order, Payment
from apps.wallet.services import release_matured_escrow

from .base import ApiTestCase
from .factories import CPF_BUYER, FakeProvider, checkout_payload, make_product


@override_settings(ASAAS_API_KEY="test-key", ASAAS_WEBHOOK_TOKEN="tok")
class LatePaymentFraudTests(ApiTestCase):
    def setUp(self):
        super().setUp()
        self.provider = FakeProvider(payer_document=CPF_BUYER)
        patcher = mock.patch(
            "apps.payments.services.get_payment_provider", return_value=self.provider
        )
        patcher.start()
        self.addCleanup(patcher.stop)
        self.product = make_product(stock=1)
        self.client.post(
            reverse("payments:checkout"),
            checkout_payload(self.product),
            content_type="application/json",
        )
        self.order = Order.objects.get()
        self.payment = Payment.objects.get()

    def test_expired_order_payment_is_refunded_and_does_not_release_product(self):
        expire_order(self.order)
        self.product.refresh_from_db()
        self.assertEqual(self.product.stock, 1)

        self.provider.paid = True
        confirmed = confirm_paid_order(self.payment)
        self.order.refresh_from_db()
        self.payment.refresh_from_db()

        self.assertFalse(confirmed)
        self.assertEqual(self.order.status, Order.Status.EXPIRED)
        self.assertIn(self.payment.provider_charge_id, self.provider.refunds)
        self.assertNotEqual(self.payment.status, Payment.Status.CONFIRMED)

    def test_unshipped_physical_escrow_never_auto_pays(self):
        self.provider.paid = True
        confirm_paid_order(self.payment)
        self.order.refresh_from_db()
        from apps.wallet.models import WalletEntry
        from django.utils import timezone

        WalletEntry.objects.filter(order=self.order).update(available_at=timezone.now())
        self.assertEqual(release_matured_escrow(), 0)


@override_settings(ASAAS_API_KEY="test-key")
class ProtectedMediaTests(ApiTestCase):
    def test_raw_media_products_path_is_gone(self):
        # Sem rota pública: age gate ou 404 — nunca entrega o arquivo.
        response = self.client.get("/media/products/qualquer.jpg")
        self.assertIn(response.status_code, {302, 404})
        session = self.client.session
        session["age_gate_confirmed"] = True
        session.save()
        self.assertEqual(self.client.get("/media/products/qualquer.jpg").status_code, 404)

    def test_signed_media_requires_valid_signature_and_age_gate(self):
        from django.core.files.storage import default_storage

        path = "products/test-sec.jpg"
        default_storage.save(path, SimpleUploadedFile("test-sec.jpg", b"\xff\xd8\xff" + b"0" * 32))
        unsigned = reverse("core_pages:protected_media", kwargs={"path": path})
        self.assertEqual(self.client.get(unsigned).status_code, 403)

        signed = sign_media_path(path)
        # Sem age gate e sem referer da origem
        session = self.client.session
        session.pop("age_gate_confirmed", None)
        session.save()
        self.assertEqual(self.client.get(signed).status_code, 403)

        session = self.client.session
        session["age_gate_confirmed"] = True
        session.save()
        # Hotlink de outro domínio é bloqueado.
        self.assertEqual(
            self.client.get(signed, HTTP_REFERER="https://evil.example/").status_code,
            403,
        )
        response = self.client.get(signed, HTTP_REFERER="http://testserver/")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response["Cache-Control"], "private, no-store, max-age=0, must-revalidate")

    def test_media_signature_rejects_tampering(self):
        self.assertFalse(verify_media_signature("products/a.jpg", "1", "deadbeef"))
        signed = sign_media_path("products/a.jpg")
        self.assertIn("e=", signed)
        self.assertIn("s=", signed)


@override_settings(ASAAS_API_KEY="test-key")
class DisputeAuthTests(ApiTestCase):
    def setUp(self):
        super().setUp()
        self.provider = FakeProvider(paid=True, payer_document=CPF_BUYER)
        patcher = mock.patch(
            "apps.payments.services.get_payment_provider", return_value=self.provider
        )
        patcher.start()
        self.addCleanup(patcher.stop)
        self.product = make_product(stock=1)
        self.client.post(
            reverse("payments:checkout"),
            checkout_payload(self.product),
            content_type="application/json",
        )
        self.order = Order.objects.get()
        self.client.get(reverse("payments:order_status", args=[self.order.access_token]))

    def test_dispute_without_guest_email_is_forbidden(self):
        response = self.client.post(
            reverse("payments:order_confirm", args=[self.order.access_token]),
            {"action": "dispute"},
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 403)
        self.order.refresh_from_db()
        self.assertEqual(self.order.status, Order.Status.PAID)
