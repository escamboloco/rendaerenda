from django.contrib.sitemaps import Sitemap
from django.urls import reverse

from apps.stores.models import Store


class StoreSitemap(Sitemap):
    changefreq = "daily"
    priority = 0.7

    def items(self):
        return Store.objects.filter(status=Store.Status.ACTIVE).order_by("id")

    def location(self, obj):
        return reverse("stores:detail", args=[obj.slug])


class StaticViewSitemap(Sitemap):
    priority = 0.5
    changefreq = "weekly"

    def items(self):
        return ["stores:home", "stores:ranking"]

    def location(self, item):
        return reverse(item)
