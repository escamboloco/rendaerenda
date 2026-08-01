"""
Conversa do pedido e pagamento por cartão.

A conversa é o canal que substitui o "me chama no zap" — por isso o
filtro anti-contato-externo vale aqui igual ao resto da plataforma.
"""
import json
from decimal import Decimal
from unittest import mock

from django.core import mail
from django.test import override_settings
from django.urls import reverse

from apps.payments.models import Order, OrderMessage, Payment

from .base import ApiTestCase
from .factories import FakeProvider, checkout_payload, make_product, make_user


@override_settings(ASAAS_API_KEY="test-key")
class OrderChatTests(ApiTestCase):
    def setUp(self):
        super().setUp()
        self.provider = FakeProvider()
        patcher = mock.patch("apps.payments.services.get_payment_provider", return_value=self.provider)
        patcher.start()
        self.addCleanup(patcher.stop)

        self.product = make_product(stock=1)
        self.seller = self.product.store.owner
        self.client.post(
            reverse("payments:checkout"),
            checkout_payload(self.product),
            content_type="application/json",
        )
        self.order = Order.objects.get()
        self.url = reverse("payments:order_messages", args=[self.order.access_token])

    def send(self, body):
        return self.client.post(self.url, {"body": body}, content_type="application/json")

    # -------------------------------------------------------------- envio

    def test_buyer_with_the_token_can_write(self):
        response = self.send("Oi! Consegue postar amanhã?")

        self.assertEqual(response.status_code, 201, response.content)
        message = OrderMessage.objects.get()
        self.assertEqual(message.sender, OrderMessage.Sender.BUYER)
        self.assertTrue(response.json()["mine"])

    def test_seller_is_identified_by_her_account(self):
        self.client.force_login(self.seller)
        self.send("Posto amanhã de manhã!")

        self.assertEqual(OrderMessage.objects.get().sender, OrderMessage.Sender.SELLER)

    def test_logged_stranger_counts_as_buyer_side(self):
        """Quem não é a dona da loja é a outra ponta — o token é o acesso."""
        self.client.force_login(make_user(role="buyer"))
        self.send("mensagem")

        self.assertEqual(OrderMessage.objects.get().sender, OrderMessage.Sender.BUYER)

    def test_wrong_token_finds_nothing(self):
        response = self.client.post(
            reverse("payments:order_messages", args=["token-invalido"]),
            {"body": "oi"},
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 404)
        self.assertEqual(OrderMessage.objects.count(), 0)

    def test_empty_message_is_rejected(self):
        self.assertEqual(self.send("   ").status_code, 400)

    # ------------------------------------------------------------- filtro

    def test_external_contact_is_blocked(self):
        response = self.send("me chama no whatsapp 11999998888")

        self.assertEqual(response.status_code, 400)
        self.assertIn("plataforma", response.json()["detail"])
        self.assertEqual(OrderMessage.objects.count(), 0)

    # ------------------------------------------------------------ leitura

    def test_thread_is_returned_in_order(self):
        self.send("primeira")
        self.client.force_login(self.seller)
        self.send("resposta")

        body = self.client.get(self.url).json()

        self.assertEqual([m["body"] for m in body["messages"]], ["primeira", "resposta"])
        self.assertEqual(body["role"], "seller")
        self.assertTrue(body["messages"][1]["mine"])
        self.assertFalse(body["messages"][0]["mine"])

    def test_expired_order_closes_the_thread(self):
        self.order.status = Order.Status.EXPIRED
        self.order.save(update_fields=["status"])

        self.assertEqual(self.send("ainda dá?").status_code, 409)


@override_settings(
    ASAAS_API_KEY="test-key",
    ASAAS_WEBHOOK_TOKEN="tok",
    MODERATION_ALERT_EMAIL="moderacao@example.com",
    EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend",
)
class DisputeAlertTests(ApiTestCase):
    def setUp(self):
        super().setUp()
        self.provider = FakeProvider(paid=True)
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
        self.client.get(reverse("payments:order_status", args=[self.order.access_token]))
        mail.outbox.clear()

    def test_dispute_notifies_seller_and_moderation(self):
        self.client.post(
            reverse("payments:order_confirm", args=[self.order.access_token]),
            {"action": "dispute"},
            content_type="application/json",
        )

        recipients = [address for message in mail.outbox for address in message.to]
        self.assertIn("moderacao@example.com", recipients)
        self.assertIn(self.product.store.owner.email, recipients)

    def test_alert_does_not_leak_the_item_title(self):
        self.product.title = "Calcinha de renda vermelha"
        self.product.save()

        self.client.post(
            reverse("payments:order_confirm", args=[self.order.access_token]),
            {"action": "dispute"},
            content_type="application/json",
        )

        for message in mail.outbox:
            self.assertNotIn("Calcinha", message.body)
            self.assertNotIn("Calcinha", message.subject)


@override_settings(ASAAS_API_KEY="test-key")
class CreditCardCheckoutTests(ApiTestCase):
    def setUp(self):
        super().setUp()
        self.provider = FakeProvider()
        patcher = mock.patch("apps.payments.services.get_payment_provider", return_value=self.provider)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.product = make_product(payout=Decimal("100.00"), stock=1)

    def checkout(self, method):
        payload = checkout_payload(self.product)
        payload["payment_method"] = method
        return self.client.post(
            reverse("payments:checkout"), payload, content_type="application/json"
        )

    def test_card_checkout_returns_the_hosted_page(self):
        response = self.checkout("credit_card")

        self.assertEqual(response.status_code, 201, response.content)
        self.assertTrue(response.json()["payment_url"])
        payment = Payment.objects.get()
        self.assertEqual(payment.method, Payment.Method.CREDIT_CARD)
        self.assertEqual(self.provider.charges[0]["method"], "credit_card")

    def test_card_without_hosted_page_cancels_the_order(self):
        """Sem link de pagamento o pedido ficaria impagável — melhor cancelar."""
        from apps.payments.services import ChargeResult

        self.provider.create_split_charge = lambda **kwargs: ChargeResult(
            provider_charge_id="pay_x", payment_url=None, pix_qr_code=None, pix_copy_paste=None
        )

        response = self.checkout("credit_card")

        self.assertEqual(response.status_code, 502)
        self.product.refresh_from_db()
        self.assertEqual(self.product.stock, 1)
        self.assertEqual(Order.objects.get().status, Order.Status.CANCELED)

    def test_unknown_method_is_rejected(self):
        self.assertEqual(self.checkout("boleto").status_code, 400)
