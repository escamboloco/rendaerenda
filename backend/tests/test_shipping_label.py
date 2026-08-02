"""Etiqueta pré-paga: money flow + compra Melhor Envio após pagamento."""
from decimal import Decimal
from unittest import mock

from django.test import override_settings
from django.urls import reverse

from apps.payments.models import Order, Payment
from apps.shipping.melhor_envio import BoughtLabel
from apps.shipping.tasks import buy_label_for_order
from apps.wallet.models import WalletEntry

from .base import ApiTestCase
from .factories import FakeProvider, checkout_payload, make_product


@override_settings(
    ASAAS_API_KEY="test-key",
    PLATFORM_BUYS_SHIPPING_LABEL=True,
    MELHOR_ENVIO_TOKEN="",
    CHECKOUT_FREE_SHIPPING=False,
    SHIPPING_FLAT_RATE=Decimal("18.00"),
    PACKAGING_FEE=Decimal("3.90"),
)
class PlatformLabelFlowTests(ApiTestCase):
    def setUp(self):
        super().setUp()
        self.provider = FakeProvider()
        patcher = mock.patch(
            "apps.payments.services.get_payment_provider", return_value=self.provider
        )
        patcher.start()
        self.addCleanup(patcher.stop)
        self.product = make_product(payout=Decimal("100.00"), stock=1)

    def test_checkout_stores_packaging_fee_separately(self):
        self.client.post(
            reverse("payments:checkout"),
            checkout_payload(self.product),
            content_type="application/json",
        )
        order = Order.objects.get()
        self.assertGreater(order.shipping_total, order.packaging_fee)
        self.assertEqual(order.packaging_fee, Decimal("3.90") + Decimal("2.50"))  # fee + envelope
        # Split: vendedora = payout + embalagem; plataforma = comissão + transportadora
        self.assertEqual(order.seller_amount, order.payout_total + order.packaging_fee)
        self.assertEqual(
            order.platform_amount,
            (order.items_total - order.payout_total)
            + (order.shipping_total - order.packaging_fee),
        )

    def test_payment_credits_only_packaging_to_seller(self):
        self.client.post(
            reverse("payments:checkout"),
            checkout_payload(self.product),
            content_type="application/json",
        )
        order = Order.objects.get()
        self.provider.paid = True
        self.client.get(reverse("payments:order_status", args=[order.access_token]))
        order.refresh_from_db()

        shipping = WalletEntry.objects.get(
            order=order, kind=WalletEntry.Kind.SHIPPING_CREDIT
        )
        self.assertEqual(shipping.amount, order.packaging_fee)

    @override_settings(MELHOR_ENVIO_TOKEN="tok-teste", PLATFORM_BUYS_SHIPPING_LABEL=True)
    def test_buy_label_uses_neutral_sender(self):
        self.client.post(
            reverse("payments:checkout"),
            checkout_payload(self.product),
            content_type="application/json",
        )
        order = Order.objects.get()
        shipment = order.shipment
        shipment.service = "me-1"
        shipment.save(update_fields=["service"])

        with mock.patch(
            "apps.shipping.melhor_envio.buy_label",
            return_value=BoughtLabel(
                order_id="me-order-1",
                tracking_code="AA123456789BR",
                label_url="https://melhorenvio.example/label.pdf",
            ),
        ) as buy, mock.patch(
            "apps.shipping.melhor_envio.find_dropoff_points", return_value=[]
        ), mock.patch("apps.shipping.tasks.send_mail"):
            buy_label_for_order(str(order.id))

        buy.assert_called_once()
        kwargs = buy.call_args.kwargs
        self.assertNotIn("seller_name", kwargs)
        shipment.refresh_from_db()
        self.assertEqual(shipment.label_url, "https://melhorenvio.example/label.pdf")
        self.assertEqual(shipment.tracking_code, "AA123456789BR")
