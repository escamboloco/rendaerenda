from datetime import date

from django.test import TestCase, override_settings
from django.urls import reverse

from apps.accounts.models import SellerKYC, User


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
        from django.core import mail

        self.assertEqual(len(mail.outbox), 1)
        self.assertIn(self.user.email, mail.outbox[0].to)

    def test_profile_has_logout_password_and_delete(self):
        self.client.force_login(self.user)
        response = self.client.get(reverse("accounts_pages:profile_page"))
        self.assertContains(response, "Sair da conta")
        self.assertContains(response, reverse("account_reset_password"))
        self.assertContains(response, reverse("accounts_pages:delete_account"))

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
