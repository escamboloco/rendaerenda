"""
Desfecho da disputa: estorno de verdade (PSP + ledger + estoque) ou
liberação para a vendedora.

O caso mais perigoso é o reembolso depois do crédito: sem estornar o
ledger, a vendedora ficaria com saldo de uma venda que voltou.
"""
from decimal import Decimal
from unittest import mock

from django.db.models import Sum
from django.test import override_settings
from django.urls import reverse

from apps.catalog.models import Product
from apps.payments.checkout import refund_order
from apps.payments.models import Order, Payment
from apps.wallet.models import WalletEntry

from .base import ApiTestCase
from .factories import FakeProvider, checkout_payload, make_product


@override_settings(ASAAS_API_KEY="test-key", ESCROW_ENABLED=True)
class DisputeResolutionTests(ApiTestCase):
    def setUp(self):
        super().setUp()
        self.provider = FakeProvider()
        patcher = mock.patch("apps.payments.services.get_payment_provider", return_value=self.provider)
        patcher.start()
        self.addCleanup(patcher.stop)

        self.product = make_product(payout=Decimal("100.00"), stock=1)
        self.client.post(
            reverse("payments:checkout"),
            checkout_payload(self.product),
            content_type="application/json",
        )
        self.order = Order.objects.get()
        self.provider.paid = True
        self.client.get(reverse("payments:order_status", args=[self.order.access_token]))
        self.order.refresh_from_db()

    def balance(self):
        total = WalletEntry.objects.filter(store=self.product.store).aggregate(
            total=Sum("amount")
        )["total"]
        return total or Decimal("0.00")

    # ------------------------------------------------------------ estorno

    def test_refund_calls_the_psp_and_undoes_everything(self):
        self.assertTrue(refund_order(self.order, reason="disputa_procedente"))

        self.order.refresh_from_db()
        self.product.refresh_from_db()
        self.assertEqual(self.provider.refunds, ["pay_1"])
        self.assertEqual(self.order.status, Order.Status.REFUNDED)
        self.assertEqual(Payment.objects.get().status, Payment.Status.REFUNDED)
        self.assertEqual(self.product.stock, 1)
        self.assertEqual(self.product.status, Product.Status.PUBLISHED)

    def test_refund_wipes_the_seller_credit(self):
        """
        Reembolso tira da vendedora o que o comprador recebeu de volta.

        Com etiqueta pela plataforma, só a embalagem neutra foi Pixada na
        confirmação — o saldo fica negativo nesse valor (dívida dela).
        """
        packaging = self.order.packaging_fee or Decimal("0.00")
        # Embalagem já saiu via Pix na confirmação; o item ainda está creditado.
        self.assertEqual(self.balance(), self.order.payout_total)

        refund_order(self.order)

        # Dívida = embalagem já Pixada (transportadora ficou na plataforma).
        self.assertEqual(self.balance(), -packaging)

    def test_refunding_twice_does_not_double_reverse(self):
        refund_order(self.order)
        balance_after_first = self.balance()
        refund_order(self.order)

        self.assertEqual(self.balance(), balance_after_first)
        self.assertEqual(
            WalletEntry.objects.filter(
                order=self.order, kind=WalletEntry.Kind.ADJUSTMENT
            ).count(),
            2,  # um estorno do item, um do frete
        )

    def test_order_without_charge_cannot_be_refunded(self):
        Payment.objects.all().delete()
        self.order.refresh_from_db()

        self.assertFalse(refund_order(self.order))
        self.assertEqual(self.provider.refunds, [])

    # ---------------------------------------------------------- liberacao

    def test_release_after_dispute_pays_the_seller(self):
        from apps.wallet.services import release_and_payout

        self.client.post(
            reverse("payments:order_confirm", args=[self.order.access_token]),
            {"action": "dispute", "guest_email": self.order.guest_email},
            content_type="application/json",
        )
        self.order.refresh_from_db()
        self.assertEqual(self.order.status, Order.Status.DISPUTED)
        # Frete ja saiu na confirmacao do pagamento; o que nao pode ter
        # saido antes da decisao e o valor do ITEM.
        self.assertEqual(
            [w for w in self.provider.withdrawals if w["reference"].startswith("pedido-")], []
        )

        self.order.status = Order.Status.DELIVERED
        self.order.save(update_fields=["status"])
        self.assertTrue(release_and_payout(self.order))

        self.assertEqual(
            len([w for w in self.provider.withdrawals if w["reference"].startswith("pedido-")]), 1
        )

    def test_webhook_refund_also_reverses_the_credit(self):
        """Estorno que chega pelo webhook segue o mesmo caminho."""
        import json

        self.provider.refunded = True
        self.provider.paid = False
        with override_settings(ASAAS_WEBHOOK_TOKEN="tok"):
            self.client.post(
                reverse("payments_webhooks:asaas_webhook"),
                data=json.dumps({"event": "PAYMENT_REFUNDED", "payment": {"id": "pay_1"}}),
                content_type="application/json",
                headers={"asaas-access-token": "tok"},
            )

        self.assertEqual(self.balance(), -(self.order.packaging_fee or Decimal("0.00")))
