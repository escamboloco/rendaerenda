from datetime import timedelta

from django.conf import settings
from django.contrib.auth.decorators import login_required
from django.contrib.contenttypes.models import ContentType
from django.shortcuts import get_object_or_404, render
from django.utils import timezone
from rest_framework import status
from rest_framework.exceptions import PermissionDenied
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.catalog.models import Category
from apps.moderation.models import ModerationQueueItem
from apps.moderation.services import run_automated_filters
from apps.payments.services import get_payment_provider

from .models import BoostPackage, Store, StoreBoost, StorePlan
from .serializers import StoreBoostPurchaseSerializer, StoreOnboardSerializer, StorePlanCheckoutSerializer


def home(request):
    stores = (
        Store.objects.filter(status=Store.Status.ACTIVE)
        .select_related("plan")
        .prefetch_related("products")
    )

    query = request.GET.get("q", "").strip()
    if query:
        stores = stores.filter(display_name__icontains=query)

    category_slug = request.GET.get("categoria", "").strip()
    if category_slug:
        stores = stores.filter(products__category__slug=category_slug).distinct()

    boosted_ids = set(
        StoreBoost.objects.filter(paid=True).values_list("store_id", flat=True)
    )
    stores = sorted(stores, key=lambda s: s.id in boosted_ids, reverse=True)

    return render(
        request,
        "stores/home.html",
        {
            "stores": stores,
            "categories": Category.objects.all(),
            "active_category": category_slug,
            "boosted_ids": boosted_ids,
        },
    )


def store_detail(request, slug):
    store = get_object_or_404(Store, slug=slug, status=Store.Status.ACTIVE)
    products = store.products.filter(
        status="published", stock__gt=0, visibility="public"
    ).prefetch_related("images")
    reviews = store.reviews.select_related("buyer").order_by("-created_at")[:20]
    return render(request, "stores/detail.html", {"store": store, "products": products, "reviews": reviews})


def ranking_page(request):
    """
    Ranking das melhores lojas: ordenado por nota bayesiana (media
    ajustada pelo volume de avaliacoes - loja com 1 avaliacao 5 estrelas
    nao fura na frente de loja consolidada), com vendas e numero de
    avaliacoes como desempate. Ver apps.stores.services.
    """
    stores = (
        Store.objects.filter(status=Store.Status.ACTIVE, review_count__gt=0)
        .order_by("-bayesian_rating", "-sales_count", "-review_count")[:50]
    )
    return render(request, "stores/ranking.html", {"stores": stores})


@login_required
def onboard_page(request):
    if hasattr(request.user, "store"):
        return render(request, "stores/onboard.html", {"already_has_store": True, "store": request.user.store})

    seller_kyc = getattr(request.user, "seller_kyc", None)
    return render(
        request,
        "stores/onboard.html",
        {
            "already_has_store": False,
            "seller_kyc": seller_kyc,
            "require_seller_kyc": settings.REQUIRE_SELLER_KYC,
        },
    )


class StoreOnboardView(APIView):
    """
    POST /api/vendedora/loja/ — cria a loja da vendedora (gratuita por
    padrão, sem plano) e a subconta dela no PSP (é essa subconta que
    vai receber o split de cada venda). Exige KYC de vendedora aprovado.
    A loja nasce em moderação - só fica pública depois de aprovada
    (docs/BASE_JURIDICA.md § 3). Ver docs/checkout.md sobre o modelo de
    negócio sem mensalidade.
    """

    permission_classes = [IsAuthenticated]
    throttle_scope = "checkout"

    def post(self, request):
        user = request.user
        if settings.REQUIRE_SELLER_KYC:
            seller_kyc = getattr(user, "seller_kyc", None)
            if not seller_kyc or seller_kyc.status != seller_kyc.Status.APPROVED:
                raise PermissionDenied("KYC de vendedora precisa estar aprovado antes de abrir loja.")
        if not user.cpf:
            raise PermissionDenied("Complete o cadastro com CPF antes de abrir loja.")
        if hasattr(user, "store"):
            return Response({"detail": "Você já tem uma loja."}, status=status.HTTP_409_CONFLICT)

        serializer = StoreOnboardSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        payload = serializer.validated_data
        plan = payload.get("plan_id")
        from apps.payments.services import detect_pix_key_type

        pix_key = payload["pix_key"]
        pix_key_type = (payload.get("pix_key_type") or detect_pix_key_type(pix_key)).upper()

        provider = get_payment_provider()
        subaccount = provider.create_seller_subaccount(
            seller_name=payload["display_name"],
            cpf=user.cpf,
            email=user.email,
        )

        store = Store.objects.create(
            owner=user,
            slug=payload["slug"],
            display_name=payload["display_name"],
            bio=payload.get("bio", ""),
            plan=plan,
            plan_expires_at=(timezone.now() + timedelta(days=plan.duration_days)) if plan else None,
            psp_subaccount_id=subaccount.provider_subaccount_id,
            psp_api_key=subaccount.api_key or "",
            pix_key=pix_key,
            pix_key_type=pix_key_type,
            origin_cep=payload["origin_cep"],
        )
        # Nome/bio da loja nunca podem ser canal de contato pessoal (telefone,
        # whatsapp, @handle) - mesma trava usada em pedidos personalizados e
        # avaliações (docs/BASE_JURIDICA.md § 3). Sinalizado, nunca bloqueado
        # na hora - a moderação humana decide.
        flags = run_automated_filters(title=payload["display_name"], description=payload.get("bio", ""))
        ModerationQueueItem.objects.create(
            target_type=ModerationQueueItem.TargetType.STORE,
            content_type=ContentType.objects.get_for_model(Store),
            object_id=str(store.id),
            decision=(
                ModerationQueueItem.Decision.AUTO_FLAGGED if flags else ModerationQueueItem.Decision.PENDING
            ),
            automated_flags=flags,
        )
        return Response({"id": store.id, "status": store.status}, status=status.HTTP_201_CREATED)


class StorePlanCheckoutView(APIView):
    """
    POST /api/vendedora/loja/plano/checkout/ — cobra (sem split, 100%
    plataforma) o plano de loja escolhido. A loja em si so e criada
    depois, via StoreOnboardView, quando a vendedora confirma que pagou
    (fluxo manual em duas etapas no front - ver templates/stores/onboard.html).
    """

    permission_classes = [IsAuthenticated]
    throttle_scope = "checkout"

    def post(self, request):
        seller_kyc = getattr(request.user, "seller_kyc", None)
        if not seller_kyc or seller_kyc.status != seller_kyc.Status.APPROVED:
            raise PermissionDenied("KYC de vendedora precisa estar aprovado antes de pagar o plano.")

        serializer = StorePlanCheckoutSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        plan = serializer.validated_data["plan_id"]

        provider = get_payment_provider()
        charge = provider.create_charge(
            reference_id=f"store-plan:{request.user.id}",
            method=serializer.validated_data["payment_method"],
            amount=plan.price,
            customer_cpf=request.user.cpf,
            customer_name=request.user.get_full_name() or request.user.username,
            customer_email=request.user.email,
        )
        return Response(
            {"payment_url": charge.payment_url, "pix_qr_code": charge.pix_qr_code},
            status=status.HTTP_201_CREATED,
        )


class StoreBoostPurchaseView(APIView):
    """POST /api/vendedora/loja/boost/ — compra um boost avulso para a loja."""

    permission_classes = [IsAuthenticated]
    throttle_scope = "checkout"

    def post(self, request):
        store = getattr(request.user, "store", None)
        if not store:
            raise PermissionDenied("Usuário não possui loja.")

        serializer = StoreBoostPurchaseSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        package = get_object_or_404(BoostPackage, id=serializer.validated_data["package_id"])

        # Cobrança do boost segue o mesmo mecanismo de cobrança direta
        # (sem split, 100% para a plataforma) usado no plano da loja -
        # implementar via provider.create_split_charge com seller_amount=0.
        boost = StoreBoost.objects.create(
            store=store,
            package=package,
            ends_at=timezone.now() + timedelta(hours=package.duration_hours),
            paid=False,
        )
        return Response({"id": boost.id, "status": "awaiting_payment"}, status=status.HTTP_201_CREATED)
