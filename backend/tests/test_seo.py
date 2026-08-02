"""
Descoberta do site: página de categoria, sitemap e prévia de link.

O que estes testes protegem é o canal de aquisição — Google Ads e Meta não
aceitam o nicho (docs/BASE_JURIDICA.md § 6), então busca orgânica e link
compartilhado no X são a divulgação. Prévia sem imagem ou categoria fora do
índice custa tráfego direto.
"""
import io
import json
import re
import tempfile

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import override_settings
from django.urls import reverse
from PIL import Image

from apps.catalog.models import Category, Product, ProductImage
from apps.core.templatetags.seo import meta_text

from .base import ApiTestCase
from .factories import make_product, make_store

MEDIA_ROOT = tempfile.mkdtemp()


def make_cover(product, *, size=(800, 1000)) -> ProductImage:
    buffer = io.BytesIO()
    Image.new("RGB", size, (200, 60, 90)).save(buffer, "JPEG")
    return ProductImage.objects.create(
        product=product,
        file=SimpleUploadedFile("capa.jpg", buffer.getvalue(), content_type="image/jpeg"),
        is_cover=True,
    )


class StructuredDataTests(ApiTestCase):
    """
    Todo bloco `application/ld+json` do site tem que ser JSON válido.

    Bloco quebrado é descartado inteiro pelo Google, e o estrago é
    silencioso: a página continua respondendo 200 e ninguém percebe. Já
    aconteceu com um `{# comentário #}` de duas linhas dentro do <script>
    — o Django só reconhece essa forma numa linha só, e o resto vazou
    literal para dentro do JSON.
    """

    def setUp(self):
        super().setUp()
        session = self.client.session
        session["age_gate_confirmed"] = True
        session.save()
        self.store = make_store()
        self.product = make_product(self.store, slug="corset-preto")
        self.product.description = 'Peça "especial".\r\nCom aspas, quebra de linha e / barra.'
        self.product.save()

    def assert_json_ld_is_valid(self, url):
        content = self.client.get(url).content.decode()
        blocks = re.findall(
            r'<script type="application/ld\+json">(.*?)</script>', content, re.S
        )
        self.assertGreater(len(blocks), 0, f"{url} não declarou nenhum dado estruturado")
        for block in blocks:
            try:
                json.loads(block)
            except json.JSONDecodeError as error:
                self.fail(f"JSON-LD inválido em {url}: {error}\n{block}")

    def test_every_public_page_ships_valid_json_ld(self):
        for url in (
            "/",
            reverse("stores:detail", args=[self.store.slug]),
            reverse("catalog:detail", args=[self.store.slug, self.product.slug]),
            reverse("stores:category_detail", args=[self.product.category.slug]),
        ):
            with self.subTest(url=url):
                self.assert_json_ld_is_valid(url)

    def test_product_declares_used_condition_and_seller(self):
        content = self.client.get(
            reverse("catalog:detail", args=[self.store.slug, self.product.slug])
        ).content.decode()
        product_ld = next(
            json.loads(b)
            for b in re.findall(r'<script type="application/ld\+json">(.*?)</script>', content, re.S)
            if json.loads(b).get("@type") == "Product"
        )

        self.assertEqual(product_ld["itemCondition"], "https://schema.org/UsedCondition")
        self.assertEqual(product_ld["offers"]["seller"]["name"], self.store.display_name)
        # A nota é da loja, não da peça — reaproveitá-la aqui é marcação enganosa.
        self.assertNotIn("aggregateRating", product_ld)


class MetaTextTests(ApiTestCase):
    """
    `truncatechars` não serve para meta description: em pt-BR a string de
    truncamento do Django é `" %(truncated_text)s…"` — com espaço na
    frente —, e isso ia parar no resultado de busca e no card do X.
    """

    def test_short_text_is_left_alone(self):
        self.assertEqual(meta_text("Calcinha de renda preta.", 100), "Calcinha de renda preta.")

    def test_truncated_text_does_not_start_with_a_space(self):
        result = meta_text("Meias 7/8 pretas usadas por quatro dias seguidos.", 20)

        self.assertFalse(result.startswith(" "), repr(result))
        self.assertTrue(result.endswith("…"), repr(result))

    def test_cuts_on_a_whole_word(self):
        self.assertEqual(meta_text("um dois tres quatro cinco", 14), "um dois tres…")

    def test_line_breaks_from_the_textarea_are_collapsed(self):
        self.assertEqual(meta_text("  Sutiã\n\npreto  usado\t1 vez  ", 100), "Sutiã preto usado 1 vez")

    def test_product_meta_description_is_clean(self):
        store = make_store()
        product = make_product(store, slug="meia-longa")
        product.description = "Meia 7/8 preta.\r\nUsada em ocasião especial." + " detalhe" * 40
        product.save()
        session = self.client.session
        session["age_gate_confirmed"] = True
        session.save()

        content = self.client.get(
            reverse("catalog:detail", args=[store.slug, product.slug])
        ).content.decode()
        description = re.search(r'name="description" content="([^"]*)"', content).group(1)

        self.assertFalse(description.startswith(" "), repr(description))
        self.assertNotIn("\n", description)


class CategoryPageTests(ApiTestCase):
    """Filtro em query string não ranqueia — a categoria precisa de URL própria."""

    def setUp(self):
        super().setUp()
        session = self.client.session
        session["age_gate_confirmed"] = True
        session.save()
        self.store = make_store()
        self.product = make_product(self.store, slug="corset-preto")
        self.category = self.product.category
        self.url = reverse("stores:category_detail", args=[self.category.slug])

    def test_category_has_its_own_indexable_page(self):
        response = self.client.get(self.url)

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, self.product.title)
        self.assertContains(response, 'name="robots" content="index, follow"')
        self.assertContains(response, f'rel="canonical" href="http://testserver{self.url}"')

    def test_category_page_declares_an_item_list(self):
        content = self.client.get(self.url).content.decode()

        self.assertIn('"@type": "CollectionPage"', content)
        self.assertIn('"@type": "ItemList"', content)
        self.assertIn(
            reverse("catalog:detail", args=[self.store.slug, self.product.slug]), content
        )

    def test_unknown_category_is_404(self):
        self.assertEqual(self.client.get("/categorias/nao-existe/").status_code, 404)

    def test_category_page_uses_its_own_text_when_there_is_one(self):
        self.category.description = "Peças de renda enviadas em embalagem neutra."
        self.category.save()

        self.assertContains(self.client.get(self.url), "Peças de renda enviadas")

    def test_filtered_listing_points_the_canonical_at_the_category_page(self):
        response = self.client.get("/anuncios/", {"categoria": self.category.slug})

        self.assertContains(response, f'rel="canonical" href="http://testserver{self.url}"')

    def test_listing_with_more_than_one_filter_is_its_own_page(self):
        response = self.client.get("/anuncios/", {"categoria": self.category.slug, "tipo": "fisico"})

        self.assertContains(response, 'rel="canonical" href="http://testserver/anuncios/?')

    def test_sitemap_lists_categories_that_have_stock(self):
        empty = Category.objects.create(name="Vazia", slug="vazia")

        content = self.client.get("/sitemap.xml").content.decode()

        self.assertIn(self.url, content)
        self.assertNotIn(reverse("stores:category_detail", args=[empty.slug]), content)


@override_settings(MEDIA_ROOT=MEDIA_ROOT)
class LinkPreviewTests(ApiTestCase):
    """
    X, WhatsApp e Telegram descartam SVG e buscam a imagem muito depois de
    ler o HTML — a URL assinada do bucket já expirou. Por isso a prévia tem
    endereço próprio, estável e fora do age gate.
    """

    def setUp(self):
        super().setUp()
        session = self.client.session
        session["age_gate_confirmed"] = True
        session.save()
        self.store = make_store()
        self.product = make_product(self.store, slug="corset-preto")
        self.og_url = reverse(
            "core_pages:og_product", args=[self.store.slug, self.product.slug]
        )

    def test_default_preview_is_a_bitmap(self):
        """SVG é descartado por X, WhatsApp e Telegram — o card sai sem imagem."""
        content = self.client.get("/").content.decode()

        og_image = re.search(r'property="og:image" content="([^"]+)"', content).group(1)
        self.assertTrue(og_image.startswith("http"), og_image)
        self.assertTrue(og_image.endswith(".png"), og_image)
        self.assertNotIn(".svg", content)
        self.assertIn('name="twitter:card" content="summary_large_image"', content)

    def test_product_page_points_the_preview_at_its_own_cover(self):
        make_cover(self.product)

        response = self.client.get(
            reverse("catalog:detail", args=[self.store.slug, self.product.slug])
        )

        self.assertContains(response, f'content="http://testserver{self.og_url}"')

    def test_preview_is_rendered_at_the_card_size(self):
        make_cover(self.product)

        response = self.client.get(self.og_url)

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response["Content-Type"], "image/jpeg")
        self.assertEqual(Image.open(io.BytesIO(response.content)).size, (1200, 630))

    def test_preview_does_not_need_the_age_gate_session(self):
        make_cover(self.product)
        self.client.logout()
        self.client.cookies.clear()

        self.assertEqual(self.client.get(self.og_url).status_code, 200)

    def test_item_without_photo_falls_back_to_the_brand_image(self):
        response = self.client.get(self.og_url)

        self.assertEqual(response.status_code, 302)
        self.assertIn("og-brand", response["Location"])
        self.assertTrue(response["Location"].endswith(".png"), response["Location"])

    def test_unpublished_item_has_no_preview(self):
        make_cover(self.product)
        self.product.status = Product.Status.PENDING_MODERATION
        self.product.save()

        self.assertEqual(self.client.get(self.og_url).status_code, 404)

    def test_private_item_has_no_preview_and_stays_out_of_the_index(self):
        """Item de pedido personalizado: sem prévia, e a página que só o
        comprador enxerga sai do índice."""
        make_cover(self.product)
        self.product.visibility = Product.Visibility.PRIVATE
        self.product.reserved_for = self.store.owner
        self.product.save()

        self.assertEqual(self.client.get(self.og_url).status_code, 404)

        self.client.force_login(self.store.owner)
        page = self.client.get(reverse("catalog:detail", args=[self.store.slug, self.product.slug]))
        self.assertContains(page, 'name="robots" content="noindex, nofollow"')

    def test_store_preview_uses_the_shop_cover(self):
        make_cover(self.product)

        response = self.client.get(reverse("core_pages:og_store", args=[self.store.slug]))

        self.assertEqual(response.status_code, 200)
        self.assertEqual(Image.open(io.BytesIO(response.content)).size, (1200, 630))
