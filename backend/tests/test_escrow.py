"""
Custódia: o dinheiro fica parado até a entrega ser confirmada.

É a promessa central da vitrine, então tem que estar coberta: crédito
retido, liberação por confirmação ou por prazo, disputa travando o
repasse e nada de pagar a vendedora duas vezes.
"""
from decimal import Decimal
from unittest import mock

from django.test import override_settings
from django.urls import reverse
from django.utils import timezone

from apps.payments.models import Order
from apps.wallet.models import WalletEntry
from apps.wallet.services import release_matured_escrow

from .base import ApiTestCase
from .factories import FakeProvider, checkout_payload, make_product


class PayoutAssertionsMixin:
    """
    Separa o repasse do ITEM do repasse do FRETE.

    O frete sai na hora do pagamento — é o dinheiro da postagem, e retê-lo
    obrigaria a vendedora a adiantar do bolso. Custódia vale para o valor
    do produto, e é isso que estes testes vigiam.
    """

    def item_payouts(self):
        return [
            w for w in self.provider.withdrawals
            if str(w.get("reference", "")).startswith("pedido-")
        ]

    def shipping_payouts(self):
        return [
            w for w in self.provider.withdrawals
            if str(w.get("reference", "")).startswith("frete-")
        ]

WEBHOOK_TOKEN = "token-webhook"


@override_settings(
    ASAAS_API_KEY="test-key",
    ASAAS_WEBHOOK_TOKEN=WEBHOOK_TOKEN,
    ESCROW_ENABLED=True,
    AUTO_PAYOUT_ON_RELEASE=True,
)
class EscrowTests(PayoutAssertionsMixin, ApiTestCase):
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
        self._pay()
        self.order.refresh_from_db()

    def _pay(self):
        self.provider.paid = True
        self.client.get(reverse("payments:order_status", args=[self.order.access_token]))

    def _confirm(self, action):
        return self.client.post(
            reverse("payments:order_confirm", args=[self.order.access_token]),
            {"action": action},
            content_type="application/json",
        )

    # ----------------------------------------------------------- retencao

    def test_payment_credits_but_holds_the_money(self):
        entry = WalletEntry.objects.get(order=self.order, kind=WalletEntry.Kind.SALE_CREDIT)

        self.assertEqual(self.order.status, Order.Status.PAID)
        self.assertGreater(entry.available_at, timezone.now())
        self.assertEqual(self.item_payouts(), [], "valor do item não pode sair antes da entrega")
        self.assertIsNone(self.order.payout_sent_at)

    def test_available_balance_is_zero_while_in_escrow(self):
        self.assertEqual(WalletEntry.objects.available_balance(self.product.store), Decimal("0.00"))
        self.assertEqual(
            WalletEntry.objects.pending_balance(self.product.store), self.order.payout_total
        )

    # ---------------------------------------------------------- liberacao

    def test_buyer_confirmation_releases_and_pays(self):
        response = self._confirm("confirm")

        self.assertEqual(response.status_code, 200)
        self.order.refresh_from_db()
        entry = WalletEntry.objects.get(order=self.order, kind=WalletEntry.Kind.SALE_CREDIT)
        self.assertEqual(self.order.status, Order.Status.DELIVERED)
        self.assertLessEqual(entry.available_at, timezone.now())
        self.assertEqual(len(self.item_payouts()), 1)
        self.assertEqual(self.item_payouts()[0]["amount"], self.order.payout_total)
        self.assertIsNotNone(self.order.payout_sent_at)

    def test_confirming_twice_does_not_pay_twice(self):
        self._confirm("confirm")
        second = self._confirm("confirm")

        self.assertEqual(second.status_code, 409)
        self.assertEqual(len(self.item_payouts()), 1)

    def test_matured_escrow_is_paid_by_the_cron(self):
        WalletEntry.objects.filter(order=self.order).update(available_at=timezone.now())

        self.assertEqual(release_matured_escrow(), 1)
        self.assertEqual(len(self.item_payouts()), 1)
        # Rodar de novo não paga outra vez.
        self.assertEqual(release_matured_escrow(), 0)
        self.assertEqual(len(self.item_payouts()), 1)

    # ------------------------------------------------------------ disputa

    def test_dispute_freezes_the_money(self):
        response = self._confirm("dispute")

        self.assertEqual(response.status_code, 200)
        self.order.refresh_from_db()
        self.assertEqual(self.order.status, Order.Status.DISPUTED)
        self.assertEqual(self.item_payouts(), [])

    def test_disputed_order_is_skipped_by_the_release_cron(self):
        self._confirm("dispute")
        WalletEntry.objects.filter(order=self.order).update(available_at=timezone.now())

        self.assertEqual(release_matured_escrow(), 0)
        self.assertEqual(self.item_payouts(), [])

    def test_cannot_confirm_after_disputing(self):
        self._confirm("dispute")
        self.assertEqual(self._confirm("confirm").status_code, 409)

    def test_invalid_action_is_rejected(self):
        self.assertEqual(self._confirm("liberar-tudo").status_code, 400)

    def test_wrong_token_cannot_release_someone_elses_order(self):
        response = self.client.post(
            reverse("payments:order_confirm", args=["token-que-nao-existe"]),
            {"action": "confirm"},
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 404)
        self.assertEqual(self.item_payouts(), [])


@override_settings(ASAAS_API_KEY="test-key", ESCROW_ENABLED=False, AUTO_PAYOUT_ON_PAYMENT=True)
class NoEscrowTests(PayoutAssertionsMixin, ApiTestCase):
    """Modo sem custódia: repasse imediato na confirmação do pagamento."""

    def setUp(self):
        super().setUp()
        self.provider = FakeProvider(paid=True)
        patcher = mock.patch("apps.payments.services.get_payment_provider", return_value=self.provider)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.product = make_product(stock=1)

    def test_seller_is_paid_right_after_payment(self):
        self.client.post(
            reverse("payments:checkout"),
            checkout_payload(self.product),
            content_type="application/json",
        )
        order = Order.objects.get()
        self.client.get(reverse("payments:order_status", args=[order.access_token]))

        self.assertEqual(len(self.item_payouts()), 1)
        entry = WalletEntry.objects.get(order=order, kind=WalletEntry.Kind.SALE_CREDIT)
        self.assertLessEqual(entry.available_at, timezone.now())
