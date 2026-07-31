from django.conf import settings
from django.contrib.auth.decorators import login_required
from django.contrib.contenttypes.models import ContentType
from django.db import transaction
from django.db.models import F
from django.shortcuts import get_object_or_404, render
from django.utils import timezone
from django.utils.text import slugify
from rest_framework import parsers, status
from rest_framework.exceptions import PermissionDenied
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.moderation.models import ModerationQueueItem
from apps.moderation.services import run_automated_filters
from apps.stores.models import Store

from .models import (
    Category,
    Product,
    ProductAsset,
    ProductImage,
    ProductQuestion,
    ProductVideo,
    price_from_payout,
)
from .serializers import ProductCreateSerializer


def product_detail(request, store_slug, product_slug):
    store = get_object_or_404(Store, slug=store_slug, status=Store.Status.ACTIVE)
    product = get_object_or_404(
        Product.objects.select_related("store", "category").prefetch_related(
            "images", "videos", "addons", "questions"
        ),
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
    image_urls = [image.file.url for image in product.images.all()]
    addons = [a for a in product.addons.all() if a.is_active]
    questions = [q for q in product.questions.all() if q.is_public]

    # Contador de visualizacoes: update direto no banco, sem race e sem
    # disparar o save() do model (que recalcularia preco a toa).
    Product.objects.filter(pk=product.pk).update(views_count=F("views_count") + 1)

    return render(
        request,
        "catalog/product_detail.html",
        {
            "product": product,
            "store": store,
            "related_products": related_products,
            "can_buy": can_buy,
            "image_urls": image_urls,
            "addons": addons,
            "addons_json": [
                {"id": str(a.id), "title": a.title, "price": str(a.price)} for a in addons
            ],
            "questions": questions,
            "store_reviews": store.reviews.select_related("buyer").order_by("-created_at")[:4],
            "dispute_window_days": settings.DISPUTE_WINDOW_DAYS,
            "is_authenticated": request.user.is_authenticated,
        },
    )


class ProductQuestionCreateView(APIView):
    """
    POST /api/anuncios/<product_id>/perguntas/ — pergunta pública no anúncio.

    Exige login (pergunta é assinada por um perfil) e passa pelo mesmo
    filtro anti-contato-externo do resto da plataforma.
    """

    permission_classes = [IsAuthenticated]
    throttle_scope = "offers"

    def post(self, request, product_id):
        product = get_object_or_404(
            Product, id=product_id, status=Product.Status.PUBLISHED, visibility=Product.Visibility.PUBLIC
        )
        if product.store.owner_id == request.user.id:
            raise PermissionDenied("Você não pergunta no próprio anúncio.")

        text = (request.data.get("question") or "").strip()
        if not 5 <= len(text) <= 300:
            return Response(
                {"detail": "Escreva a pergunta com pelo menos 5 caracteres."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        if run_automated_filters(title="", description=text):
            return Response(
                {
                    "detail": (
                        "A pergunta precisa ser sobre o item. Combinar contato ou "
                        "serviço fora da plataforma não é permitido."
                    )
                },
                status=status.HTTP_400_BAD_REQUEST,
            )

        question = ProductQuestion.objects.create(
            product=product, asked_by=request.user, question=text
        )
        return Response(
            {"id": str(question.id), "question": question.question},
            status=status.HTTP_201_CREATED,
        )


class ProductAnswerView(APIView):
    """POST /api/anuncios/perguntas/<question_id>/responder/ — resposta da vendedora."""

    permission_classes = [IsAuthenticated]
    throttle_scope = "offers"

    def post(self, request, question_id):
        question = get_object_or_404(
            ProductQuestion.objects.select_related("product__store"), id=question_id
        )
        if question.product.store.owner_id != request.user.id:
            raise PermissionDenied("Só a dona do anúncio responde.")

        text = (request.data.get("answer") or "").strip()
        if not 2 <= len(text) <= 600:
            return Response({"detail": "Escreva uma resposta."}, status=status.HTTP_400_BAD_REQUEST)
        if run_automated_filters(title="", description=text):
            return Response(
                {"detail": "A resposta não pode conter contatos externos nem menção a serviços."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        question.answer = text
        question.answered_at = timezone.now()
        question.save(update_fields=["answer", "answered_at"])
        return Response({"id": str(question.id), "answer": question.answer})


def download_asset(request, token, asset_id):
    """
    Entrega do conteúdo digital. O link só funciona para quem tem o token
    do pedido, com o pedido pago e o arquivo pertencendo a um item dele.
    """
    from django.http import FileResponse, Http404

    from apps.payments.models import Order

    order = get_object_or_404(
        Order.objects.prefetch_related("items__product"), access_token=token
    )
    if order.status not in (Order.Status.PAID, Order.Status.SHIPPED, Order.Status.DELIVERED):
        raise Http404
    asset = get_object_or_404(ProductAsset, id=asset_id)
    if asset.product_id not in {item.product_id for item in order.items.all()}:
        raise Http404
    return FileResponse(asset.file.open("rb"), as_attachment=True, filename=asset.file.name.split("/")[-1])


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
