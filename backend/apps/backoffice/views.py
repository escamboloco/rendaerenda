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


@ratelimit(key="ip", rate="5/5m", method="POST", block=False)
@ratelimit(key="post:email", rate="5/5m", method="POST", block=False)
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
    response["Referrer-Policy"] = "no-referrer"
    return response


@require_POST
def staff_logout(request):
    logout(request)
    return redirect("backoffice:login")


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
                decision__in=[
                    ModerationQueueItem.Decision.PENDING,
                    ModerationQueueItem.Decision.AUTO_FLAGGED,
                ]
            ).count(),
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
        },
    )


@staff_required
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


@staff_required
def disputes(request):
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
