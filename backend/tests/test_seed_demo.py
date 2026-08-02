from io import BytesIO
from unittest.mock import patch

from django.core.management import call_command
from django.db.models import Max, Min
from django.test import TestCase, override_settings
from PIL import Image

from apps.catalog.models import Product, ProductImage
from apps.core.management.commands.seed_demo import SELLERS
from apps.stores.models import Store


def _jpeg_bytes() -> bytes:
    buf = BytesIO()
    Image.new("RGB", (64, 64), color=(200, 120, 140)).save(buf, format="JPEG")
    return buf.getvalue()


@override_settings(DEBUG=True)
class SeedDemoCatalogTests(TestCase):
    @patch(
        "apps.core.management.commands.seed_demo.fetch_photo",
        side_effect=lambda url, category, title, variant: (_jpeg_bytes(), True),
    )
    def test_seed_demo_creates_stores_products_ceps_and_photos(self, _mock_fetch):
        call_command("seed_demo", "--skip-social", verbosity=0)

        slugs = [row[2] for row in SELLERS]
        stores = Store.objects.filter(slug__in=slugs)
        self.assertGreaterEqual(stores.count(), 20)
        self.assertGreaterEqual(stores.values("origin_cep").distinct().count(), 20)

        products = Product.objects.filter(
            store__in=stores,
            status=Product.Status.PUBLISHED,
            visibility=Product.Visibility.PUBLIC,
        )
        self.assertGreaterEqual(products.count(), 70)
        price_stats = products.aggregate(lo=Min("price"), hi=Max("price"))
        self.assertLess(price_stats["lo"], price_stats["hi"])
        self.assertEqual(
            ProductImage.objects.filter(product__in=products).count(),
            products.count() * 2,
        )
        self.assertTrue(all(store.origin_city and store.origin_state for store in stores))
