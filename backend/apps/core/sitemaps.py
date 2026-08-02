from django.contrib.sitemaps import Sitemap
from django.db.models import Count, Q
from django.urls import reverse

from apps.catalog.models import Category, Product
from apps.stores.models import Store


class CategorySitemap(Sitemap):
    """
    Páginas de categoria — a porta de entrada de cauda longa do site.
    Categoria sem anúncio ativo fica de fora: página vazia indexada só
    ensina o Google que o site tem conteúdo raso.
    """

    changefreq = "daily"
    priority = 0.6

    def items(self):
        return (
            Category.objects.annotate(
                active_count=Count(
                    "products",
                    filter=Q(
                        products__status=Product.Status.PUBLISHED,
                        products__visibility=Product.Visibility.PUBLIC,
                        products__stock__gt=0,
                        products__store__status=Store.Status.ACTIVE,
                    ),
                )
            )
            .filter(active_count__gt=0)
            .order_by("name")
        )

    def location(self, obj):
        return reverse("stores:category_detail", args=[obj.slug])


class StoreSitemap(Sitemap):
    changefreq = "daily"
    priority = 0.7

    def items(self):
        return Store.objects.filter(status=Store.Status.ACTIVE).order_by("id")

    def location(self, obj):
        return reverse("stores:detail", args=[obj.slug])


class ProductSitemap(Sitemap):
    """
    Anúncios públicos disponíveis. Item privado (pedido personalizado) e
    item esgotado ficam de fora — indexar isso só gera 404 e página vazia.
    """

    changefreq = "daily"
    priority = 0.8
    limit = 5000

    def items(self):
        return (
            Product.objects.filter(
                status=Product.Status.PUBLISHED,
                visibility=Product.Visibility.PUBLIC,
                stock__gt=0,
                store__status=Store.Status.ACTIVE,
            )
            .select_related("store")
            .order_by("-created_at")
        )

    def location(self, obj):
        return reverse("catalog:detail", args=[obj.store.slug, obj.slug])

    def lastmod(self, obj):
        return obj.created_at


class StaticViewSitemap(Sitemap):
    priority = 0.5
    changefreq = "weekly"

    def items(self):
        return [
            "stores:home",
            "stores:listing",
            "stores:categories",
            "stores:how_it_works",
            "stores:sell",
            "stores:ranking",
        ]

    def location(self, item):
        return reverse(item)
