"""Vitrine, sacola e consulta de CEP — o caminho até o checkout."""
from decimal import Decimal
from unittest import mock

from django.test import override_settings
from django.urls import reverse

from apps.catalog.models import Product
from apps.stores.models import Store

from .base import ApiTestCase
from .factories import make_product, make_store


@override_settings(PLATFORM_COMMISSION_PERCENT=Decimal("20"))
class StorefrontTests(ApiTestCase):
    def setUp(self):
        super().setUp()
        session = self.client.session
        session["age_gate_confirmed"] = True
        session.save()
        self.store = make_store()
        self.product = make_product(self.store, payout=Decimal("100.00"), slug="corset-preto")
        self.product.title = "Corset preto"
        self.product.save()

    def test_home_shows_products_not_only_stores(self):
        response = self.client.get("/")
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Corset preto")
        self.assertContains(response, "120,00")

    def test_search_goes_to_the_catalog(self):
        """Busca na home redireciona: prateleira curada e resultado de busca
        na mesma tela confundem quem procurou uma coisa específica."""
        response = self.client.get("/", {"q": "Corset"})
        self.assertEqual(response.status_code, 302)
        self.assertIn("/anuncios/", response["Location"])

    def test_search_matches_product_title(self):
        make_product(self.store, slug="meia-arrastao", payout=Decimal("30.00"))
        response = self.client.get("/anuncios/", {"q": "Corset"})
        self.assertContains(response, "Corset preto")
        self.assertNotContains(response, "meia-arrastao")

    def test_sold_out_item_leaves_the_showcase(self):
        self.product.stock = 0
        self.product.status = Product.Status.SOLD
        self.product.save()
        self.assertNotContains(self.client.get("/"), "Corset preto")

    def test_item_from_suspended_store_is_hidden(self):
        self.store.status = Store.Status.SUSPENDED
        self.store.save()
        self.assertNotContains(self.client.get("/"), "Corset preto")

    def test_sorting_by_price(self):
        make_product(self.store, slug="item-barato", payout=Decimal("10.00"))
        response = self.client.get("/anuncios/", {"ordem": "menor-preco"})
        content = response.content.decode()
        self.assertLess(content.index("12,00"), content.index("120,00"))

    def test_product_page_renders_buy_box(self):
        response = self.client.get(
            reverse("catalog:detail", args=[self.store.slug, self.product.slug])
        )
        self.assertContains(response, "Comprar agora")
        self.assertContains(response, "via Pix ou cartão")

    def test_checkout_page_is_reachable(self):
        self.assertEqual(self.client.get(reverse("payments_pages:checkout_page")).status_code, 200)


@override_settings(PLATFORM_COMMISSION_PERCENT=Decimal("20"))
class CartSummaryTests(ApiTestCase):
    """O preço do checkout vem do servidor — nunca do navegador."""

    def setUp(self):
        super().setUp()
        self.product = make_product(payout=Decimal("100.00"), stock=2)
        self.url = reverse("payments:cart_summary")

    def post(self, payload):
        return self.client.post(self.url, payload, content_type="application/json")

    def test_prices_come_from_the_database(self):
        body = self.post(
            {"items": [{"id": str(self.product.id), "qty": 1, "price": "0.01"}]}
        ).json()

        self.assertEqual(body["items"][0]["price"], "120.00")
        self.assertEqual(body["grand_total"], "120.00")

    def test_quantity_is_capped_at_available_stock(self):
        body = self.post({"items": [{"id": str(self.product.id), "qty": 99}]}).json()

        self.assertEqual(body["items"][0]["qty"], 2)
        self.assertEqual(body["grand_total"], "240.00")

    def test_unavailable_item_is_reported_not_charged(self):
        self.product.status = Product.Status.SOLD
        self.product.stock = 0
        self.product.save()

        body = self.post({"items": [{"id": str(self.product.id), "qty": 1}]}).json()

        self.assertEqual(body["items"], [])
        self.assertEqual(len(body["unavailable"]), 1)

    def test_items_from_a_second_store_are_flagged(self):
        other = make_product(slug="outra-loja-item")
        body = self.post(
            {"items": [{"id": str(self.product.id), "qty": 1}, {"id": str(other.id), "qty": 1}]}
        ).json()

        self.assertEqual(len(body["items"]), 1)
        self.assertEqual(len(body["unavailable"]), 1)

    def test_empty_cart_is_not_an_error(self):
        body = self.post({"items": []}).json()
        self.assertEqual(body["items"], [])
        self.assertIsNone(body["store"])


class CepLookupTests(ApiTestCase):
    """O navegador nunca fala com o ViaCEP direto (CSP fechada + privacidade)."""

    def test_rejects_malformed_cep(self):
        self.assertEqual(self.client.get("/api/cep/123/").status_code, 400)

    @mock.patch("apps.core.views.requests.get")
    def test_returns_normalized_address(self, mocked_get):
        mocked_get.return_value.status_code = 200
        mocked_get.return_value.raise_for_status.return_value = None
        mocked_get.return_value.json.return_value = {
            "logradouro": "Avenida Paulista",
            "bairro": "Bela Vista",
            "localidade": "São Paulo",
            "uf": "SP",
        }

        body = self.client.get("/api/cep/01310100/").json()

        self.assertEqual(body["street"], "Avenida Paulista")
        self.assertEqual(body["state"], "SP")

    @mock.patch("apps.core.views.requests.get")
    def test_unknown_cep_returns_404(self, mocked_get):
        mocked_get.return_value.raise_for_status.return_value = None
        mocked_get.return_value.json.return_value = {"erro": True}

        self.assertEqual(self.client.get("/api/cep/99999999/").status_code, 404)

    @override_settings(USE_LOCMEM_CACHE=True)
    @mock.patch("apps.core.views.requests.get", side_effect=Exception("timeout"))
    def test_provider_down_does_not_break_checkout(self, _mocked_get):
        response = self.client.get("/api/cep/01310101/")
        self.assertIn(response.status_code, (503, 500))
