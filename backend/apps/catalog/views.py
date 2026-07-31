from django.conf import settings
from django.contrib.auth.decorators import login_required
from django.contrib.contenttypes.models import ContentType
from django.db import transaction
from django.shortcuts import get_object_or_404, render
from django.utils.text import slugify
from rest_framework import parsers, status
from rest_framework.exceptions import PermissionDenied
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.moderation.models import ModerationQueueItem
from apps.moderation.services import run_automated_filters
from apps.stores.models import Store

from .models import Category, Product, ProductImage, ProductVideo, price_from_payout
from .serializers import ProductCreateSerializer


def product_detail(request, store_slug, product_slug):
    store = get_object_or_404(Store, slug=store_slug, status=Store.Status.ACTIVE)
    product = get_object_or_404(
        Product.objects.select_related("store", "category").prefetch_related("images", "videos"),
        store=store,
        slug=product_slug,
        status=Product.Status.PUBLISHED,
    )
    # Item de pedido personalizado: so o comprador que pediu (e a dona da
    # loja) enxergam a pagina - nunca aparece para terceiros nem em buscas.
    if product.visibility == Product.Visibility.PRIVATE:
        allowed = request.user.is_authenticated and (
            request.user == product.reserved_for or request.user == store.owner
        )
        if not allowed:
            from django.http import Http404

            raise Http404
    related_products = (
        Product.objects.filter(
            store=store, status=Product.Status.PUBLISHED, visibility=Product.Visibility.PUBLIC
        )
        .exclude(id=product.id)
        .select_related("category")
        .prefetch_related("images")[:4]
    )

    # Compra aberta (guest ou logado). Age gate do site ainda vale.
    can_buy = product.is_available()

    return render(
        request,
        "catalog/product_detail.html",
        {
            "product": product,
            "store": store,
            "related_products": related_products,
            "can_buy": can_buy,
            "is_authenticated": request.user.is_authenticated,
        },
    )


@login_required
def product_create_page(request):
    store = getattr(request.user, "store", None)
    if not store:
        return render(request, "wallet/no_store.html")
    return render(
        request,
        "catalog/product_create.html",
        {
            "store": store,
            "categories": Category.objects.exclude(name="Pedidos personalizados"),
            "commission_percent": settings.PLATFORM_COMMISSION_PERCENT,
        },
    )


class ProductCreateView(APIView):
    """
    POST /api/vendedora/anuncios/ — cria o anúncio GRATUITAMENTE. O item
    nasce em fila de moderação (nunca publica direto - docs/BASE_JURIDICA.md
    § 3); filtros automáticos anti-serviço-sexual rodam antes.
    """

    permission_classes = [IsAuthenticated]
    parser_classes = [parsers.MultiPartParser, parsers.FormParser]
    throttle_scope = "offers"

    @transaction.atomic
    def post(self, request):
        store = getattr(request.user, "store", None)
        if not store or store.status != Store.Status.ACTIVE:
            raise PermissionDenied("Sua loja precisa estar ativa (aprovada na moderação) para anunciar.")

        data = request.data.copy()
        serializer = ProductCreateSerializer(
            data={
                **data.dict(),
                "images": request.FILES.getlist("images"),
                "videos": request.FILES.getlist("videos"),
            }
        )
        serializer.is_valid(raise_exception=True)
        payload = serializer.validated_data

        flags = run_automated_filters(title=payload["title"], description=payload["description"])

        base_slug = slugify(payload["title"])[:100] or "item"
        slug = base_slug
        suffix = 1
        while Product.objects.filter(store=store, slug=slug).exists():
            suffix += 1
            slug = f"{base_slug}-{suffix}"

        product = Product.objects.create(
            store=store,
            category=payload["category_id"],
            title=payload["title"],
            slug=slug,
            description=payload["description"],
            payout_amount=payload["payout_amount"],
            weight_grams=payload["weight_grams"],
            length_cm=payload["length_cm"],
            width_cm=payload["width_cm"],
            height_cm=payload["height_cm"],
            stock=payload["stock"],
            status=Product.Status.PENDING_MODERATION,
        )
        for index, image in enumerate(payload["images"]):
            ProductImage.objects.create(product=product, file=image, is_cover=(index == 0), order=index)
        for index, video in enumerate(payload.get("videos", [])):
            ProductVideo.objects.create(product=product, file=video, order=index)

        ModerationQueueItem.objects.create(
            target_type=ModerationQueueItem.TargetType.PRODUCT,
            content_type=ContentType.objects.get_for_model(Product),
            object_id=str(product.id),
            decision=(
                ModerationQueueItem.Decision.AUTO_FLAGGED if flags else ModerationQueueItem.Decision.PENDING
            ),
            automated_flags=flags,
        )
        return Response(
            {
                "id": product.id,
                "status": product.status,
                "buyer_price": str(product.price),
                "payout_amount": str(product.payout_amount),
            },
            status=status.HTTP_201_CREATED,
        )
