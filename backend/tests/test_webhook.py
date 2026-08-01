"""
Webhook do Asaas — a porta por onde o dinheiro entra.

O que estes testes protegem: token obrigatório, idempotência (o Asaas
reenvia o mesmo evento até receber 200) e o repasse à vendedora saindo
uma única vez por pedido.
"""
import json
from unittest import mock

from django.test import override_settings
from django.urls import reverse

from apps.catalog.models import Product
from apps.payments.models import Order, Payment
from apps.wallet.models import WalletEntry

from .base import ApiTestCase
from .factories import CPF_BUYER, FakeProvider, checkout_payload, make_product

WEBHOOK_TOKEN = "token-secreto-do-webhook"


@override_settings(ASAAS_API_KEY="test-key", ASAAS_WEBHOOK_TOKEN=WEBHOOK_TOKEN)
class AsaasWebhookTests(ApiTestCase):
    def setUp(self):
        super().setUp()
        self.provider = FakeProvider()
        patcher = mock.patch("apps.payments.services.get_payment_provider", return_value=self.provider)
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
        self.url = reverse("payments_webhooks:asaas_webhook")

    def send(self, event="PAYMENT_RECEIVED", *, token=WEBHOOK_TOKEN, charge_id=None):
        body = {
            "event": event,
            "payment": {"id": charge_id or self.payment.provider_charge_id, "status": "RECEIVED"},
        }
        return self.client.post(
            self.url,
            data=json.dumps(body),
            content_type="application/json",
            headers={"asaas-access-token": token},
        )

    # ------------------------------------------------------------ seguranca

    def test_rejects_wrong_token(self):
        self.assertEqual(self.send(token="errado").status_code, 403)
        self.order.refresh_from_db()
        self.assertEqual(self.order.status, Order.Status.AWAITING_PAYMENT)

    @override_settings(ASAAS_WEBHOOK_TOKEN="")
    def test_endpoint_is_closed_when_token_not_configured(self):
        """Sem token no servidor, ninguém marca pedido como pago."""
        self.assertEqual(self.send(token="").status_code, 503)
        self.order.refresh_from_db()
        self.assertEqual(self.order.status, Order.Status.AWAITING_PAYMENT)

    def test_get_returns_ok_for_browser(self):
        self.assertEqual(self.client.get(self.url).status_code, 200)

    def test_unknown_charge_is_acknowledged_without_side_effects(self):
        response = self.send(charge_id="pay_inexistente")
        self.assertEqual(response.status_code, 200)
        self.order.refresh_from_db()
        self.assertEqual(self.order.status, Order.Status.AWAITING_PAYMENT)

    # --------------------------------------------------------- confirmacao

    def test_payment_received_confirms_order_and_holds_the_money(self):
        response = self.send("PAYMENT_RECEIVED")

        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.json()["confirmed_now"])
        self.order.refresh_from_db()
        self.payment.refresh_from_db()
        self.assertEqual(self.order.status, Order.Status.PAID)
        self.assertIsNotNone(self.order.paid_at)
        self.assertIsNone(self.order.expires_at)
        self.assertEqual(self.payment.status, Payment.Status.CONFIRMED)
        # Custódia: o valor do ITEM só sai depois da entrega confirmada.
        # O frete sai antes, de propósito — é o dinheiro da postagem.
        self.assertEqual(
            [w for w in self.provider.withdrawals if w["reference"].startswith("pedido-")], []
        )
        self.assertIsNone(self.order.payout_sent_at)

    def test_payment_confirmed_event_also_works(self):
        self.assertTrue(self.send("PAYMENT_CONFIRMED").json()["confirmed_now"])

    def test_duplicate_webhook_does_not_credit_twice(self):
        self.send("PAYMENT_RECEIVED")
        second = self.send("PAYMENT_CONFIRMED")

        self.assertEqual(second.status_code, 200)
        self.assertFalse(second.json()["confirmed_now"])
        self.assertEqual(
            WalletEntry.objects.filter(order=self.order, kind=WalletEntry.Kind.SALE_CREDIT).count(), 1
        )

    def test_credits_are_split_between_item_and_shipping(self):
        """
        Duas parcelas: item retido em custódia, frete liberado na hora.
        Somadas, batem com o que a vendedora tem a receber; a diferença
        para o total pago é exatamente a comissão da plataforma.
        """
        self.send("PAYMENT_RECEIVED")
        self.order.refresh_from_db()

        item = WalletEntry.objects.get(
            order=self.order, kind=WalletEntry.Kind.SALE_CREDIT
        ).amount
        shipping = WalletEntry.objects.get(
            order=self.order, kind=WalletEntry.Kind.SHIPPING_CREDIT
        ).amount
        self.assertEqual(item, self.order.payout_total)
        self.assertEqual(shipping, self.order.shipping_total)
        self.assertEqual(self.order.grand_total - item - shipping, self.order.platform_amount)

    def test_store_sales_counter_increases_once(self):
        self.send("PAYMENT_RECEIVED")
        self.send("PAYMENT_RECEIVED")

        self.product.store.refresh_from_db()
        self.assertEqual(self.product.store.sales_count, 1)

    # -------------------------------------------------------------- estorno

    def test_refund_event_returns_stock(self):
        self.send("PAYMENT_RECEIVED")
        response = self.send("PAYMENT_REFUNDED")

        self.assertEqual(response.status_code, 200)
        self.order.refresh_from_db()
        self.product.refresh_from_db()
        self.assertEqual(self.order.status, Order.Status.REFUNDED)
        self.assertEqual(self.product.stock, 1)
        self.assertEqual(self.product.status, Product.Status.PUBLISHED)

    def test_refunded_order_cannot_be_confirmed_again(self):
        self.send("PAYMENT_REFUNDED")
        response = self.send("PAYMENT_RECEIVED")

        self.assertFalse(response.json()["confirmed_now"])
        self.assertEqual(self.provider.withdrawals, [])

    def test_payer_with_other_cpf_is_refunded_and_not_paid_out(self):
        self.provider.payer_document = "52998224725"

        self.send("PAYMENT_RECEIVED")

        self.order.refresh_from_db()
        self.assertEqual(self.order.status, Order.Status.REFUNDED)
        self.assertEqual(self.provider.refunds, [self.payment.provider_charge_id])
        self.assertEqual(self.provider.withdrawals, [])
        self.assertFalse(
            WalletEntry.objects.filter(order=self.order, kind=WalletEntry.Kind.SALE_CREDIT).exists()
        )

    @override_settings(REFUND_ON_PAYER_CPF_MISMATCH=False)
    def test_mismatch_can_be_flagged_instead_of_refunded(self):
        self.provider.payer_document = "52998224725"

        self.send("PAYMENT_RECEIVED")

        self.order.refresh_from_db()
        self.payment.refresh_from_db()
        self.assertEqual(self.order.status, Order.Status.PAID)
        self.assertFalse(self.payment.payer_cpf_matched)
        self.assertEqual(self.provider.refunds, [])

    def test_matching_cpf_is_recorded(self):
        self.provider.payer_document = CPF_BUYER

        self.send("PAYMENT_RECEIVED")

        self.payment.refresh_from_db()
        self.assertTrue(self.payment.payer_cpf_matched)
        self.assertEqual(self.payment.payer_document, CPF_BUYER)

    def test_unrelated_event_is_stored_without_changing_the_order(self):
        response = self.send("PAYMENT_OVERDUE")

        self.assertEqual(response.status_code, 200)
        self.order.refresh_from_db()
        self.assertEqual(self.order.status, Order.Status.AWAITING_PAYMENT)
