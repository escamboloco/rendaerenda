<<<<<<< HEAD
import logging
from datetime import timedelta
from uuid import UUID

from django.contrib import messages
from django.contrib.auth import authenticate, login, logout
from django.core.paginator import Paginator
from django.db.models import Count, Q, Sum
from django.http import FileResponse, Http404, HttpResponseNotAllowed
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.utils.http import url_has_allowed_host_and_scheme
from django.views.decorators.debug import sensitive_post_parameters
from django.views.decorators.http import require_POST
from django_ratelimit.decorators import ratelimit

from apps.accounts.models import SellerKYC, User
from apps.catalog.models import Product
from apps.moderation.models import ModerationQueueItem, Report
from apps.payments.models import Invoice, Order, Payment
from apps.shipping.models import Shipment
from apps.stores.models import Store
from apps.wallet.models import WalletEntry, WithdrawalRequest

from .decorators import staff_required, superuser_required
from .forms import StaffLoginForm

logger = logging.getLogger(__name__)
LOGIN_ERROR = "E-mail ou senha inválidos."


def _safe_next(request) -> str:
    target = request.POST.get("next") or request.GET.get("next") or ""
    if url_has_allowed_host_and_scheme(
        target,
        allowed_hosts={request.get_host()},
        require_https=request.is_secure(),
    ):
        return target
    return reverse("backoffice:dashboard")
=======
"""
Painel de gestão do negócio (/gestao/).

Existe porque o admin do Django é ótimo para editar registro solto e
péssimo para *operar*: aprovar identidade olhando três fotos lado a lado,
ver quanto está retido em custódia hoje, decidir uma disputa. Cada tela
aqui responde a uma pergunta que a operação faz todo dia.

Acesso: `is_staff`. Nunca exposto no sitemap e sempre `noindex`.
"""
from __future__ import annotations

from datetime import timedelta
from decimal import Decimal

import logging

from django.conf import settings
from django.contrib.auth import authenticate, login, logout
from django.utils.http import url_has_allowed_host_and_scheme
from django_ratelimit.decorators import ratelimit
from django.contrib import messages
from django.contrib.auth.decorators import user_passes_test
from django.db.models import Avg, Count, Q, Sum
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.utils.dateparse import parse_date
from django.views.decorators.http import require_POST

from apps.accounts.models import SellerKYC, User
from apps.catalog.models import Product
from apps.moderation.models import ModerationQueueItem
from apps.payments.models import Order
from apps.stores.models import Store
from apps.wallet.models import WalletEntry, WithdrawalRequest

ZERO = Decimal("0.00")
logger = logging.getLogger(__name__)

# ------------------------------------------------------------------- acesso
>>>>>>> 4df39f633ec1e7b18ef9954ec7be5eb99492cfc4


@ratelimit(key="ip", rate="5/5m", method="POST", block=False)
@ratelimit(key="post:email", rate="5/5m", method="POST", block=False)
<<<<<<< HEAD
@sensitive_post_parameters("password")
def staff_login(request):
    if request.user.is_authenticated and request.user.is_staff:
        return redirect("backoffice:dashboard")

    form = StaffLoginForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        limited = bool(getattr(request, "limited", False))
        email = form.cleaned_data["email"].strip().lower()
        candidate = User.objects.filter(email__iexact=email).only(
            "username", "is_staff", "is_active"
        ).first()
        username = candidate.get_username() if candidate else email
        user = authenticate(
            request,
            username=username,
            password=form.cleaned_data["password"],
        )
        if not limited and user and user.is_active and user.is_staff:
            login(request, user)
            request.session.set_expiry(60 * 60 * 8)
            return redirect(_safe_next(request))
        form.add_error(None, LOGIN_ERROR)
    elif request.method == "POST":
        # Não diferencia formato, conta inexistente ou senha incorreta.
        form.add_error(None, LOGIN_ERROR)

    response = render(
        request,
        "backoffice/login.html",
        {"form": form, "next": _safe_next(request)},
    )
    response["Cache-Control"] = "no-store, private"
    # same-origin: envia Referer no POST do formulário (exigido pelo CSRF
    # em HTTPS). no-referrer quebrava /gestao/entrar/ com 403.
    response["Referrer-Policy"] = "same-origin"
    return response
=======
def staff_login(request):
    """
    Porta de entrada da equipe.

    Separada do login do site e do /admin/ de propósito: é a única tela
    que dá acesso a documento de identidade de terceiro e ao dinheiro em
    custódia, então merece limite de tentativa próprio.

    Regras:
    - 5 tentativas por IP e 5 por e-mail a cada 5 min (freia força bruta
      distribuída, que só limitar por IP não pega);
    - mensagem de erro idêntica para e-mail inexistente, senha errada e
      conta sem permissão — não confirma para o atacante o que existe;
    - `next` só é seguido se apontar para o próprio site.
    """
    if request.user.is_authenticated and request.user.is_staff:
        return redirect("backoffice:dashboard")

    destino = request.GET.get("next") or request.POST.get("next") or ""
    if destino and not url_has_allowed_host_and_scheme(
        destino, allowed_hosts={request.get_host()}, require_https=request.is_secure()
    ):
        destino = ""

    erro = ""
    if request.method == "POST":
        if getattr(request, "limited", False):
            erro = "Muitas tentativas. Aguarde alguns minutos e tente de novo."
            logger.warning("Backoffice: limite de tentativas atingido (IP %s).", _client_ip(request))
        else:
            email = (request.POST.get("email") or "").strip().lower()
            senha = request.POST.get("password") or ""
            usuario = authenticate(request, username=email, password=senha)

            if usuario is not None and usuario.is_staff and usuario.is_active:
                login(request, usuario)
                logger.info("Backoffice: entrada de %s", email)
                return redirect(destino or "backoffice:dashboard")

            # Mesma resposta para todos os casos de falha.
            erro = "E-mail ou senha inválidos, ou a conta não tem acesso ao painel."
            logger.warning(
                "Backoffice: tentativa recusada para %s (IP %s).",
                email or "sem e-mail",
                _client_ip(request),
            )

    return render(request, "backoffice/login.html", {"erro": erro, "next": destino})
>>>>>>> 4df39f633ec1e7b18ef9954ec7be5eb99492cfc4


@require_POST
def staff_logout(request):
    logout(request)
    return redirect("backoffice:login")


<<<<<<< HEAD
@staff_required
def dashboard(request):
    now = timezone.now()
    paid_statuses = [
        Order.Status.PAID,
        Order.Status.SHIPPED,
        Order.Status.DELIVERED,
    ]
    revenue = (
        Order.objects.filter(status__in=paid_statuses)
        .aggregate(total=Sum("items_total"))["total"]
        or 0
    )
    context = {
        "active_tab": "dashboard",
        "metrics": {
            "stores": Store.objects.count(),
            "active_stores": Store.objects.filter(status=Store.Status.ACTIVE).count(),
            "users": User.objects.count(),
            "orders": Order.objects.count(),
            "gross_sales": revenue,
        },
        "alerts": {
            "moderation": ModerationQueueItem.objects.filter(
=======
def _client_ip(request) -> str:
    """IP real atrás do proxy do Render (X-Forwarded-For)."""
    encaminhado = request.META.get("HTTP_X_FORWARDED_FOR", "")
    return encaminhado.split(",")[0].strip() if encaminhado else request.META.get("REMOTE_ADDR", "?")



def staff_required(view):
    """Exige equipe e manda para a porta do painel, não para o /admin/."""
    return user_passes_test(
        lambda u: u.is_authenticated and u.is_staff and u.is_active,
        login_url="backoffice:login",
    )(view)


def _money(value) -> Decimal:
    return value if value is not None else ZERO


def _period_bounds(days: int):
    now = timezone.now()
    return now - timedelta(days=days), now


@staff_required
def dashboard(request):
    """
    Visão do dia: dinheiro, filas e o que está travando venda.

    A ordem das seções segue a urgência real — primeiro o que tem gente
    esperando resposta (KYC, moderação, disputa), depois o financeiro.
    """
    inicio, agora = _period_bounds(30)

    pagos = Order.objects.filter(
        status__in=[Order.Status.PAID, Order.Status.SHIPPED, Order.Status.DELIVERED]
    )
    pagos_30d = pagos.filter(paid_at__gte=inicio)

    gmv_30d = _money(pagos_30d.aggregate(t=Sum("items_total"))["t"])
    gmv_total = _money(pagos.aggregate(t=Sum("items_total"))["t"])

    # Comissão = o que sobra do preço depois do líquido da vendedora.
    # Calculada em Python porque payout_total é property do pedido.
    comissao_30d = sum(
        (o.platform_amount for o in pagos_30d.prefetch_related("items")), ZERO
    )

    # Custódia: crédito ainda não sacável. É passivo — dinheiro de terceiro
    # parado na conta, e o número que mais importa para não gastar sem querer.
    retido = _money(
        WalletEntry.objects.filter(
            kind=WalletEntry.Kind.SALE_CREDIT, available_at__gt=agora
        ).aggregate(t=Sum("amount"))["t"]
    )
    liberado_nao_sacado = _money(
        WalletEntry.objects.filter(available_at__lte=agora).aggregate(t=Sum("amount"))["t"]
    )

    filas = {
        "kyc": SellerKYC.objects.filter(status=SellerKYC.Status.PENDING).count(),
        "anuncios": ModerationQueueItem.objects.filter(
            decision__in=[
                ModerationQueueItem.Decision.PENDING,
                ModerationQueueItem.Decision.AUTO_FLAGGED,
            ]
        ).count(),
        "disputas": Order.objects.filter(status=Order.Status.DISPUTED).count(),
        "saques_falhos": WithdrawalRequest.objects.filter(
            status=WithdrawalRequest.Status.FAILED
        ).count(),
        "sem_pix": Store.objects.filter(status=Store.Status.ACTIVE)
        .filter(Q(pix_key="") | Q(pix_key__isnull=True))
        .count(),
    }

    return render(
        request,
        "backoffice/dashboard.html",
        {
            "gmv_30d": gmv_30d,
            "gmv_total": gmv_total,
            "comissao_30d": comissao_30d,
            "retido": retido,
            "liberado_nao_sacado": liberado_nao_sacado,
            "pedidos_30d": pagos_30d.count(),
            "ticket_medio": (gmv_30d / pagos_30d.count()) if pagos_30d.count() else ZERO,
            "filas": filas,
            "aguardando_pagamento": Order.objects.filter(
                status=Order.Status.AWAITING_PAYMENT
            ).count(),
            "lojas_ativas": Store.objects.filter(status=Store.Status.ACTIVE).count(),
            "anuncios_no_ar": Product.objects.filter(
                status=Product.Status.PUBLISHED, stock__gt=0
            ).count(),
            "ultimos_pedidos": (
                Order.objects.select_related("store")
                .exclude(status=Order.Status.AWAITING_PAYMENT)
                .order_by("-created_at")[:12]
            ),
        },
    )


# --------------------------------------------------------------- identidade


@staff_required
def kyc_queue(request):
    """Fila de identidade. A decisão é tomada olhando as três fotos juntas."""
    status = request.GET.get("status", SellerKYC.Status.PENDING)
    itens = (
        SellerKYC.objects.select_related("user", "reviewed_by")
        .filter(status=status)
        .order_by("submitted_at")
    )
    return render(
        request,
        "backoffice/kyc_queue.html",
        {
            "itens": itens,
            "status_atual": status,
            "status_choices": SellerKYC.Status.choices,
            "pendentes": SellerKYC.objects.filter(status=SellerKYC.Status.PENDING).count(),
        },
    )


@staff_required
@require_POST
def kyc_decide(request, kyc_id):
    """
    Aprova ou reprova a identidade.

    Aprovar exige a data de nascimento LIDA NO DOCUMENTO: é ela que vira a
    idade oficial da conta. Sem esse dado a conta não pode ser liberada —
    idade é exigência legal, não campo opcional (Lei 15.211/2025).
    """
    kyc = get_object_or_404(SellerKYC.objects.select_related("user"), pk=kyc_id)
    acao = request.POST.get("acao")

    if acao == "aprovar":
        # O POST entrega texto; approve() calcula idade e precisa de date.
        # A conversao acontece aqui, na borda HTTP, e nao no model.
        nascimento = parse_date((request.POST.get("document_birth_date") or "").strip())
        if not nascimento:
            messages.error(
                request,
                "Informe uma data de nascimento válida (a que está no documento) antes de aprovar.",
            )
            return redirect("backoffice:kyc_queue")
        kyc.approve(reviewer=request.user, document_birth_date=nascimento)
        kyc.refresh_from_db()
        if kyc.status != SellerKYC.Status.APPROVED:
            messages.error(request, "Documento indica menor de idade — conta bloqueada.")
        else:
            loja = activate_store_for(kyc.user)
            messages.success(
                request,
                f"{kyc.user.email} aprovada."
                + (f" Loja “{loja.display_name}” já está no ar." if loja else
                   " Ela ainda precisa abrir a loja."),
            )
    elif acao == "reprovar":
        motivo = (request.POST.get("motivo") or "").strip()
        kyc.reject(reviewer=request.user, reason=motivo or "Documento ilegível ou código não confere.")
        messages.info(request, f"{kyc.user.email} reprovada — ela pode reenviar.")
    return redirect("backoffice:kyc_queue")


def activate_store_for(user: User):
    """
    Libera a loja assim que a identidade é aprovada.

    Sem isso a vendedora ficava aprovada mas invisível, esperando alguém
    mexer no admin — é o passo que faz "aprovou, está vendendo".
    """
    user.refresh_from_db()
    # Segunda trava: mesmo que alguém chame isto direto, conta banida ou
    # sem idade verificada nunca coloca loja no ar.
    if user.is_banned or not user.is_age_verified:
        return None

    loja = getattr(user, "store", None)
    if loja and loja.status == Store.Status.PENDING_MODERATION:
        loja.status = Store.Status.ACTIVE
        loja.save(update_fields=["status"])
    return loja


# --------------------------------------------------------------- financeiro


@staff_required
def finance(request):
    """Onde o dinheiro está: custódia, repasses e saques que falharam."""
    agora = timezone.now()

    retidos = (
        WalletEntry.objects.filter(
            kind=WalletEntry.Kind.SALE_CREDIT, available_at__gt=agora
        )
        .select_related("store", "order")
        .order_by("available_at")[:50]
    )
    saques = (
        WithdrawalRequest.objects.select_related("store")
        .order_by("-requested_at")[:40]
    )
    por_loja = (
        Store.objects.filter(wallet_entries__isnull=False)
        .annotate(
            saldo=Sum("wallet_entries__amount"),
            retido=Sum(
                "wallet_entries__amount",
                filter=Q(
                    wallet_entries__available_at__gt=agora,
                    wallet_entries__kind=WalletEntry.Kind.SALE_CREDIT,
                ),
            ),
        )
        .order_by("-saldo")[:25]
    )
    return render(
        request,
        "backoffice/finance.html",
        {
            "retidos": retidos,
            "saques": saques,
            "por_loja": por_loja,
            "total_retido": _money(
                WalletEntry.objects.filter(
                    kind=WalletEntry.Kind.SALE_CREDIT, available_at__gt=agora
                ).aggregate(t=Sum("amount"))["t"]
            ),
            "saques_falhos": WithdrawalRequest.objects.filter(
                status=WithdrawalRequest.Status.FAILED
            ).count(),
        },
    )


# ------------------------------------------------------------------ pedidos


@staff_required
def orders(request):
    """Pedidos com filtro por situação — a tela para responder 'cadê o meu?'."""
    status = request.GET.get("status", "")
    qs = Order.objects.select_related("store", "payment", "shipment").order_by("-created_at")
    if status:
        qs = qs.filter(status=status)
    return render(
        request,
        "backoffice/orders.html",
        {
            "pedidos": qs[:80],
            "status_atual": status,
            "status_choices": Order.Status.choices,
            "contagem": {
                s: Order.objects.filter(status=s).count() for s, _ in Order.Status.choices
            },
        },
    )


@staff_required
def stores_list(request):
    """Lojas com o que decide suspensão: reputação, vendas e chave Pix."""
    lojas = (
        Store.objects.select_related("owner")
        .annotate(
            anuncios=Count(
                "products",
                filter=Q(products__status=Product.Status.PUBLISHED, products__stock__gt=0),
            )
        )
        .order_by("-created_at")[:60]
    )
    return render(
        request,
        "backoffice/stores.html",
        {
            "lojas": lojas,
            "nota_media": Store.objects.filter(review_count__gt=0).aggregate(
                v=Avg("avg_rating")
            )["v"],
            "dispute_window_days": settings.DISPUTE_WINDOW_DAYS,
        },
    )


# ------------------------------------------------------------- moderação


@staff_required
def moderation_queue(request):
    """
    Fila de moderação com o conteúdo à vista.

    O admin do Django mostra `object_id` e content type — inútil para
    decidir. Aqui o item vem resolvido: título, descrição, fotos e o que
    o filtro automático sinalizou.
    """
    decisao = request.GET.get("decisao", "")
    itens = ModerationQueueItem.objects.select_related("content_type").order_by("created_at")
    if decisao:
        itens = itens.filter(decision=decisao)
    else:
        itens = itens.filter(
            decision__in=[
                ModerationQueueItem.Decision.PENDING,
                ModerationQueueItem.Decision.AUTO_FLAGGED,
            ]
        )

    # Resolve o alvo de cada item em lote (o genérico não traz o objeto).
    itens = list(itens[:60])
    ids_produto = [i.object_id for i in itens if i.target_type == ModerationQueueItem.TargetType.PRODUCT]
    ids_loja = [i.object_id for i in itens if i.target_type == ModerationQueueItem.TargetType.STORE]
    produtos = {
        str(p.id): p
        for p in Product.objects.filter(id__in=ids_produto)
        .select_related("store", "category")
        .prefetch_related("images")
    }
    lojas = {str(s.id): s for s in Store.objects.filter(id__in=ids_loja)}
    for item in itens:
        item.alvo = produtos.get(item.object_id) or lojas.get(item.object_id)

    return render(
        request,
        "backoffice/moderation.html",
        {
            "itens": itens,
            "decisao_atual": decisao,
            "decisoes": ModerationQueueItem.Decision.choices,
            "pendentes": ModerationQueueItem.objects.filter(
>>>>>>> 4df39f633ec1e7b18ef9954ec7be5eb99492cfc4
                decision__in=[
                    ModerationQueueItem.Decision.PENDING,
                    ModerationQueueItem.Decision.AUTO_FLAGGED,
                ]
            ).count(),
<<<<<<< HEAD
            "reports": Report.objects.filter(resolved_at__isnull=True).count(),
            "urgent_reports": Report.objects.filter(
                resolved_at__isnull=True, requires_immediate_action=True
            ).count(),
            "disputes": Order.objects.filter(status=Order.Status.DISPUTED).count(),
            "kyc": SellerKYC.objects.filter(status=SellerKYC.Status.PENDING).count(),
            "unpaid_expired": Order.objects.filter(
                status=Order.Status.AWAITING_PAYMENT, expires_at__lt=now
            ).count(),
            "labels": Shipment.objects.filter(
                order__status=Order.Status.PAID, label_url=""
            ).count(),
        },
        "recent_orders": Order.objects.select_related("store", "buyer")[:8],
        "recent_payments": Payment.objects.select_related("order").order_by(
            "-order__created_at"
        )[:8],
        "period": now - timedelta(days=30),
    }
    return render(request, "backoffice/dashboard.html", context)


@staff_required
def stores(request):
    query = request.GET.get("q", "").strip()
    status = request.GET.get("status", "").strip()
    ordering = request.GET.get("ordem", "rating")
    queryset = Store.objects.select_related("owner").annotate(
        product_count=Count("products")
    )
    if query:
        queryset = queryset.filter(
            Q(display_name__icontains=query)
            | Q(slug__icontains=query)
            | Q(owner__email__icontains=query)
        )
    if status in Store.Status.values:
        queryset = queryset.filter(status=status)
    order_map = {
        "rating": ("-bayesian_rating", "-review_count", "-sales_count"),
        "sales": ("-sales_count", "-bayesian_rating"),
        "newest": ("-created_at",),
        "name": ("display_name",),
    }
    queryset = queryset.order_by(*order_map.get(ordering, order_map["rating"]))
    return render(
        request,
        "backoffice/stores.html",
        {
            "active_tab": "stores",
            "stores": Paginator(queryset, 50).get_page(request.GET.get("page")),
            "query": query,
            "status_filter": status,
            "ordering": ordering,
            "store_statuses": Store.Status.choices,
=======
>>>>>>> 4df39f633ec1e7b18ef9954ec7be5eb99492cfc4
        },
    )


@staff_required
<<<<<<< HEAD
def orders(request):
    query = request.GET.get("q", "").strip()
    status = request.GET.get("status", "").strip()
    queryset = Order.objects.select_related("store", "buyer", "payment").prefetch_related(
        "items"
    )
    if query:
        filters = (
            Q(guest_email__icontains=query)
            | Q(store__display_name__icontains=query)
            | Q(buyer__email__icontains=query)
        )
        try:
            filters |= Q(id=UUID(query))
        except ValueError:
            pass
        queryset = queryset.filter(filters)
    if status in Order.Status.values:
        queryset = queryset.filter(status=status)
    return render(
        request,
        "backoffice/orders.html",
        {
            "active_tab": "orders",
            "orders": Paginator(queryset, 50).get_page(request.GET.get("page")),
            "query": query,
            "status_filter": status,
            "order_statuses": Order.Status.choices,
        },
    )


@superuser_required
def finance(request):
    now = timezone.now()
    ledger = WalletEntry.objects.select_related("store", "order").order_by("-created_at")
    withdrawals = WithdrawalRequest.objects.select_related("store").order_by("-requested_at")
    invoices = Invoice.objects.select_related("order").order_by("-created_at")
    return render(
        request,
        "backoffice/finance.html",
        {
            "active_tab": "finance",
            "available": ledger.filter(available_at__lte=now).aggregate(total=Sum("amount"))["total"] or 0,
            "held": ledger.filter(
                available_at__gt=now, kind=WalletEntry.Kind.SALE_CREDIT
            ).aggregate(total=Sum("amount"))["total"]
            or 0,
            "failed_withdrawals": withdrawals.filter(
                status=WithdrawalRequest.Status.FAILED
            ).count(),
            "failed_invoices": invoices.filter(status=Invoice.Status.FAILED).count(),
            "withdrawals": withdrawals[:50],
            "invoices": invoices[:50],
        },
    )


@staff_required
def moderation(request):
    pending = ModerationQueueItem.objects.filter(
        decision__in=[
            ModerationQueueItem.Decision.PENDING,
            ModerationQueueItem.Decision.AUTO_FLAGGED,
        ]
    ).select_related("content_type", "reviewed_by")
    reports = Report.objects.filter(resolved_at__isnull=True).select_related(
        "content_type", "reporter"
    )
    return render(
        request,
        "backoffice/moderation.html",
        {
            "active_tab": "moderation",
            "queue": pending[:100],
            "reports": reports[:100],
        },
    )


@require_POST
@staff_required
def moderate(request, item_id, decision):
    item = get_object_or_404(ModerationQueueItem, id=item_id)
    if item.decision not in {
        item.Decision.PENDING,
        item.Decision.AUTO_FLAGGED,
    }:
        messages.warning(request, "Este item já foi revisado.")
        return redirect("backoffice:moderation")
    if decision == "approve":
        try:
            item.approve(request.user)
        except ValueError as exc:
            messages.error(request, str(exc))
            return redirect("backoffice:moderation")
        messages.success(request, "Conteúdo aprovado e publicado.")
    elif decision == "reject":
        item.reject(request.user)
        messages.success(request, "Conteúdo recusado e retirado da publicação.")
    else:
        return HttpResponseNotAllowed(["POST"])
    return redirect("backoffice:moderation")


@require_POST
@staff_required
def resolve_report(request, report_id):
    report = get_object_or_404(Report, id=report_id, resolved_at__isnull=True)
    action = (request.POST.get("action") or "").strip()
    notes = (request.POST.get("notes") or "").strip()[:500]
    if report.requires_immediate_action and action != "remove":
        messages.error(
            request,
            "Denúncia urgente só pode ser encerrada após remover/suspender o alvo.",
        )
        return redirect("backoffice:moderation")

    if action == "remove":
        target = report.target
        if isinstance(target, Product):
            target.status = Product.Status.REJECTED
            target.save(update_fields=["status"])
        elif isinstance(target, Store):
            target.status = Store.Status.SUSPENDED
            target.save(update_fields=["status"])
        else:
            messages.error(request, "O alvo não existe mais; encaminhe para revisão jurídica.")
            return redirect("backoffice:moderation")

    report.resolved_at = timezone.now()
    report.resolved_by = request.user
    report.resolution_notes = notes or (
        "Alvo removido/suspenso." if action == "remove" else "Revisão concluída."
    )
    report.save(update_fields=["resolved_at", "resolved_by", "resolution_notes"])
    messages.success(request, "Denúncia marcada como tratada.")
    return redirect("backoffice:moderation")
=======
@require_POST
def moderation_decide(request, item_id):
    """Aprova (vai ao ar) ou rejeita (fica fora) o conteúdo da fila."""
    item = get_object_or_404(ModerationQueueItem, pk=item_id)
    acao = request.POST.get("acao")

    if item.target_type == ModerationQueueItem.TargetType.PRODUCT:
        produto = Product.objects.filter(id=item.object_id).first()
        if produto:
            produto.status = (
                Product.Status.PUBLISHED if acao == "aprovar" else Product.Status.REJECTED
            )
            produto.save(update_fields=["status"])
    elif item.target_type == ModerationQueueItem.TargetType.STORE:
        loja = Store.objects.filter(id=item.object_id).first()
        if loja:
            loja.status = Store.Status.ACTIVE if acao == "aprovar" else Store.Status.SUSPENDED
            loja.save(update_fields=["status"])

    item.decision = (
        ModerationQueueItem.Decision.APPROVED
        if acao == "aprovar"
        else ModerationQueueItem.Decision.REJECTED
    )
    item.reviewed_by = request.user
    item.reviewed_at = timezone.now()
    item.save(update_fields=["decision", "reviewed_by", "reviewed_at"])

    messages.success(
        request, "Conteúdo publicado." if acao == "aprovar" else "Conteúdo recusado."
    )
    return redirect("backoffice:moderation")


# --------------------------------------------------------------- disputas
>>>>>>> 4df39f633ec1e7b18ef9954ec7be5eb99492cfc4


@staff_required
def disputes(request):
<<<<<<< HEAD
    orders = (
        Order.objects.filter(status=Order.Status.DISPUTED)
        .select_related("store", "buyer", "payment", "shipment")
        .prefetch_related("items__product", "messages")
    )
    return render(
        request,
        "backoffice/disputes.html",
        {"active_tab": "disputes", "orders": orders[:100]},
    )


@require_POST
@superuser_required
def resolve_dispute(request, order_id, decision):
    order = get_object_or_404(
        Order.objects.select_related("payment", "store"),
        id=order_id,
        status=Order.Status.DISPUTED,
    )
    confirmation = request.POST.get("confirmation", "")
    if confirmation != order.short_id:
        messages.error(request, f"Digite {order.short_id} para confirmar a decisão.")
        return redirect("backoffice:disputes")

    try:
        if decision == "refund":
            from apps.payments.checkout import refund_order

            if not refund_order(order, reason="disputa_procedente"):
                raise RuntimeError("O provedor não confirmou o estorno.")
            messages.success(request, f"Pedido {order.short_id} estornado.")
        elif decision == "release":
            from apps.wallet.services import release_and_payout

            if not release_and_payout(order):
                raise RuntimeError("O repasse não foi confirmado.")
            order.status = Order.Status.DELIVERED
            order.save(update_fields=["status"])
            messages.success(request, f"Pedido {order.short_id} liberado à vendedora.")
        else:
            return HttpResponseNotAllowed(["POST"])
    except Exception as exc:  # mensagem pública não expõe resposta do PSP
        logger.exception("Falha ao resolver disputa %s no backoffice", order.id)
        messages.error(
            request,
            "Operação não concluída. Consulte os logs e tente novamente; "
            "nenhum detalhe do provedor foi exibido.",
        )
    return redirect("backoffice:disputes")


@staff_required
def accounts(request):
    query = request.GET.get("q", "").strip()
    users = User.objects.select_related("store").order_by("-date_joined")
    if query:
        users = users.filter(
            Q(email__icontains=query)
            | Q(cpf__icontains="".join(c for c in query if c.isdigit()))
            | Q(first_name__icontains=query)
            | Q(last_name__icontains=query)
        )
    page = Paginator(users, 50).get_page(request.GET.get("page"))
    return render(
        request,
        "backoffice/accounts.html",
        {
            "active_tab": "accounts",
            "users": page,
            "query": query,
            "status_filter": "",
            "ordering": "",
        },
    )


@staff_required
def kyc_queue(request):
    """Fila de verificação: RG frente/verso + selfie para liberar loja."""
    status_filter = request.GET.get("status", SellerKYC.Status.PENDING).strip()
    query = request.GET.get("q", "").strip()
    queryset = SellerKYC.objects.select_related("user", "user__store", "reviewed_by").order_by(
        "-submitted_at", "-created_at"
    )
    if status_filter in SellerKYC.Status.values:
        queryset = queryset.filter(status=status_filter)
    if query:
        queryset = queryset.filter(
            Q(user__email__icontains=query)
            | Q(user__cpf__icontains="".join(c for c in query if c.isdigit()))
            | Q(user__store__display_name__icontains=query)
            | Q(user__store__slug__icontains=query)
            | Q(verification_code__icontains=query)
        )
    return render(
        request,
        "backoffice/kyc_queue.html",
        {
            "active_tab": "kyc",
            "items": Paginator(queryset, 40).get_page(request.GET.get("page")),
            "query": query,
            "status_filter": status_filter,
            "kyc_statuses": SellerKYC.Status.choices,
            "pending_count": SellerKYC.objects.filter(status=SellerKYC.Status.PENDING).count(),
        },
    )


@staff_required
def seller_detail(request, store_id):
    """Dossiê da vendedora: loja, métricas e fotos de segurança do KYC."""
    store = get_object_or_404(
        Store.objects.select_related("owner", "owner__seller_kyc", "plan"),
        id=store_id,
    )
    owner = store.owner
    kyc = getattr(owner, "seller_kyc", None)
    paid_statuses = [
        Order.Status.PAID,
        Order.Status.SHIPPED,
        Order.Status.DELIVERED,
    ]
    orders = (
        Order.objects.filter(store=store)
        .select_related("buyer", "payment")
        .order_by("-created_at")[:20]
    )
    products = (
        Product.objects.filter(store=store)
        .order_by("-created_at")[:12]
    )
    gross = (
        Order.objects.filter(store=store, status__in=paid_statuses).aggregate(
            total=Sum("items_total")
        )["total"]
        or 0
    )
    from apps.wallet.models import WalletEntry

    context = {
        "active_tab": "sellers",
        "store": store,
        "owner": owner,
        "kyc": kyc,
        "orders": orders,
        "products": products,
        "metrics": {
            "products": store.products.count(),
            "published": store.products.filter(status=Product.Status.PUBLISHED).count(),
            "orders": Order.objects.filter(store=store).count(),
            "gross_sales": gross,
            "available_balance": WalletEntry.objects.available_balance(store),
            "pending_balance": WalletEntry.objects.pending_balance(store),
        },
        "origin_complete": bool(
            store.origin_cep and store.origin_street and store.origin_city and store.origin_state
        ),
    }
    return render(request, "backoffice/seller_detail.html", context)


@require_POST
@staff_required
def kyc_decide(request, kyc_id, decision):
    kyc = get_object_or_404(SellerKYC.objects.select_related("user", "user__store"), id=kyc_id)
    store = getattr(kyc.user, "store", None)
    redirect_to = (
        reverse("backoffice:seller_detail", args=[store.id])
        if store
        else reverse("backoffice:kyc_queue")
    )

    if kyc.status != SellerKYC.Status.PENDING:
        if decision == "approve" and kyc.status == SellerKYC.Status.APPROVED:
            messages.info(request, "Este KYC já está aprovado.")
        else:
            messages.warning(
                request,
                "Só é possível decidir KYCs em análise. Peça reenvio se estiver recusado.",
            )
        return redirect(redirect_to)

    if decision == "approve":
        birth_raw = (request.POST.get("document_birth_date") or "").strip()
        if not birth_raw:
            messages.error(request, "Informe a data de nascimento lida no documento.")
            return redirect(redirect_to)
        try:
            from datetime import date as date_cls

            year, month, day = (int(part) for part in birth_raw.split("-"))
            birth = date_cls(year, month, day)
        except (TypeError, ValueError):
            messages.error(request, "Data de nascimento inválida.")
            return redirect(redirect_to)
        try:
            kyc.approve(reviewer=request.user, document_birth_date=birth, activate_store=True)
        except ValueError as exc:
            messages.error(request, str(exc))
            return redirect(redirect_to)
        messages.success(
            request,
            "KYC aprovado. Idade verificada e loja liberada (quando existir e não estiver suspensa).",
        )
    elif decision == "reject":
        reason = (request.POST.get("reason") or "").strip()
        if len(reason) < 10:
            messages.error(request, "Descreva o motivo da recusa (mín. 10 caracteres).")
            return redirect(redirect_to)
        kyc.reject(reviewer=request.user, reason=reason)
        messages.success(request, "KYC recusado. A vendedora pode reenviar as fotos.")
    else:
        return HttpResponseNotAllowed(["POST"])
    return redirect(redirect_to)


@staff_required
def kyc_file(request, kyc_id, field):
    """Serve documento KYC somente à equipe, sem URL pública permanente."""
    allowed_fields = {"document_front", "document_back", "selfie_with_document"}
    if field not in allowed_fields:
        raise Http404
    kyc = get_object_or_404(SellerKYC, id=kyc_id)
    stored_file = getattr(kyc, field, None)
    if not stored_file or not stored_file.name:
        raise Http404
    try:
        response = FileResponse(
            stored_file.open("rb"),
            content_type="image/jpeg",
            as_attachment=False,
            filename=f"kyc-{kyc.id}-{field}.jpg",
        )
    except (FileNotFoundError, OSError):
        raise Http404 from None
    response["Cache-Control"] = "no-store, private"
    response["X-Content-Type-Options"] = "nosniff"
    response["Content-Security-Policy"] = "default-src 'none'; img-src 'self'"
    return response
=======
    """Contestações abertas — cada uma com dinheiro travado dos dois lados."""
    pedidos = (
        Order.objects.filter(status=Order.Status.DISPUTED)
        .select_related("store", "payment", "shipment")
        .prefetch_related("items__product", "messages")
        .order_by("created_at")
    )
    return render(request, "backoffice/disputes.html", {"pedidos": pedidos})


@staff_required
@require_POST
def dispute_decide(request, order_id):
    """
    Fecha a contestação: reembolsa quem comprou ou libera para quem vendeu.

    As duas ações mexem em dinheiro de verdade e são idempotentes nas
    camadas de baixo (refund_order / release_and_payout).
    """
    from apps.payments.checkout import refund_order
    from apps.wallet.services import release_and_payout

    pedido = get_object_or_404(Order, pk=order_id)
    if pedido.status != Order.Status.DISPUTED:
        messages.error(request, "Este pedido não está em contestação.")
        return redirect("backoffice:disputes")

    if request.POST.get("acao") == "reembolsar":
        if refund_order(pedido, reason="disputa procedente"):
            messages.success(request, f"Pedido {pedido.short_id} reembolsado ao comprador.")
        else:
            messages.error(request, "Não havia cobrança para estornar — verifique no Asaas.")
    else:
        pedido.status = Order.Status.DELIVERED
        pedido.save(update_fields=["status"])
        release_and_payout(pedido)
        messages.success(request, f"Pedido {pedido.short_id} liberado para a vendedora.")
    return redirect("backoffice:disputes")


# ----------------------------------------------------------------- pessoas


@staff_required
def people(request):
    """Busca de conta por e-mail ou CPF — a tela do 'me ajuda com meu pedido'."""
    busca = (request.GET.get("q") or "").strip()
    usuarios = User.objects.none()
    if busca:
        usuarios = (
            User.objects.filter(
                Q(email__icontains=busca) | Q(cpf__icontains=busca) | Q(username__icontains=busca)
            )
            .select_related("store")
            .order_by("-date_joined")[:40]
        )
    return render(
        request,
        "backoffice/people.html",
        {
            "usuarios": usuarios,
            "busca": busca,
            "total_contas": User.objects.count(),
            "vendedoras": User.objects.filter(role=User.Role.SELLER).count(),
            "banidas": User.objects.filter(is_banned=True).count(),
        },
    )
>>>>>>> 4df39f633ec1e7b18ef9954ec7be5eb99492cfc4
