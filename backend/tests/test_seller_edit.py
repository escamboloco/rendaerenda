"""
Edição e pausa de anúncio pela vendedora.

A regra que importa: corrigir preço/estoque é operação do dia a dia e não
tira o anúncio do ar; mexer em título ou descrição é conteúdo novo e volta
para a moderação.
"""
from decimal import Decimal

from django.test import override_settings
from django.urls import reverse

from apps.catalog.models import Category, Product
from apps.moderation.models import ModerationQueueItem

from .base import ApiTestCase
from .factories import make_product, make_store, make_user


@override_settings(PLATFORM_COMMISSION_PERCENT=Decimal("20"))
class ProductEditTests(ApiTestCase):
    def setUp(self):
        super().setUp()
        self.seller = make_user(role="seller")
        self.store = make_store(self.seller)
        self.product = make_product(self.store, payout=Decimal("100.00"), stock=3)
        self.client.force_login(self.seller)
        self.url = reverse("catalog_api:api_update", args=[self.product.id])

    def patch(self, payload):
        return self.client.patch(self.url, payload, content_type="application/json")

    # ------------------------------------------------------------- preço

    def test_price_change_keeps_the_listing_live(self):
        response = self.patch({"payout_amount": "150.00"})

        self.assertEqual(response.status_code, 200, response.content)
        self.product.refresh_from_db()
        self.assertEqual(self.product.payout_amount, Decimal("150.00"))
        self.assertEqual(self.product.price, Decimal("180.00"))
        self.assertEqual(self.product.status, Product.Status.PUBLISHED)
        self.assertFalse(response.json()["back_to_moderation"])

    def test_stock_change_keeps_the_listing_live(self):
        self.patch({"stock": 7})

        self.product.refresh_from_db()
        self.assertEqual(self.product.stock, 7)
        self.assertEqual(self.product.status, Product.Status.PUBLISHED)

    def test_zeroing_stock_marks_as_sold(self):
        self.patch({"stock": 0})

        self.product.refresh_from_db()
        self.assertEqual(self.product.status, Product.Status.SOLD)

    def test_restocking_brings_it_back(self):
        self.patch({"stock": 0})
        self.patch({"stock": 2})

        self.product.refresh_from_db()
        self.assertEqual(self.product.status, Product.Status.PUBLISHED)

    # -------------------------------------------------------- conteúdo

    def test_text_change_goes_back_to_moderation(self):
        response = self.patch({"description": "Descrição nova, item lavado e embalado."})

        self.assertTrue(response.json()["back_to_moderation"])
        self.product.refresh_from_db()
        self.assertEqual(self.product.status, Product.Status.PENDING_MODERATION)
        self.assertEqual(ModerationQueueItem.objects.count(), 1)

    def test_same_text_does_not_trigger_moderation(self):
        response = self.patch({"title": self.product.title, "payout_amount": "110.00"})

        self.assertFalse(response.json()["back_to_moderation"])
        self.product.refresh_from_db()
        self.assertEqual(self.product.status, Product.Status.PUBLISHED)
        self.assertEqual(ModerationQueueItem.objects.count(), 0)

    def test_external_contact_in_edit_is_flagged(self):
        self.patch({"description": "chama no whatsapp 11999998888"})

        item = ModerationQueueItem.objects.get()
        self.assertEqual(item.decision, ModerationQueueItem.Decision.AUTO_FLAGGED)
        self.product.refresh_from_db()
        self.assertEqual(self.product.status, Product.Status.PENDING_MODERATION)

    def test_category_can_be_corrected(self):
        other = Category.objects.create(name="Meias", slug="meias")
        self.patch({"category_id": other.id})

        self.product.refresh_from_db()
        self.assertEqual(self.product.category_id, other.id)

    def test_empty_payload_is_rejected(self):
        self.assertEqual(self.patch({}).status_code, 400)

    # ----------------------------------------------------- pausar/voltar

    def test_pause_takes_it_off_the_showcase(self):
        response = self.client.post(reverse("catalog_api:api_pause", args=[self.product.id]))

        self.assertEqual(response.status_code, 200)
        self.product.refresh_from_db()
        self.assertEqual(self.product.status, Product.Status.PAUSED)
        self.assertFalse(self.product.is_available())

    def test_paused_listing_disappears_from_the_showcase(self):
        self.client.post(reverse("catalog_api:api_pause", args=[self.product.id]))
        self.client.logout()
        session = self.client.session
        session["age_gate_confirmed"] = True
        session.save()

        self.assertNotContains(self.client.get("/"), self.product.title)

    def test_resume_puts_it_back(self):
        self.client.post(reverse("catalog_api:api_pause", args=[self.product.id]))
        response = self.client.post(reverse("catalog_api:api_resume", args=[self.product.id]))

        self.assertEqual(response.status_code, 200)
        self.product.refresh_from_db()
        self.assertEqual(self.product.status, Product.Status.PUBLISHED)

    def test_resume_requires_stock(self):
        self.patch({"stock": 0})
        self.client.post(reverse("catalog_api:api_pause", args=[self.product.id]))

        response = self.client.post(reverse("catalog_api:api_resume", args=[self.product.id]))

        self.assertEqual(response.status_code, 400)

    def test_resume_only_works_on_paused(self):
        response = self.client.post(reverse("catalog_api:api_resume", args=[self.product.id]))
        self.assertEqual(response.status_code, 409)

    # ---------------------------------------------------------- permissão

    def test_another_seller_cannot_edit(self):
        intruder = make_user(role="seller")
        make_store(intruder)
        self.client.force_login(intruder)

        self.assertEqual(self.patch({"payout_amount": "1.00"}).status_code, 404)
        self.product.refresh_from_db()
        self.assertEqual(self.product.payout_amount, Decimal("100.00"))

    def test_moderation_removed_listing_is_locked(self):
        self.product.status = Product.Status.REMOVED
        self.product.save()

        self.assertEqual(self.patch({"payout_amount": "10.00"}).status_code, 403)

    def test_anonymous_cannot_edit(self):
        self.client.logout()
        self.assertIn(self.patch({"stock": 99}).status_code, (401, 403))
