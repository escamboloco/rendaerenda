"""Travas de acesso: age gate, webhook de KYC e visibilidade de itens privados."""
import json
from datetime import date
from decimal import Decimal

from django.test import override_settings
from django.urls import reverse

from apps.accounts.models import AgeVerification
from apps.catalog.models import Product

from .base import ApiTestCase
from .factories import make_product, make_user


class AgeGateTests(ApiTestCase):
    def setUp(self):
        super().setUp()
        # Estes testes exercitam o gate — começam sem confirmação.
        session = self.client.session
        session.pop("age_gate_confirmed", None)
        session.save()

    def test_public_page_redirects_to_age_gate(self):
        response = self.client.get("/")
        self.assertEqual(response.status_code, 302)
        self.assertIn("/entrada/", response["Location"])

    def test_confirming_adult_unlocks_the_site(self):
        self.client.post(reverse("core:age_gate"), {"confirm_adult": "yes", "next": "/"})
        self.assertEqual(self.client.get("/").status_code, 200)

    def test_minor_is_sent_away(self):
        response = self.client.post(reverse("core:age_gate"), {"confirm_adult": "no", "next": "/"})
        self.assertEqual(response.status_code, 302)
        self.assertNotIn("rendaerenda", response["Location"])

    def test_open_redirect_is_blocked(self):
        response = self.client.post(
            reverse("core:age_gate"), {"confirm_adult": "yes", "next": "https://site-malicioso.example/"}
        )
        self.assertEqual(response["Location"], "/")

    def test_healthcheck_and_robots_stay_public(self):
        self.assertEqual(self.client.get("/healthz/").status_code, 200)
        self.assertEqual(self.client.get("/robots.txt").status_code, 200)


class KycWebhookTests(ApiTestCase):
    """A verificação de idade é a trava legal do site — não pode ter bypass."""

    def setUp(self):
        super().setUp()
        self.user = make_user()
        self.verification = AgeVerification.objects.create(
            user=self.user, provider="idwall", provider_reference_id="ref-123"
        )
        self.url = reverse("accounts_webhooks:age_verification_webhook")

    def post(self, token):
        return self.client.post(
            self.url,
            data=json.dumps(
                {
                    "reference_id": "ref-123",
                    "approved": True,
                    "document_validated": True,
                    "birth_date": "1990-01-01",
                }
            ),
            content_type="application/json",
            headers={"X-Kyc-Webhook-Token": token},
        )

    @override_settings(AGE_KYC_API_KEY="")
    def test_empty_token_cannot_approve_anyone(self):
        response = self.post("")

        self.assertEqual(response.status_code, 503)
        self.user.refresh_from_db()
        self.assertFalse(self.user.is_age_verified)

    @override_settings(AGE_KYC_API_KEY="chave-do-provider")
    def test_wrong_token_is_rejected(self):
        self.assertEqual(self.post("outra-chave").status_code, 403)
        self.user.refresh_from_db()
        self.assertFalse(self.user.is_age_verified)

    @override_settings(AGE_KYC_API_KEY="chave-do-provider")
    def test_valid_token_applies_the_result(self):
        self.assertEqual(self.post("chave-do-provider").status_code, 200)
        self.user.refresh_from_db()
        self.assertTrue(self.user.is_age_verified)


class PrivateProductTests(ApiTestCase):
    """Item de pedido personalizado só existe para quem encomendou."""

    def setUp(self):
        super().setUp()
        session = self.client.session
        session["age_gate_confirmed"] = True
        session.save()
        self.buyer = make_user(role="buyer")
        self.product = make_product(
            payout=Decimal("50.00"),
            visibility=Product.Visibility.PRIVATE,
            reserved_for=self.buyer,
        )
        self.url = reverse("catalog:detail", args=[self.product.store.slug, self.product.slug])

    def test_stranger_gets_404(self):
        self.assertEqual(self.client.get(self.url).status_code, 404)

    def test_owner_of_the_request_can_see_it(self):
        self.client.force_login(self.buyer)
        self.assertEqual(self.client.get(self.url).status_code, 200)

    def test_private_item_is_not_in_the_showcase(self):
        response = self.client.get("/")
        self.assertNotContains(response, self.product.title)
