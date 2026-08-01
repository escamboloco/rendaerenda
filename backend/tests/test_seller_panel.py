"""
Painel da vendedora: criar anúncio pelo site (sem admin do Django).

Cobre os três tipos de anúncio, os adicionais pagos e as travas que
impedem anúncio quebrado (digital sem arquivo, físico sem peso).
"""
import json
from decimal import Decimal

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import override_settings
from django.urls import reverse

from apps.catalog.models import Category, Product
from apps.stores.models import Store

from .base import ApiTestCase
from .factories import make_store, make_user

# GIF 1x1 valido — o serializer usa ImageField, entao precisa ser imagem de verdade.
TINY_GIF = (
    b"GIF89a\x01\x00\x01\x00\x80\x00\x00\x00\x00\x00\xff\xff\xff!"
    b"\xf9\x04\x01\x00\x00\x00\x00,\x00\x00\x00\x00\x01\x00\x01\x00\x00\x02\x02D\x01\x00;"
)


def image(name="foto.gif"):
    return SimpleUploadedFile(name, TINY_GIF, content_type="image/gif")


@override_settings(PLATFORM_COMMISSION_PERCENT=Decimal("20"))
class ProductCreateTests(ApiTestCase):
    def setUp(self):
        super().setUp()
        self.seller = make_user(role="seller")
        self.store = make_store(self.seller)
        self.category = Category.objects.create(name="Calcinhas", slug="calcinhas")
        self.url = reverse("catalog_api:api_create")
        self.client.force_login(self.seller)

    def base_payload(self, **overrides):
        payload = {
            "title": "Calcinha de renda preta",
            "description": "Peça usada por 3 dias, embalagem discreta.",
            "category_id": str(self.category.id),
            "kind": "physical",
            "payout_amount": "100.00",
            "weight_grams": "150",
            "stock": "1",
            "images": image(),
        }
        payload.update(overrides)
        return payload

    # ------------------------------------------------------------- fisico

    def test_seller_creates_physical_listing(self):
        response = self.client.post(self.url, self.base_payload())

        self.assertEqual(response.status_code, 201, response.content)
        product = Product.objects.get()
        self.assertEqual(product.kind, Product.Kind.PHYSICAL)
        self.assertEqual(product.price, Decimal("120.00"))
        self.assertEqual(product.status, Product.Status.PENDING_MODERATION)
        self.assertTrue(product.requires_shipping)
        self.assertEqual(product.images.count(), 1)

    def test_physical_listing_requires_weight(self):
        response = self.client.post(self.url, self.base_payload(weight_grams="0"))

        self.assertEqual(response.status_code, 400)
        self.assertIn("weight_grams", response.json())
        self.assertEqual(Product.objects.count(), 0)

    # ------------------------------------------------------------ digital

    def test_seller_creates_digital_listing_with_file(self):
        response = self.client.post(
            self.url,
            self.base_payload(
                kind="digital",
                weight_grams="0",
                stock="50",
                assets=SimpleUploadedFile("pack.txt", b"conteudo"),
            ),
        )

        self.assertEqual(response.status_code, 201, response.content)
        product = Product.objects.get()
        self.assertEqual(product.kind, Product.Kind.DIGITAL)
        self.assertFalse(product.requires_shipping)
        self.assertEqual(product.weight_grams, 0)
        self.assertEqual(product.assets.count(), 1)

    def test_digital_listing_without_file_is_rejected(self):
        response = self.client.post(self.url, self.base_payload(kind="digital", weight_grams="0"))

        self.assertEqual(response.status_code, 400)
        self.assertIn("assets", response.json())
        self.assertEqual(Product.objects.count(), 0)

    # ---------------------------------------------------------- encomenda

    def test_custom_listing_keeps_production_deadline(self):
        response = self.client.post(
            self.url, self.base_payload(kind="custom", production_days="5")
        )

        self.assertEqual(response.status_code, 201, response.content)
        self.assertEqual(Product.objects.get().production_days, 5)

    # --------------------------------------------------------- adicionais

    def test_addons_are_created_with_commission_on_top(self):
        addons = [
            {"title": "Com bilhete à mão", "description": "escrito por mim", "payout_amount": "20.00"},
            {"title": "Mais 2 dias de uso", "payout_amount": "30.00"},
        ]
        response = self.client.post(self.url, self.base_payload(addons=json.dumps(addons)))

        self.assertEqual(response.status_code, 201, response.content)
        product = Product.objects.get()
        self.assertEqual(product.addons.count(), 2)
        first = product.addons.first()
        self.assertEqual(first.title, "Com bilhete à mão")
        self.assertEqual(first.payout_amount, Decimal("20.00"))
        self.assertEqual(first.price, Decimal("24.00"))

    def test_malformed_addons_json_is_rejected(self):
        response = self.client.post(self.url, self.base_payload(addons="{isso nao e json"))

        self.assertEqual(response.status_code, 400)
        self.assertEqual(Product.objects.count(), 0)

    def test_addon_without_value_is_rejected(self):
        addons = [{"title": "Sem preço", "payout_amount": "0"}]
        response = self.client.post(self.url, self.base_payload(addons=json.dumps(addons)))

        self.assertEqual(response.status_code, 400)
        self.assertEqual(Product.objects.count(), 0)

    # ----------------------------------------------------------- permissao

    def test_listing_is_rejected_without_an_active_store(self):
        self.store.status = Store.Status.PENDING_MODERATION
        self.store.save()

        response = self.client.post(self.url, self.base_payload())

        self.assertEqual(response.status_code, 403)
        self.assertEqual(Product.objects.count(), 0)

    def test_anonymous_cannot_create_listing(self):
        self.client.logout()
        response = self.client.post(self.url, self.base_payload())

        self.assertIn(response.status_code, (401, 403))
        self.assertEqual(Product.objects.count(), 0)

    def test_listing_with_external_contact_goes_to_manual_review(self):
        from apps.moderation.models import ModerationQueueItem

        response = self.client.post(
            self.url,
            self.base_payload(description="me chama no whatsapp 11999998888 pra combinar tudo"),
        )

        self.assertEqual(response.status_code, 201)
        item = ModerationQueueItem.objects.get()
        self.assertEqual(item.decision, ModerationQueueItem.Decision.AUTO_FLAGGED)
        self.assertTrue(item.automated_flags)
        self.assertEqual(Product.objects.get().status, Product.Status.PENDING_MODERATION)

    def test_slug_does_not_collide_within_the_store(self):
        self.client.post(self.url, self.base_payload())
        self.client.post(self.url, self.base_payload())

        slugs = list(Product.objects.values_list("slug", flat=True))
        self.assertEqual(len(slugs), len(set(slugs)))
