"""Lojas verificadas usadas na descoberta visual do cabeçalho."""

from django.db.models import Prefetch, Q
from django.utils import timezone

from apps.catalog.models import Product

from .models import Store


DISCOVERY_PREFIXES = ("/anuncios/", "/categorias/", "/ranking/", "/loja/")


def header_store_carousel(request):
    """
    Adiciona lojas com produtos reais apenas às páginas de descoberta.

    O prefetch carrega as fotos sem N+1 queries. Checkout, conta, APIs e
    painéis privados não pagam o custo desta consulta.
    """
    path = request.path
    if not (path == "/" or path.startswith(DISCOVERY_PREFIXES)):
        return {}

    published_products = (
        Product.objects.filter(
            status=Product.Status.PUBLISHED,
            visibility=Product.Visibility.PUBLIC,
            stock__gt=0,
        )
        .prefetch_related("images")
        .order_by("-sold_count", "-created_at")
    )
    now = timezone.now()
    stores = (
        Store.objects.filter(status=Store.Status.ACTIVE)
        .filter(Q(plan__isnull=True) | Q(plan_expires_at__gt=now))
        .filter(
            products__status=Product.Status.PUBLISHED,
            products__visibility=Product.Visibility.PUBLIC,
            products__stock__gt=0,
        )
        .prefetch_related(
            Prefetch(
                "products",
                queryset=published_products,
                to_attr="showcase_products",
            )
        )
        .order_by("-bayesian_rating", "-sales_count", "-created_at")
        .distinct()[:14]
    )
    return {"header_stores": stores}
