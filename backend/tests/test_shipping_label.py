"""Etiqueta pré-paga: money flow + compra SuperFrete após pagamento."""
from decimal import Decimal
from unittest import mock

from django.core import mail
from django.test import SimpleTestCase, override_settings
from django.urls import reverse

from apps.payments.models import Order, Payment
from apps.shipping import superfrete
from apps.shipping.superfrete import BoughtLabel
from apps.shipping.tasks import buy_label_for_order, send_shipment_posted_email
from apps.wallet.models import WalletEntry

from .base import ApiTestCase
from .factories import FakeProvider, checkout_payload, make_product


@override_settings(
    SUPERFRETE_TOKEN="token-test",
    SUPERFRETE_SANDBOX=True,
    SUPERFRETE_SERVICES="1,2,17,3",
    SUPERFRETE_USER_AGENT="Renda/1.0 (suporte@example.com)",
)
class SuperFreteClientTests(SimpleTestCase):
    @mock.patch("apps.shipping.superfrete.requests.request")
    def test_calculate_uses_superfrete_contract(self, request):
        response = mock.Mock(status_code=200)
        response.json.return_value = [
            {
                "id": 1,
                "name": "PAC",
                "price": "18.90",
                "delivery_time": 5,
                "company": {"name": "Correios"},
            }
        ]
        request.return_value = response

        options = superfrete.calculate(
            origin_cep="01310-100",
            destination_cep="20020-050",
            weight_grams=300,
            length_cm=16,
            width_cm=11,
            height_cm=2,
            declared_value=Decimal("100"),
        )

        self.assertEqual(options[0]["name"], "PAC")
        kwargs = request.call_args.kwargs
        self.assertEqual(kwargs["json"]["services"], "1,2,17,3")
        self.assertEqual(kwargs["json"]["package"]["weight"], 0.3)
        self.assertEqual(
            kwargs["headers"]["Authorization"],
            "Bearer token-test",
        )

    @mock.patch("apps.shipping.superfrete.requests.request")
    def test_finalize_is_idempotent_when_label_is_already_released(self, request):
        response = mock.Mock(status_code=200)
        response.json.return_value = {
            "id": "sf-123",
            "status": "released",
            "tracking": "AA123456789BR",
            "print": {"url": "https://superfrete.example/label.pdf"},
        }
        request.return_value = response

        label = superfrete.finalize_label("sf-123")

        self.assertEqual(label.tracking_code, "AA123456789BR")
        request.assert_called_once()
        self.assertEqual(request.call_args.args[:2], ("GET", "https://sandbox.superfrete.com/api/v0/order/info/sf-123"))


@override_settings(
    ASAAS_API_KEY="test-key",
    PLATFORM_BUYS_SHIPPING_LABEL=True,
    SUPERFRETE_TOKEN="",
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

    def test_checkout_does_not_charge_packaging_to_buyer(self):
        self.client.post(
            reverse("payments:checkout"),
            checkout_payload(self.product),
            content_type="application/json",
        )
        order = Order.objects.get()
        # Embalagem neutra é custo da vendedora — frete = só transportadora.
        self.assertEqual(order.packaging_fee, Decimal("0.00"))
        self.assertEqual(order.shipping_total, Decimal("18.00"))
        self.assertEqual(order.seller_amount, order.payout_total)
        self.assertEqual(
            order.platform_amount,
            (order.items_total - order.payout_total) + order.shipping_total,
        )

    def test_payment_does_not_credit_packaging_to_seller(self):
        self.client.post(
            reverse("payments:checkout"),
            checkout_payload(self.product),
            content_type="application/json",
        )
        order = Order.objects.get()
        self.provider.paid = True
        self.client.get(reverse("payments:order_status", args=[order.access_token]))
        order.refresh_from_db()

        self.assertFalse(
            WalletEntry.objects.filter(
                order=order, kind=WalletEntry.Kind.SHIPPING_CREDIT
            ).exists()
        )

    @override_settings(EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend")
    def test_buyer_receives_tracking_code_and_order_link(self):
        self.client.post(
            reverse("payments:checkout"),
            checkout_payload(self.product),
            content_type="application/json",
        )
        order = Order.objects.get()
        order.status = Order.Status.PAID
        order.save(update_fields=["status"])
        shipment = order.shipment
        shipment.tracking_code = "AA123456789BR"
        shipment.save(update_fields=["tracking_code"])
        mail.outbox.clear()

        send_shipment_posted_email(str(shipment.id))

        self.assertEqual(len(mail.outbox), 1)
        self.assertIn("AA123456789BR", mail.outbox[0].body)
        self.assertIn(order.track_url, mail.outbox[0].body)

    @override_settings(PLATFORM_BUYS_SHIPPING_LABEL=True)
    def test_buy_label_uses_neutral_sender(self):
        self.client.post(
            reverse("payments:checkout"),
            checkout_payload(self.product),
            content_type="application/json",
        )
        order = Order.objects.get()
        shipment = order.shipment
        shipment.service = "sf-1"
        shipment.save(update_fields=["service"])
        # Pagamento precisa estar pago para comprar etiqueta.
        order.status = Order.Status.PAID
        order.save(update_fields=["status"])

        with mock.patch(
            "apps.shipping.superfrete.create_label",
            return_value="sf-order-1",
        ) as create, mock.patch(
            "apps.shipping.superfrete.finalize_label",
            return_value=BoughtLabel(
                order_id="sf-order-1",
                tracking_code="AA123456789BR",
                label_url="https://superfrete.example/label.pdf",
            ),
        ) as finalize, mock.patch("apps.shipping.labels.send_mail") as mail:
            buy_label_for_order(str(order.id))

        create.assert_called_once()
        finalize.assert_called_once_with("sf-order-1")
        kwargs = create.call_args.kwargs
        self.assertNotIn("seller_name", kwargs)
        self.assertEqual(kwargs["sender"]["name"], "Renda & Renda")
        self.assertEqual(kwargs["sender"]["address"], "Avenida Paulista")
        self.assertEqual(kwargs["products"][0]["name"], "Peça de vestuário usada")
        shipment.refresh_from_db()
        self.assertEqual(shipment.shipping_provider, "superfrete")
        self.assertEqual(shipment.provider_order_id, "sf-order-1")
        self.assertEqual(shipment.label_url, "https://superfrete.example/label.pdf")
        self.assertEqual(shipment.tracking_code, "AA123456789BR")
        mail.assert_called_once()

    @override_settings(
        PLATFORM_BUYS_SHIPPING_LABEL=True,
        SUPERFRETE_SERVICES="17,1,2",
        SUPERFRETE_TOKEN="token-test",
    )
    def test_buy_label_recovers_from_pac_service(self):
        """Checkout com tarifa fixa (pac) ainda compra Mini Envios/SuperFrete."""
        self.client.post(
            reverse("payments:checkout"),
            checkout_payload(self.product),
            content_type="application/json",
        )
        order = Order.objects.get()
        order.status = Order.Status.PAID
        order.save(update_fields=["status"])
        shipment = order.shipment
        shipment.service = "pac"
        shipment.save(update_fields=["service"])

        with mock.patch(
            "apps.shipping.labels.calculate_freight_options",
            side_effect=Exception("offline"),
        ), mock.patch(
            "apps.shipping.superfrete.create_label",
            return_value="sf-order-17",
        ) as create, mock.patch(
            "apps.shipping.superfrete.finalize_label",
            return_value=BoughtLabel(
                order_id="sf-order-17",
                tracking_code="BB123456789BR",
                label_url="https://superfrete.example/mini.pdf",
            ),
        ), mock.patch("apps.shipping.labels.send_mail"):
            buy_label_for_order(str(order.id))

        create.assert_called_once()
        self.assertEqual(create.call_args.kwargs["service_id"], 17)
        shipment.refresh_from_db()
        self.assertEqual(shipment.service, "sf-17")
        self.assertEqual(shipment.label_url, "https://superfrete.example/mini.pdf")

    def test_seller_can_request_label_from_wallet_api(self):
        self.client.post(
            reverse("payments:checkout"),
            checkout_payload(self.product),
            content_type="application/json",
        )
        order = Order.objects.get()
        order.status = Order.Status.PAID
        order.save(update_fields=["status"])
        order.shipment.service = "sf-1"
        order.shipment.save(update_fields=["service"])

        self.client.force_login(self.product.store.owner)
        with mock.patch(
            "apps.shipping.superfrete.create_label",
            return_value="sf-order-api",
        ), mock.patch(
            "apps.shipping.superfrete.finalize_label",
            return_value=BoughtLabel(
                order_id="sf-order-api",
                tracking_code="CC123456789BR",
                label_url="https://superfrete.example/api.pdf",
            ),
        ), mock.patch("apps.shipping.labels.send_mail"):
            response = self.client.post(
                reverse("shipping:request_label", args=[order.id]),
                {},
                content_type="application/json",
            )

        self.assertEqual(response.status_code, 200, response.content)
        body = response.json()
        self.assertEqual(body["status"], "ready")
        self.assertEqual(body["label_url"], "https://superfrete.example/api.pdf")
