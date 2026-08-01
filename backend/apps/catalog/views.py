import json

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
    ProductAddon,
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


@login_required
def seller_products_page(request):
    """Lista os anúncios da loja para editar preço, estoque ou tirar do ar."""
    store = getattr(request.user, "store", None)
    if not store:
        return render(request, "wallet/no_store.html")

    products = (
        store.products.select_related("category")
        .prefetch_related("images")
        .order_by("-created_at")
    )
    return render(
        request,
        "catalog/seller_products.html",
        {
            "store": store,
            "products": products,
            "categories": Category.objects.order_by("name"),
            "commission_percent": settings.PLATFORM_COMMISSION_PERCENT,
        },
    )


class ProductUpdateView(APIView):
    """
    PATCH /api/vendedora/anuncios/<id>/ — edição do anúncio.
    POST  .../pausar/ e .../publicar/ — tirar do ar e voltar.

    Mexer em título ou descrição devolve o anúncio para a fila de
    moderação: é conteúdo novo, e conteúdo novo não vai ao ar sem
    revisão (docs/BASE_JURIDICA.md § 3). Corrigir preço ou estoque não
    tira o anúncio do ar.
    """

    permission_classes = [IsAuthenticated]
    throttle_scope = "offers"

    def get_product(self, request, product_id):
        store = getattr(request.user, "store", None)
        if not store:
            raise PermissionDenied("Usuário não possui loja.")
        product = get_object_or_404(Product, id=product_id, store=store)
        if product.status not in Product.SELLER_EDITABLE_STATUSES:
            raise PermissionDenied("Este anúncio está bloqueado pela moderação.")
        return product

    def patch(self, request, product_id):
        from .serializers import ProductUpdateSerializer

        product = self.get_product(request, product_id)
        serializer = ProductUpdateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        payload = serializer.validated_data

        content_changed = False
        for field in ("title", "description"):
            if field in payload and payload[field] != getattr(product, field):
                setattr(product, field, payload[field])
                content_changed = True
        if "category_id" in payload:
            product.category = payload["category_id"]
        for field in ("payout_amount", "stock", "weight_grams", "production_days"):
            if field in payload:
                setattr(product, field, payload[field])

        # Estoque zerado por edição = esgotado, não "pausado pela moderação".
        if product.stock == 0 and product.status == Product.Status.PUBLISHED:
            product.status = Product.Status.SOLD
        elif product.stock > 0 and product.status == Product.Status.SOLD:
            product.status = Product.Status.PUBLISHED

        flags = []
        if content_changed:
            flags = run_automated_filters(title=product.title, description=product.description)
            product.status = Product.Status.PENDING_MODERATION

        product.save()

        if content_changed:
            ModerationQueueItem.objects.create(
                target_type=ModerationQueueItem.TargetType.PRODUCT,
                content_type=ContentType.objects.get_for_model(Product),
                object_id=str(product.id),
                decision=(
                    ModerationQueueItem.Decision.AUTO_FLAGGED
                    if flags
                    else ModerationQueueItem.Decision.PENDING
                ),
                automated_flags=flags,
            )

        return Response(
            {
                "id": str(product.id),
                "status": product.status,
                "status_label": product.get_status_display(),
                "buyer_price": str(product.price),
                "payout_amount": str(product.payout_amount),
                "stock": product.stock,
                "back_to_moderation": content_changed,
            }
        )


class ProductPauseView(APIView):
    """POST /api/vendedora/anuncios/<id>/pausar/ — tira o anúncio da vitrine."""

    permission_classes = [IsAuthenticated]
    throttle_scope = "offers"

    def post(self, request, product_id):
        product = ProductUpdateView().get_product(request, product_id)
        product.status = Product.Status.PAUSED
        product.save(update_fields=["status"])
        return Response({"status": product.status, "status_label": product.get_status_display()})


class ProductResumeView(APIView):
    """
    POST /api/vendedora/anuncios/<id>/publicar/ — volta o anúncio ao ar.

    Só sai do pausado; anúncio que a moderação derrubou não volta por aqui.
    """

    permission_classes = [IsAuthenticated]
    throttle_scope = "offers"

    def post(self, request, product_id):
        product = ProductUpdateView().get_product(request, product_id)
        if product.status != Product.Status.PAUSED:
            return Response(
                {"detail": "Só anúncio pausado pode ser reativado."},
                status=status.HTTP_409_CONFLICT,
            )
        if product.stock < 1:
            return Response(
                {"detail": "Coloque pelo menos 1 unidade em estoque antes de reativar."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        product.status = Product.Status.PUBLISHED
        product.save(update_fields=["status"])
        return Response({"status": product.status, "status_label": product.get_status_display()})


@login_required
def seller_questions_page(request):
    """
    Caixa de perguntas da vendedora. Responder rápido é o que destrava a
    compra de quem está em dúvida — por isso as sem resposta vêm primeiro.
    """
    store = getattr(request.user, "store", None)
    if not store:
        return render(request, "wallet/no_store.html")

    questions = (
        ProductQuestion.objects.filter(product__store=store)
        .select_related("product")
        .order_by("answered_at", "-created_at")
    )
    pending = [q for q in questions if not q.answer]
    answered = [q for q in questions if q.answer][:30]
    return render(
        request,
        "catalog/seller_questions.html",
        {"store": store, "pending": pending, "answered": answered},
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
        # Os adicionais chegam como JSON num campo do multipart (nao da
        # para aninhar objeto em FormData sem isso).
        raw_addons = data.get("addons") or "[]"
        try:
            addons_payload = json.loads(raw_addons) if isinstance(raw_addons, str) else raw_addons
        except json.JSONDecodeError:
            return Response(
                {"addons": "Formato inválido nos adicionais."}, status=status.HTTP_400_BAD_REQUEST
            )

        serializer = ProductCreateSerializer(
            data={
                **data.dict(),
                "addons": addons_payload or [],
                "images": request.FILES.getlist("images"),
                "videos": request.FILES.getlist("videos"),
                "assets": request.FILES.getlist("assets"),
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
            kind=payload["kind"],
            payout_amount=payload["payout_amount"],
            weight_grams=payload["weight_grams"],
            length_cm=payload["length_cm"],
            width_cm=payload["width_cm"],
            height_cm=payload["height_cm"],
            production_days=payload.get("production_days", 0),
            stock=payload["stock"],
            status=Product.Status.PENDING_MODERATION,
        )
        for index, image in enumerate(payload["images"]):
            ProductImage.objects.create(product=product, file=image, is_cover=(index == 0), order=index)
        for index, video in enumerate(payload.get("videos", [])):
            ProductVideo.objects.create(product=product, file=video, order=index)
        for index, asset in enumerate(payload.get("assets", [])):
            ProductAsset.objects.create(
                product=product, file=asset, label=asset.name[:80], order=index
            )
        for index, addon in enumerate(payload.get("addons", [])):
            ProductAddon.objects.create(
                product=product,
                title=addon["title"],
                description=addon.get("description", ""),
                payout_amount=addon["payout_amount"],
                order=index,
            )

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
