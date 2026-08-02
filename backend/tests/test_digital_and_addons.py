"""
Conteúdo digital e adicionais pagos — as duas coisas que mudam o formato
do pedido (sem endereço num caso, com valor extra no outro).
"""
from decimal import Decimal
from unittest import mock

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import override_settings
from django.urls import reverse

from apps.catalog.models import Product, ProductAddon, ProductAsset
from apps.payments.models import Order, OrderItem

from .base import ApiTestCase
from .factories import FakeProvider, checkout_payload, make_product


@override_settings(ASAAS_API_KEY="test-key", PLATFORM_COMMISSION_PERCENT=Decimal("20"))
class AddonTests(ApiTestCase):
    def setUp(self):
        super().setUp()
        self.provider = FakeProvider()
        patcher = mock.patch("apps.payments.services.get_payment_provider", return_value=self.provider)
        patcher.start()
        self.addCleanup(patcher.stop)

        self.product = make_product(payout=Decimal("100.00"), stock=1)
        self.addon = ProductAddon.objects.create(
            product=self.product, title="Com bilhete à mão", payout_amount=Decimal("20.00")
        )

    def test_addon_price_carries_the_commission(self):
        self.assertEqual(self.addon.price, Decimal("24.00"))

    def test_addon_is_charged_and_paid_to_the_seller(self):
        payload = checkout_payload(self.product)
        payload["items"][0]["addon_ids"] = [str(self.addon.id)]

        response = self.client.post(
            reverse("payments:checkout"), payload, content_type="application/json"
        )

        self.assertEqual(response.status_code, 201, response.content)
        order = Order.objects.get()
        item = OrderItem.objects.get()
        self.assertEqual(order.items_total, Decimal("144.00"))  # 120 + 24
        self.assertEqual(item.addons_price, Decimal("24.00"))
        self.assertEqual(item.addons_payout, Decimal("20.00"))
        self.assertEqual(order.payout_total, Decimal("120.00"))  # 100 + 20
        self.assertEqual(order.platform_amount, Decimal("24.00"))
        self.assertEqual(item.addons[0]["title"], "Com bilhete à mão")

    def test_addon_from_another_product_is_rejected(self):
        other = make_product(slug="outro-item")
        foreign = ProductAddon.objects.create(
            product=other, title="Adicional alheio", payout_amount=Decimal("10.00")
        )
        payload = checkout_payload(self.product)
        payload["items"][0]["addon_ids"] = [str(foreign.id)]

        response = self.client.post(
            reverse("payments:checkout"), payload, content_type="application/json"
        )

        self.assertEqual(response.status_code, 400)
        self.assertEqual(Order.objects.count(), 0)

    def test_inactive_addon_is_rejected(self):
        self.addon.is_active = False
        self.addon.save()
        payload = checkout_payload(self.product)
        payload["items"][0]["addon_ids"] = [str(self.addon.id)]

        response = self.client.post(
            reverse("payments:checkout"), payload, content_type="application/json"
        )
        self.assertEqual(response.status_code, 400)

    def test_cart_summary_prices_the_addon_server_side(self):
        body = self.client.post(
            reverse("payments:cart_summary"),
            {"items": [{"id": str(self.product.id), "qty": 1, "addons": [str(self.addon.id)]}]},
            content_type="application/json",
        ).json()

        self.assertEqual(body["items"][0]["addons_total"], "24.00")
        self.assertEqual(body["grand_total"], "144.00")


@override_settings(ASAAS_API_KEY="test-key")
class DigitalProductTests(ApiTestCase):
    def setUp(self):
        super().setUp()
        self.provider = FakeProvider()
        patcher = mock.patch("apps.payments.services.get_payment_provider", return_value=self.provider)
        patcher.start()
        self.addCleanup(patcher.stop)

        session = self.client.session
        session["age_gate_confirmed"] = True
        session.save()
        self.product = make_product(
            payout=Decimal("30.00"), stock=10, slug="pack-digital", kind=Product.Kind.DIGITAL
        )
        self.asset = ProductAsset.objects.create(
            product=self.product,
            file=SimpleUploadedFile("pack.txt", b"conteudo secreto"),
            label="Pack completo",
        )

    def _buy(self):
        payload = checkout_payload(self.product)
        payload.pop("shipping_address")
        return self.client.post(
            reverse("payments:checkout"), payload, content_type="application/json"
        )

    def test_digital_checkout_does_not_require_address(self):
        response = self._buy()

        self.assertEqual(response.status_code, 201, response.content)
        order = Order.objects.get()
        self.assertEqual(order.shipping_address, {})
        self.assertEqual(order.shipping_total, Decimal("0.00"))
        self.assertTrue(order.is_digital_only)

    def test_digital_order_has_no_shipment(self):
        self._buy()
        order = Order.objects.get()
        self.assertFalse(hasattr(order, "shipment"))

    def test_download_is_blocked_before_payment(self):
        self._buy()
        order = Order.objects.get()
        url = reverse("catalog:download_asset", args=[order.access_token, self.asset.id])

        self.assertEqual(
            self.client.get(url, {"email": order.guest_email}).status_code, 404
        )

    def test_download_works_after_payment(self):
        self._buy()
        order = Order.objects.get()
        self.provider.paid = True
        self.client.get(reverse("payments:order_status", args=[order.access_token]))

        url = reverse("catalog:download_asset", args=[order.access_token, self.asset.id])
        response = self.client.get(url, {"email": order.guest_email})

        self.assertEqual(response.status_code, 200)
        self.assertEqual(b"".join(response.streaming_content), b"conteudo secreto")

    def test_download_without_guest_email_is_blocked(self):
        self._buy()
        order = Order.objects.get()
        self.provider.paid = True
        self.client.get(reverse("payments:order_status", args=[order.access_token]))
        url = reverse("catalog:download_asset", args=[order.access_token, self.asset.id])
        self.assertEqual(self.client.get(url).status_code, 404)

    def test_asset_of_another_order_is_not_downloadable(self):
        self._buy()
        order = Order.objects.get()
        self.provider.paid = True
        self.client.get(reverse("payments:order_status", args=[order.access_token]))

        other_asset = ProductAsset.objects.create(
            product=make_product(slug="outro-pack", kind=Product.Kind.DIGITAL),
            file=SimpleUploadedFile("outro.txt", b"nao e seu"),
        )
        url = reverse("catalog:download_asset", args=[order.access_token, other_asset.id])

        self.assertEqual(
            self.client.get(url, {"email": order.guest_email}).status_code, 404
        )

    def test_digital_product_has_no_weight(self):
        self.assertEqual(self.product.weight_grams, 0)
        self.assertFalse(self.product.requires_shipping)


@override_settings(ASAAS_API_KEY="test-key")
class ProductQuestionTests(ApiTestCase):
    def setUp(self):
        super().setUp()
        self.product = make_product()
        self.buyer = self._make_buyer()
        self.url = reverse("catalog_api:question_create", args=[self.product.id])

    @staticmethod
    def _make_buyer():
        from .factories import make_user

        return make_user(role="buyer")

    def test_login_is_required(self):
        response = self.client.post(self.url, {"question": "Tem em outra cor?"}, content_type="application/json")
        self.assertIn(response.status_code, (401, 403))

    def test_buyer_can_ask(self):
        self.client.force_login(self.buyer)
        response = self.client.post(
            self.url, {"question": "Tem em outra cor?"}, content_type="application/json"
        )

        self.assertEqual(response.status_code, 201)
        self.assertEqual(self.product.questions.count(), 1)

    def test_question_with_external_contact_is_blocked(self):
        self.client.force_login(self.buyer)
        response = self.client.post(
            self.url,
            {"question": "me chama no whatsapp 11999998888 pra combinar"},
            content_type="application/json",
        )

        self.assertEqual(response.status_code, 400)
        self.assertEqual(self.product.questions.count(), 0)

    def test_seller_cannot_ask_on_own_listing(self):
        self.client.force_login(self.product.store.owner)
        response = self.client.post(
            self.url, {"question": "Comprem meu item"}, content_type="application/json"
        )
        self.assertEqual(response.status_code, 403)

    def test_seller_answers_the_question(self):
        self.client.force_login(self.buyer)
        self.client.post(self.url, {"question": "Tem em outra cor?"}, content_type="application/json")
        question = self.product.questions.get()

        self.client.force_login(self.product.store.owner)
        response = self.client.post(
            reverse("catalog_api:question_answer", args=[question.id]),
            {"answer": "Tenho em preto e vinho."},
            content_type="application/json",
        )

        self.assertEqual(response.status_code, 200)
        question.refresh_from_db()
        self.assertEqual(question.answer, "Tenho em preto e vinho.")
        self.assertIsNotNone(question.answered_at)

    def test_stranger_cannot_answer(self):
        self.client.force_login(self.buyer)
        self.client.post(self.url, {"question": "Tem em outra cor?"}, content_type="application/json")
        question = self.product.questions.get()

        response = self.client.post(
            reverse("catalog_api:question_answer", args=[question.id]),
            {"answer": "Resposta falsa"},
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 403)
