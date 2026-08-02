from datetime import date
from decimal import Decimal

from allauth.account.signals import user_signed_up
from django.core import mail
from django.test import TestCase, override_settings
from django.urls import reverse

from apps.accounts.models import SellerKYC, User
from apps.payments.models import Order, OrderMessage, Payment
from apps.shipping.models import Shipment

from .factories import make_store


@override_settings(EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend")
class AccountAuthPagesTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            username="seller@example.com",
            email="seller@example.com",
            password="Senha-Forte-123!",
            cpf="39053344705",
            birth_date=date(1990, 5, 5),
            role=User.Role.SELLER,
        )

    def test_password_reset_page_and_email(self):
        response = self.client.get(reverse("account_reset_password"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Esqueci a senha")
        posted = self.client.post(
            reverse("account_reset_password"),
            {"email": self.user.email},
        )
        self.assertEqual(posted.status_code, 302)
        self.assertEqual(len(mail.outbox), 1)
        self.assertIn(self.user.email, mail.outbox[0].to)

    def test_signup_welcome_email_has_login_but_never_password(self):
        mail.outbox.clear()
        user_signed_up.send(sender=User, request=None, user=self.user)

        self.assertEqual(len(mail.outbox), 1)
        body = mail.outbox[0].body
        self.assertIn(self.user.email, body)
        self.assertIn("/contas/login/", body)
        self.assertIn("/contas/password/reset/", body)
        self.assertNotIn("Senha-Forte-123!", body)
        self.assertIn("não é enviada", body)

    def test_profile_has_logout_password_and_delete(self):
        self.client.force_login(self.user)
        response = self.client.get(reverse("accounts_pages:profile_page"))
        self.assertContains(response, "Sair da conta")
        self.assertContains(response, reverse("account_reset_password"))
        self.assertContains(response, reverse("accounts_pages:delete_account"))
        self.assertContains(response, "Meu Perfil")
        self.assertContains(response, "Transações e pagamento")

    def test_profile_unifies_order_payment_tracking_and_chat(self):
        store = make_store()
        order = Order.objects.create(
            buyer=self.user,
            store=store,
            access_token="perfil-token-seguro",
            status=Order.Status.SHIPPED,
            items_total=Decimal("80.00"),
            shipping_total=Decimal("12.00"),
            shipping_address={"city": "São Paulo", "state": "SP"},
        )
        Payment.objects.create(
            order=order,
            method=Payment.Method.PIX,
            status=Payment.Status.CONFIRMED,
        )
        Shipment.objects.create(
            order=order,
            service="sf-17",
            estimated_delivery_days=6,
            tracking_code="AA123456789BR",
            status=Shipment.Status.IN_TRANSIT,
        )
        OrderMessage.objects.create(
            order=order,
            sender=OrderMessage.Sender.SELLER,
            body="Seu envio já foi postado.",
        )

        self.client.force_login(self.user)
        response = self.client.get(reverse("accounts_pages:profile_page"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "AA123456789BR")
        self.assertContains(response, "Pix")
        self.assertContains(response, "Seu envio já foi postado.")
        self.assertContains(response, "#{}".format(order.short_id))

    def test_logout_post(self):
        self.client.force_login(self.user)
        response = self.client.post(reverse("account_logout"))
        self.assertEqual(response.status_code, 302)
        follow = self.client.get(reverse("accounts_pages:profile_page"))
        self.assertEqual(follow.status_code, 302)

    def test_kyc_page_mentions_camera_stamp_not_paper(self):
        self.client.force_login(self.user)
        response = self.client.get(reverse("accounts_pages:seller_kyc_page"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Não precisa de papel")
        self.assertContains(response, "Tirar foto com código")
        kyc = SellerKYC.objects.get(user=self.user)
        self.assertTrue(kyc.verification_code.startswith("RR-"))

    def test_rejected_kyc_can_rotate_code(self):
        self.client.force_login(self.user)
        kyc, _ = SellerKYC.objects.get_or_create(user=self.user)
        kyc.status = SellerKYC.Status.REJECTED
        kyc.rejection_reason = "ilegível"
        old = kyc.verification_code
        kyc.save()
        response = self.client.get(
            reverse("accounts_pages:seller_kyc_page") + "?novo_codigo=1"
        )
        self.assertEqual(response.status_code, 302)
        kyc.refresh_from_db()
        self.assertNotEqual(kyc.verification_code, old)
