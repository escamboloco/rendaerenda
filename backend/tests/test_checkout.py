from datetime import date, timedelta
from decimal import Decimal
from unittest import mock

from django.test import override_settings
from django.urls import reverse
from django.utils import timezone

from apps.catalog.models import Product
from apps.payments.checkout import expire_stale_orders
from apps.payments.models import Order, Payment

from .base import ApiTestCase
from .factories import CPF_BUYER, FakeProvider, checkout_payload, make_product


@override_settings(ASAAS_API_KEY="test-key", PLATFORM_COMMISSION_PERCENT=20)
class CheckoutApiTests(ApiTestCase):
    def setUp(self):
        super().setUp()
        self.product = make_product(payout=Decimal("100.00"), stock=1)
        self.url = reverse("payments:checkout")
        self.provider = FakeProvider()
        patcher = mock.patch("apps.payments.services.get_payment_provider", return_value=self.provider)
        patcher.start()
        self.addCleanup(patcher.stop)

    def post(self, payload):
        return self.client.post(self.url, payload, content_type="application/json")

    def test_guest_checkout_creates_order_and_pix(self):
        response = self.post(checkout_payload(self.product))

        self.assertEqual(response.status_code, 201, response.content)
        body = response.json()
        self.assertTrue(body["pix_copy_paste"])
        self.assertTrue(body["track_url"].startswith("/pedido/"))

        order = Order.objects.get()
        self.assertEqual(order.status, Order.Status.AWAITING_PAYMENT)
        # 120 do item + frete (só transportadora) cobrado à parte.
        self.assertEqual(order.items_total, Decimal("120.00"))
        self.assertEqual(order.grand_total, order.items_total + order.shipping_total)
        self.assertEqual(order.payout_total, Decimal("100.00"))
        self.assertEqual(order.platform_amount, Decimal("20.00"))
        self.assertIsNotNone(order.expires_at)

        self.product.refresh_from_db()
        self.assertEqual(self.product.stock, 0)
        self.assertEqual(self.product.status, Product.Status.SOLD)

    def test_second_buyer_cannot_take_the_last_unit(self):
        self.assertEqual(self.post(checkout_payload(self.product)).status_code, 201)
        response = self.post(checkout_payload(self.product))

        self.assertEqual(response.status_code, 400)
        self.product.refresh_from_db()
        self.assertEqual(self.product.stock, 0)  # nunca negativo
        self.assertEqual(Order.objects.count(), 1)

    def test_duplicate_lines_do_not_bypass_stock(self):
        payload = checkout_payload(self.product)
        payload["items"] = [
            {"product_id": str(self.product.id), "quantity": 1},
            {"product_id": str(self.product.id), "quantity": 1},
        ]
        response = self.post(payload)

        self.assertEqual(response.status_code, 400)
        self.product.refresh_from_db()
        self.assertEqual(self.product.stock, 1)

    def test_two_stores_in_one_order_is_rejected(self):
        other = make_product(slug="outro-item")
        payload = checkout_payload(self.product)
        payload["items"].append({"product_id": str(other.id), "quantity": 1})

        self.assertEqual(self.post(payload).status_code, 400)
        self.assertEqual(Order.objects.count(), 0)

    def test_minor_cannot_buy(self):
        payload = checkout_payload(self.product)
        payload["guest_birth_date"] = (date.today() - timedelta(days=365 * 15)).isoformat()

        self.assertEqual(self.post(payload).status_code, 403)
        self.product.refresh_from_db()
        self.assertEqual(self.product.stock, 1)

    def test_invalid_cpf_is_rejected(self):
        payload = checkout_payload(self.product, cpf="11144477736")
        self.assertEqual(self.post(payload).status_code, 400)

    def test_invalid_address_is_rejected(self):
        payload = checkout_payload(self.product)
        payload["shipping_address"]["state"] = "XX"
        self.assertEqual(self.post(payload).status_code, 400)

    def test_provider_failure_restores_stock_and_cancels_order(self):
        self.provider.fail_charge = True
        response = self.post(checkout_payload(self.product))

        self.assertEqual(response.status_code, 502)
        self.assertIn("Cobrança recusada", response.json()["detail"])
        self.product.refresh_from_db()
        self.assertEqual(self.product.stock, 1)
        self.assertEqual(self.product.status, Product.Status.PUBLISHED)
        order = Order.objects.get()
        self.assertEqual(order.status, Order.Status.CANCELED)
        self.assertTrue(order.stock_restored)

    @override_settings(ASAAS_API_KEY="")
    def test_checkout_blocked_when_asaas_not_configured(self):
        response = self.post(checkout_payload(self.product))

        self.assertEqual(response.status_code, 503)
        self.product.refresh_from_db()
        self.assertEqual(self.product.stock, 1)

    def test_sold_out_product_is_not_purchasable(self):
        self.product.stock = 0
        self.product.status = Product.Status.SOLD
        self.product.save()

        self.assertEqual(self.post(checkout_payload(self.product)).status_code, 400)


@override_settings(ASAAS_API_KEY="test-key")
class OrderExpiryTests(ApiTestCase):
    def setUp(self):
        super().setUp()
        self.product = make_product(stock=1)
        self.provider = FakeProvider()
        patcher = mock.patch("apps.payments.services.get_payment_provider", return_value=self.provider)
        patcher.start()
        self.addCleanup(patcher.stop)

    def _create_order(self):
        self.client.post(
            reverse("payments:checkout"),
            checkout_payload(self.product),
            content_type="application/json",
        )
        return Order.objects.get()

    def test_unpaid_order_expires_and_returns_stock(self):
        order = self._create_order()
        Order.objects.filter(pk=order.pk).update(expires_at=timezone.now() - timedelta(minutes=1))

        self.assertEqual(expire_stale_orders(), 1)

        order.refresh_from_db()
        self.product.refresh_from_db()
        self.assertEqual(order.status, Order.Status.EXPIRED)
        self.assertEqual(self.product.stock, 1)
        self.assertEqual(self.product.status, Product.Status.PUBLISHED)

    def test_paid_order_is_never_expired(self):
        order = self._create_order()
        Order.objects.filter(pk=order.pk).update(expires_at=timezone.now() - timedelta(minutes=1))
        self.provider.paid = True  # o Pix caiu, o webhook e que se perdeu

        self.assertEqual(expire_stale_orders(), 0)

        order.refresh_from_db()
        self.assertEqual(order.status, Order.Status.PAID)
        self.product.refresh_from_db()
        self.assertEqual(self.product.stock, 0)

    def test_expiring_twice_does_not_duplicate_stock(self):
        order = self._create_order()
        Order.objects.filter(pk=order.pk).update(expires_at=timezone.now() - timedelta(minutes=1))
        expire_stale_orders()

        from apps.payments.checkout import restore_stock

        order.refresh_from_db()
        self.assertFalse(restore_stock(order))
        self.product.refresh_from_db()
        self.assertEqual(self.product.stock, 1)


@override_settings(ASAAS_API_KEY="test-key")
class OrderStatusPollingTests(ApiTestCase):
    """A tela de pagamento confirma sozinha, mesmo sem webhook."""

    def setUp(self):
        super().setUp()
        self.product = make_product(stock=1)
        self.provider = FakeProvider()
        patcher = mock.patch("apps.payments.services.get_payment_provider", return_value=self.provider)
        patcher.start()
        self.addCleanup(patcher.stop)

        self.client.post(
            reverse("payments:checkout"),
            checkout_payload(self.product),
            content_type="application/json",
        )
        self.order = Order.objects.get()

    def status_url(self):
        return reverse("payments:order_status", args=[self.order.access_token])

    def test_status_is_pending_while_pix_not_paid(self):
        body = self.client.get(self.status_url()).json()
        self.assertFalse(body["paid"])
        self.assertEqual(body["status"], Order.Status.AWAITING_PAYMENT)

    def test_polling_confirms_order_when_provider_says_paid(self):
        self.provider.paid = True

        body = self.client.get(self.status_url()).json()

        self.assertTrue(body["paid"])
        self.order.refresh_from_db()
        self.assertEqual(self.order.status, Order.Status.PAID)
        self.assertEqual(Payment.objects.get().status, Payment.Status.CONFIRMED)
        # Custódia: o crédito entra retido e nada é repassado ainda.
        from apps.wallet.models import WalletEntry

        credit = WalletEntry.objects.get(order=self.order, kind=WalletEntry.Kind.SALE_CREDIT)
        # Custodia guarda so o item; o frete tem parcela propria e sai na hora.
        self.assertEqual(credit.amount, self.order.payout_total)
        self.assertEqual(
            [w for w in self.provider.withdrawals if w["reference"].startswith("pedido-")], []
        )

    def test_polling_twice_does_not_credit_twice(self):
        from apps.wallet.models import WalletEntry

        self.provider.paid = True
        self.client.get(self.status_url())
        self.client.get(self.status_url())

        self.assertEqual(
            WalletEntry.objects.filter(order=self.order, kind=WalletEntry.Kind.SALE_CREDIT).count(), 1
        )

    def test_payer_with_another_cpf_is_refunded(self):
        self.provider.paid = True
        self.provider.payer_document = "52998224725"  # CPF diferente do pedido

        self.client.get(self.status_url())

        self.order.refresh_from_db()
        self.assertEqual(self.order.status, Order.Status.REFUNDED)
        self.assertEqual(self.provider.refunds, ["pay_1"])
        self.assertEqual(self.provider.withdrawals, [])
        self.product.refresh_from_db()
        self.assertEqual(self.product.stock, 1)

    def test_matching_payer_cpf_is_accepted(self):
        self.provider.paid = True
        self.provider.payer_document = CPF_BUYER

        self.client.get(self.status_url())

        self.order.refresh_from_db()
        self.assertEqual(self.order.status, Order.Status.PAID)
        self.assertEqual(self.provider.refunds, [])
