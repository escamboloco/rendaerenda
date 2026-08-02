from datetime import date

from django.test import TestCase, override_settings
from django.urls import reverse

from apps.accounts.models import SellerKYC, User
from apps.stores.models import Store


@override_settings(REQUIRE_SELLER_KYC=True)
class OnboardPageTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            username="seller@example.com",
            email="seller@example.com",
            password="Senha-Forte-123!",
            cpf="11144477735",
            birth_date=date(1990, 1, 1),
        )
        self.client.force_login(self.user)

    def test_onboard_without_kyc_asks_for_documents(self):
        response = self.client.get(reverse("stores:onboard_page"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Enviar documentos de segurança")

    def test_onboard_with_not_sent_kyc(self):
        SellerKYC.objects.create(user=self.user, status=SellerKYC.Status.NOT_SENT)
        response = self.client.get(reverse("stores:onboard_page"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Enviar documentos de segurança")

    def test_onboard_with_rejected_kyc(self):
        SellerKYC.objects.create(
            user=self.user,
            status=SellerKYC.Status.REJECTED,
            rejection_reason="Selfie ilegível",
        )
        response = self.client.get(reverse("stores:onboard_page"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Reenviar documentos")
        self.assertContains(response, "Selfie ilegível")

    def test_onboard_with_pending_kyc_shows_form(self):
        SellerKYC.objects.create(user=self.user, status=SellerKYC.Status.PENDING)
        response = self.client.get(reverse("stores:onboard_page"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Criar loja e continuar")
        self.assertContains(response, "Documentos em análise")

    def test_onboard_already_has_store(self):
        Store.objects.create(
            owner=self.user,
            slug="minha-loja",
            display_name="Minha Loja",
            status=Store.Status.PENDING_MODERATION,
        )
        response = self.client.get(reverse("stores:onboard_page"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "já está criada")
