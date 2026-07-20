from django.contrib import admin
from django.contrib.sitemaps.views import sitemap
from django.urls import include, path

import apps.accounts.urls as accounts_urls
import apps.catalog.urls as catalog_urls
import apps.core.urls as core_urls
import apps.moderation.urls as moderation_urls
import apps.offers.urls as offers_urls
import apps.payments.urls as payments_urls
import apps.reviews.urls as reviews_urls
import apps.stores.urls as stores_urls
import apps.subscriptions.urls as subscriptions_urls
import apps.wallet.urls as wallet_urls
from apps.core.sitemaps import StaticViewSitemap, StoreSitemap

sitemaps = {"stores": StoreSitemap, "static": StaticViewSitemap}

api_urlpatterns = [
    path("", include((accounts_urls.urlpatterns, "accounts"))),
    path("", include((payments_urls.urlpatterns, "payments"))),
    path("", include((stores_urls.api_urlpatterns, "stores_api"))),
    path("", include((wallet_urls.api_urlpatterns, "wallet_api"))),
    path("", include((subscriptions_urls.api_urlpatterns, "subscriptions_api"))),
    path("", include((moderation_urls.api_urlpatterns, "moderation_api"))),
    path("", include((offers_urls.api_urlpatterns, "offers_api"))),
    path("", include((catalog_urls.api_urlpatterns, "catalog_api"))),
    path("", include((reviews_urls.api_urlpatterns, "reviews_api"))),
    path("", include("apps.shipping.urls")),
]

webhook_urlpatterns = [
    path("", include((accounts_urls.webhook_urlpatterns, "accounts_webhooks"))),
    path("", include((payments_urls.webhook_urlpatterns, "payments_webhooks"))),
]

urlpatterns = [
    path("admin/", admin.site.urls),
    path("entrada/", include("apps.core.urls")),
    path("contas/", include("allauth.urls")),
    path("api/", include(api_urlpatterns)),
    path("webhooks/", include(webhook_urlpatterns)),
    path("", include((core_urls.page_urlpatterns, "core_pages"))),
    path("", include((accounts_urls.page_urlpatterns, "accounts_pages"))),
    path("", include((payments_urls.page_urlpatterns, "payments_pages"))),
    path("sitemap.xml", sitemap, {"sitemaps": sitemaps}, name="sitemap"),
    path("", include("apps.subscriptions.urls")),
    path("", include("apps.wallet.urls")),
    path("", include("apps.offers.urls")),
    path("", include("apps.catalog.urls")),
    path("", include("apps.stores.urls")),
]
