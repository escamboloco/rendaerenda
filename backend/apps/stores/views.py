from datetime import timedelta

from django.conf import settings
from django.contrib.auth.decorators import login_required
from django.contrib.contenttypes.models import ContentType
from django.core.paginator import Paginator
from django.db.models import Case, Count, IntegerField, Prefetch, Q, Value, When
from django.shortcuts import get_object_or_404, render
from django.urls import reverse
from django.utils import timezone
from rest_framework import status
from rest_framework.exceptions import PermissionDenied
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.catalog.models import Category, Product
from apps.moderation.models import ModerationQueueItem
from apps.moderation.services import run_automated_filters
from apps.payments.services import get_payment_provider

from .models import BoostPackage, Store, StoreBoost, StoreFollow, StorePlan
from .serializers import StoreBoostPurchaseSerializer, StoreOnboardSerializer, StorePlanCheckoutSerializer


SORT_OPTIONS = {
    "relevancia": ("-sold_count", "Relevância"),
    "recentes": ("-created_at", "Mais recentes"),
    "menor-preco": ("price", "Menor preço"),
    "maior-preco": ("-price", "Maior preço"),
    "populares": ("-views_count", "Mais vistos"),
    "melhor-avaliadas": ("-store__bayesian_rating", "Lojas melhor avaliadas"),
}

KIND_FILTERS = {
    "fisico": ("physical", "Itens físicos"),
    "digital": ("digital", "Conteúdo digital"),
    "encomenda": ("custom", "Sob encomenda"),
}


# Conteudo estatico da home. Fica aqui (e nao no template) para o texto
# ser reaproveitado na FAQ estruturada (schema.org) sem duplicar redacao.
INCLUDED_IN_EVERY_ORDER = [
    ("Pagamento em custódia", "O valor fica com a plataforma até você confirmar que recebeu."),
    ("Embalagem neutra", "Caixa sem logo, sem tema e sem remetente que entregue o conteúdo."),
    ("Extrato discreto", "A cobrança aparece com nome neutro, sem citar o site nem o produto."),
    ("Envio rastreado", "Você acompanha o pedido pelo link, do pagamento até a entrega."),
    ("Conversa protegida", "Fale com a vendedora aqui dentro, sem passar telefone nem rede social."),
    ("Direito de contestar", "7 dias após a entrega para abrir disputa e travar o pagamento."),
]

HOME_FAQ = [
    (
        "Preciso criar conta para comprar?",
        "Não. Dá para comprar informando nome, e-mail, CPF e data de nascimento na "
        "hora do pagamento. A conta serve para acompanhar todas as compras num lugar "
        "só, mas não é obrigatória.",
    ),
    (
        "O que aparece na fatura do meu cartão ou no extrato do Pix?",
        "Um nome neutro, que não menciona o site, o tipo de produto nem a vendedora. "
        "Quem olhar o seu extrato não descobre o que foi comprado.",
    ),
    (
        "Como sei que a vendedora vai enviar?",
        "O dinheiro não vai para ela quando você paga. Fica retido na plataforma e só "
        "é liberado quando você confirma o recebimento — ou 7 dias depois da entrega, "
        "se você não responder. Se não chegar, você contesta e o valor trava.",
    ),
    (
        "Por que o Pix precisa sair do mesmo CPF?",
        "Porque é assim que garantimos que quem está comprando é um adulto "
        "identificado. Pagamento vindo de outro CPF é estornado automaticamente.",
    ),
    (
        "Como a embalagem chega?",
        "Sem logotipo, sem indicação do conteúdo e sem remetente que entregue o "
        "assunto. O custo dessa embalagem neutra já está incluído no frete.",
    ),
    (
        "E se eu comprar conteúdo digital?",
        "O arquivo fica disponível na página do pedido assim que o pagamento é "
        "confirmado. Não tem envio nem frete.",
    ),
    (
        "Quanto a plataforma cobra de quem vende?",
        "20% sobre o valor do item, cobrados por cima do que a vendedora pediu — ela "
        "recebe o líquido inteiro. O frete é repassado a ela integralmente. Não há "
        "mensalidade nem taxa para anunciar.",
    ),
]


def public_store_filter(prefix: str = "") -> Q:
    """
    Loja visível ao público: ativa e com plano em dia (plano nulo = grátis).
    Espelha Store.is_public() em SQL para evitar filtrar no Python.
    """
    now = timezone.now()
    field = f"{prefix}status" if prefix else "status"
    plan = f"{prefix}plan__isnull" if prefix else "plan__isnull"
    expires = f"{prefix}plan_expires_at__gt" if prefix else "plan_expires_at__gt"
    return Q(**{field: Store.Status.ACTIVE}) & (Q(**{plan: True}) | Q(**{expires: now}))


def _product_feed(request, *, default_sort="relevancia", per_page=24):
    """
    Feed de anúncios usado pela vitrine e pela listagem completa.

    A ordem padrão premia quem já vendeu (sold_count) — anúncio parado não
    ocupa o topo — e loja com impulsionamento pago entra na frente.
    """
    query = request.GET.get("q", "").strip()
    category_slug = request.GET.get("categoria", "").strip()
    kind_key = request.GET.get("tipo", "").strip()
    sort_key = request.GET.get("ordem", default_sort)
    order_by, _ = SORT_OPTIONS.get(sort_key, SORT_OPTIONS[default_sort])

    products = (
        Product.objects.filter(
            public_store_filter("store__"),
            status=Product.Status.PUBLISHED,
            visibility=Product.Visibility.PUBLIC,
            stock__gt=0,
        )
        .select_related("store", "category")
        .prefetch_related("images")
    )

    if query:
        products = products.filter(
            Q(title__icontains=query)
            | Q(description__icontains=query)
            | Q(store__display_name__icontains=query)
            | Q(category__name__icontains=query)
        )
    if category_slug:
        products = products.filter(category__slug=category_slug)
    if kind_key in KIND_FILTERS:
        products = products.filter(kind=KIND_FILTERS[kind_key][0])

    # Loja com boost ativo aparece antes (é o produto pago da plataforma).
    boosted_ids = set(
        StoreBoost.objects.filter(
            paid=True, starts_at__lte=timezone.now(), ends_at__gte=timezone.now()
        ).values_list("store_id", flat=True)
    )
    products = products.annotate(
        is_boosted=Case(
            When(store_id__in=boosted_ids, then=Value(1)), default=Value(0), output_field=IntegerField()
        )
    ).order_by("-is_boosted", order_by, "-created_at")

    page = Paginator(products, per_page).get_page(request.GET.get("pagina"))

    return {
        "page_obj": page,
        "products": page.object_list,
        "categories": Category.objects.order_by("name"),
        "active_category": category_slug,
        "active_kind": kind_key if kind_key in KIND_FILTERS else "",
        "kind_filters": KIND_FILTERS,
        "sort_options": SORT_OPTIONS,
        "active_sort": sort_key if sort_key in SORT_OPTIONS else default_sort,
        "total_count": page.paginator.count,
        "query": query,
    }


def home(request):
    """
    Vitrine principal: peças à venda (não lojas). É o que faz o marketplace
    parecer marketplace — a pessoa entra e já vê o que pode comprar.

    Busca e filtro vão para o catálogo: a home é feita de prateleiras
    curadas (destaques, novidades, mais vendidos) e misturar resultado de
    busca com prateleira genérica confunde — a pessoa buscou uma coisa e
    via outras dez sem relação.
    """
    from django.shortcuts import redirect

    if any(request.GET.get(key) for key in ("q", "categoria", "tipo", "ordem")):
        return redirect(f"{reverse('stores:listing')}?{request.GET.urlencode()}")

    context = _product_feed(request, per_page=16)
    context.update(
        {
            "featured_stores": (
                Store.objects.filter(public_store_filter())
                .filter(
                    review_count__gt=0,
                    products__status=Product.Status.PUBLISHED,
                    products__visibility=Product.Visibility.PUBLIC,
                    products__stock__gt=0,
                )
                .prefetch_related(
                    Prefetch(
                        "products",
                        queryset=Product.objects.filter(
                            status=Product.Status.PUBLISHED,
                            visibility=Product.Visibility.PUBLIC,
                            stock__gt=0,
                        )
                        .prefetch_related("images")
                        .order_by("-sold_count", "-created_at"),
                        to_attr="showcase_products",
                    )
                )
                .distinct()
                .order_by("-bayesian_rating", "-sales_count")[:8]
            ),
            "top_sellers": (
                Product.objects.filter(
                    public_store_filter("store__"),
                    status=Product.Status.PUBLISHED,
                    visibility=Product.Visibility.PUBLIC,
                    stock__gt=0,
                    sold_count__gt=0,
                )
                .select_related("store")
                .prefetch_related("images")
                .order_by("-sold_count")[:8]
            ),
            "newest": (
                Product.objects.filter(
                    public_store_filter("store__"),
                    status=Product.Status.PUBLISHED,
                    visibility=Product.Visibility.PUBLIC,
                    stock__gt=0,
                )
                .select_related("store")
                .prefetch_related("images")
                .order_by("-created_at")[:8]
            ),
            "home_categories": (
                Category.objects.annotate(
                    active_count=Count(
                        "products",
                        filter=Q(
                            products__status=Product.Status.PUBLISHED,
                            products__visibility=Product.Visibility.PUBLIC,
                            products__stock__gt=0,
                        ),
                    )
                )
                .filter(active_count__gt=0)
                .order_by("-active_count")[:8]
            ),
            # Depoimentos = avaliacoes REAIS de pedidos entregues. Nunca
            # texto inventado: depoimento fabricado e publicidade enganosa
            # (CDC art. 37) e a plataforma responde por isso.
            "testimonials": _recent_testimonials(),
            "included_items": INCLUDED_IN_EVERY_ORDER,
            "faq": HOME_FAQ,
            "commission_percent": settings.PLATFORM_COMMISSION_PERCENT,
            "dispute_window_days": settings.DISPUTE_WINDOW_DAYS,
            "stats": _marketplace_stats(),
        }
    )
    return render(request, "stores/home.html", context)


def _recent_testimonials(limit: int = 6):
    """
    Avaliações recentes com comentário, para a prova social da home.

    Só entram avaliações presas a pedido entregue (o model já garante
    isso) e com nota alta o suficiente para servir de destaque — as
    demais continuam visíveis na página da loja, sem curadoria.
    """
    from apps.reviews.models import Review

    return (
        Review.objects.filter(rating__gte=4)
        .exclude(comment="")
        .select_related("store", "buyer")
        .order_by("-created_at")[:limit]
    )


def _marketplace_stats() -> dict:
    """
    Números reais da vitrine (nunca inventados): se ainda não houver
    volume, a home esconde a seção em vez de exibir prova social falsa.
    """
    from django.db.models import Avg

    from apps.payments.models import Order

    delivered = Order.objects.filter(status=Order.Status.DELIVERED).count()
    rating = Store.objects.filter(review_count__gt=0).aggregate(value=Avg("avg_rating"))["value"]
    return {
        "delivered": delivered,
        "rating": round(rating, 1) if rating else None,
        "show": delivered >= 10,
    }


def listing(request):
    """Catálogo completo com filtros — a página para quem já sabe o que quer."""
    context = _product_feed(request, per_page=24)
    return render(request, "stores/listing.html", context)


def categories_page(request):
    """Índice de categorias com contagem de anúncios ativos."""
    categories = Category.objects.annotate(
        active_count=Count(
            "products",
            filter=Q(
                products__status=Product.Status.PUBLISHED,
                products__visibility=Product.Visibility.PUBLIC,
                products__stock__gt=0,
            ),
        )
    ).order_by("-active_count", "name")
    return render(request, "stores/categories.html", {"categories": categories})


def sell_landing(request):
    """Página de captação de vendedoras: regras, comissão e passo a passo."""
    return render(
        request,
        "stores/sell.html",
        {
            "commission_percent": settings.PLATFORM_COMMISSION_PERCENT,
            "dispute_window_days": settings.DISPUTE_WINDOW_DAYS,
            "release_hours": settings.DELIVERY_CONFIRMATION_WINDOW_HOURS,
        },
    )


def how_it_works(request):
    """Explica a custódia: onde o dinheiro fica e quando ele é liberado."""
    return render(
        request,
        "core/how_it_works.html",
        {
            "dispute_window_days": settings.DISPUTE_WINDOW_DAYS,
            "release_hours": settings.DELIVERY_CONFIRMATION_WINDOW_HOURS,
            "digital_hours": settings.DIGITAL_RELEASE_HOURS,
        },
    )


def store_detail(request, slug):
    store = get_object_or_404(Store, slug=slug, status=Store.Status.ACTIVE)
    products = (
        store.products.filter(
            status=Product.Status.PUBLISHED,
            stock__gt=0,
            visibility=Product.Visibility.PUBLIC,
        )
        .select_related("category")
        .prefetch_related("images")
        .order_by("-created_at")
    )
    reviews = store.reviews.select_related("buyer").order_by("-created_at")[:20]

    # Distribuicao das notas: dizer "4,8 de 5" e abstrato; mostrar quantas
    # deram 5, 4, 3... e o que faz a pessoa confiar (ou desconfiar) com base
    # em dado, nao em media.
    breakdown = []
    if store.review_count:
        counts = dict(
            store.reviews.values_list("rating").annotate(total=Count("rating")).values_list("rating", "total")
        )
        for score in (5, 4, 3, 2, 1):
            total = counts.get(score, 0)
            breakdown.append(
                {"score": score, "total": total, "percent": round(total * 100 / store.review_count)}
            )

    is_owner = request.user.is_authenticated and getattr(request.user, "store", None) == store
    is_following = False
    if request.user.is_authenticated and not is_owner:
        is_following = StoreFollow.objects.filter(store=store, user=request.user).exists()

    pending_products = 0
    open_questions = 0
    if is_owner:
        pending_products = store.products.filter(status=Product.Status.PENDING_MODERATION).count()
        from apps.catalog.models import ProductQuestion

        open_questions = ProductQuestion.objects.filter(
            product__store=store, answer="", answered_at__isnull=True
        ).count()

    return render(
        request,
        "stores/detail.html",
        {
            "store": store,
            "products": products,
            "reviews": reviews,
            "product_count": products.count(),
            "rating_breakdown": breakdown,
            "dispute_window_days": settings.DISPUTE_WINDOW_DAYS,
            "is_owner": is_owner,
            "is_following": is_following,
            "follower_count": store.followers.count(),
            "pending_products": pending_products,
            "open_questions": open_questions,
        },
    )


@login_required
def seller_hub(request):
    """Painel único da vendedora: atalhos, pedidos e saúde da loja."""
    store = getattr(request.user, "store", None)
    if not store:
        return render(request, "wallet/no_store.html")

    from django.db.models import Sum

    from apps.catalog.models import ProductQuestion
    from apps.offers.models import CustomOrderRequest
    from apps.payments.models import Order
    from apps.wallet.models import WalletEntry

    seller_kyc = getattr(request.user, "seller_kyc", None)
    published = store.products.filter(status=Product.Status.PUBLISHED, stock__gt=0).count()
    draft_count = store.products.filter(status=Product.Status.DRAFT).count()
    pending = store.products.filter(status=Product.Status.PENDING_MODERATION).count()
    open_questions = ProductQuestion.objects.filter(
        product__store=store, answer="", answered_at__isnull=True
    ).count()
    open_customs = CustomOrderRequest.objects.filter(
        store=store,
        status__in=[
            CustomOrderRequest.Status.PENDING,
            CustomOrderRequest.Status.COUNTERED,
        ],
    ).count()
    active_orders = Order.objects.filter(
        store=store,
        status__in=[Order.Status.PAID, Order.Status.SHIPPED],
    ).count()
    delivered_orders = Order.objects.filter(store=store, status=Order.Status.DELIVERED).count()
    disputed_orders = Order.objects.filter(store=store, status=Order.Status.DISPUTED).count()
    paid_statuses = [Order.Status.PAID, Order.Status.SHIPPED, Order.Status.DELIVERED]
    gross_sales = (
        Order.objects.filter(store=store, status__in=paid_statuses).aggregate(
            total=Sum("items_total")
        )["total"]
        or 0
    )
    recent_orders = (
        Order.objects.filter(store=store)
        .exclude(status=Order.Status.AWAITING_PAYMENT)
        .select_related("buyer")
        .order_by("-created_at")[:10]
    )
    origin_complete = bool(
        store.origin_cep and store.origin_street and store.origin_city and store.origin_state
    )
    checklist = [
        {
            "label": "KYC enviado (RG frente/verso + selfie)",
            "done": bool(
                seller_kyc
                and seller_kyc.status
                in {seller_kyc.Status.PENDING, seller_kyc.Status.APPROVED}
            ),
            "url": "accounts_pages:seller_kyc_page",
        },
        {
            "label": "KYC aprovado pelo admin",
            "done": bool(seller_kyc and seller_kyc.status == seller_kyc.Status.APPROVED),
            "url": "accounts_pages:seller_kyc_page",
        },
        {
            "label": "Loja liberada na vitrine",
            "done": store.status == Store.Status.ACTIVE,
            "url": "stores:detail",
            "url_args": [store.slug],
        },
        {
            "label": "Endereço de postagem completo",
            "done": origin_complete,
            "url": "wallet:dashboard",
        },
        {
            "label": "Chave Pix cadastrada",
            "done": bool(store.pix_key),
            "url": "wallet:dashboard",
        },
        {
            "label": "Pelo menos 1 anúncio publicado",
            "done": published > 0,
            "url": "catalog:create",
        },
    ]

    return render(
        request,
        "stores/seller_hub.html",
        {
            "store": store,
            "seller_kyc": seller_kyc,
            "published": published,
            "draft_count": draft_count,
            "pending": pending,
            "open_questions": open_questions,
            "open_customs": open_customs,
            "active_orders": active_orders,
            "delivered_orders": delivered_orders,
            "disputed_orders": disputed_orders,
            "gross_sales": gross_sales,
            "available_balance": WalletEntry.objects.available_balance(store),
            "pending_balance": WalletEntry.objects.pending_balance(store),
            "recent_orders": recent_orders,
            "follower_count": store.followers.count(),
            "commission_percent": settings.PLATFORM_COMMISSION_PERCENT,
            "origin_complete": origin_complete,
            "checklist": checklist,
            "require_seller_kyc": settings.REQUIRE_SELLER_KYC,
        },
    )


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
        return render(
            request,
            "stores/onboard.html",
            {
                "already_has_store": True,
                "store": request.user.store,
                "commission_percent": settings.PLATFORM_COMMISSION_PERCENT,
            },
        )

    seller_kyc = getattr(request.user, "seller_kyc", None)
    return render(
        request,
        "stores/onboard.html",
        {
            "already_has_store": False,
            "seller_kyc": seller_kyc,
            "require_seller_kyc": settings.REQUIRE_SELLER_KYC,
            "commission_percent": settings.PLATFORM_COMMISSION_PERCENT,
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
        # Loja pode nascer antes do KYC — fica pendente até o admin
        # conferir RG frente/verso + selfie e liberar a vitrine.
        if settings.REQUIRE_SELLER_KYC:
            seller_kyc = getattr(user, "seller_kyc", None)
            if not seller_kyc or seller_kyc.status not in {
                seller_kyc.Status.PENDING,
                seller_kyc.Status.APPROVED,
            }:
                raise PermissionDenied(
                    "Envie o KYC (RG frente/verso + selfie) antes de abrir a loja. "
                    "Após a análise, a vitrine é liberada."
                )
        if not user.cpf:
            raise PermissionDenied("Complete o cadastro com CPF antes de abrir loja.")
        if hasattr(user, "store"):
            return Response({"detail": "Você já tem uma loja."}, status=status.HTTP_409_CONFLICT)

        serializer = StoreOnboardSerializer(data=request.data, context={"request": request})
        serializer.is_valid(raise_exception=True)
        payload = serializer.validated_data
        from apps.payments.services import detect_pix_key_type

        pix_key = payload["pix_key"]
        pix_key_type = (payload.get("pix_key_type") or detect_pix_key_type(pix_key)).upper()

        provider = get_payment_provider()
        # PF: create_seller_subaccount e no-op. PJ: cria walletId no Asaas.
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
            psp_subaccount_id=subaccount.provider_subaccount_id or "",
            psp_api_key=subaccount.api_key or "",
            pix_key=pix_key,
            pix_key_type=pix_key_type,
            origin_cep=payload["origin_cep"],
            origin_street=payload["origin_street"],
            origin_number=payload["origin_number"],
            origin_complement=payload.get("origin_complement", ""),
            origin_district=payload["origin_district"],
            origin_city=payload["origin_city"],
            origin_state=payload["origin_state"],
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
        if not getattr(settings, "ENABLE_STORE_PLAN_SALES", False):
            return Response(
                {
                    "detail": (
                        "Planos pagos estão temporariamente indisponíveis até a "
                        "ativação automática por webhook estar validada."
                    )
                },
                status=status.HTTP_503_SERVICE_UNAVAILABLE,
            )
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


class StoreFollowToggleView(APIView):
    """POST /api/loja/<slug>/seguir/ — segue ou deixa de seguir a loja."""

    permission_classes = [IsAuthenticated]
    throttle_scope = "cart"

    def post(self, request, slug):
        store = get_object_or_404(Store, slug=slug, status=Store.Status.ACTIVE)
        if getattr(request.user, "store", None) == store:
            return Response(
                {"detail": "Você não pode seguir a própria loja."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        follow, created = StoreFollow.objects.get_or_create(store=store, user=request.user)
        if not created:
            follow.delete()
            following = False
        else:
            following = True
        return Response(
            {
                "following": following,
                "follower_count": store.followers.count(),
            }
        )
