"""
E-mails transacionais e emissao de NF do pedido - tudo assincrono
(Celery) para o webhook do PSP responder rapido.

Politica de discricao (docs/BASE_JURIDICA.md secao 4.4 + skill): nem o
assunto nem o corpo dos e-mails citam o nicho ou os titulos dos itens -
so numero do pedido, valores e link para ver os detalhes.
"""
import logging

from celery import shared_task
from django.conf import settings
from django.core.mail import send_mail
from django.template.loader import render_to_string
from django.utils import timezone

logger = logging.getLogger(__name__)


def _site_url(path: str = "") -> str:
    domain = settings.SITE_DOMAIN
    scheme = "http" if settings.DEBUG else "https"
    return f"{scheme}://{domain}{path}"


def _shipping_line(order) -> str:
    addr = order.shipping_address or {}
    parts = [
        addr.get("street", ""),
        addr.get("number", ""),
        addr.get("neighborhood", ""),
        f"{addr.get('city', '')}/{addr.get('state', '')}",
        f"CEP {addr.get('cep', '')}",
    ]
    return ", ".join(p for p in parts if p)


def _safe_send(subject: str, template: str, context: dict, recipient: str) -> bool:
    if not recipient:
        logger.warning("E-mail '%s' sem destinatario — pulando.", subject)
        return False
    try:
        send_mail(
            subject=subject,
            message=render_to_string(template, context),
            from_email=settings.DEFAULT_FROM_EMAIL,
            recipient_list=[recipient],
        )
        return True
    except Exception:
        logger.exception("Falha ao enviar e-mail '%s' para %s", subject, recipient)
        return False


@shared_task
def send_order_confirmation_email(order_id: str):
    from .models import Order

    order = Order.objects.select_related("buyer", "store").prefetch_related("items").get(id=order_id)
    track = (
        f"/pedido/{order.access_token}/"
        if order.access_token
        else "/compras/"
    )
    context = {
        "order": order,
        "site_name": settings.SITE_NAME,
        "order_url": _site_url(track),
        "shipping_line": _shipping_line(order),
    }
    _safe_send(
        subject=f"Pedido confirmado #{str(order.id)[:8]}",
        template="emails/order_confirmation.txt",
        context=context,
        recipient=order.payer_email,
    )


@shared_task
def send_seller_new_sale_email(order_id: str):
    from .models import Order

    order = (
        Order.objects.select_related("store__owner", "shipment")
        .prefetch_related("items__product")
        .get(id=order_id)
    )
    seller_email = getattr(order.store.owner, "email", "") or ""
    shipment = getattr(order, "shipment", None)
    # Se a etiqueta já saiu no mesmo request, o e-mail "Venda + etiqueta"
    # já cobriu os detalhes — evita duplicar.
    if shipment and shipment.label_url:
        logger.info(
            "Pedido %s: e-mail de venda pulado — etiqueta já enviada com os detalhes.",
            order_id,
        )
        return

    item_lines = []
    for item in order.items.all():
        kind = "digital" if not item.product.requires_shipping else "físico"
        item_lines.append(f"{item.quantity}x peça {kind} — R$ {item.unit_price}")

    context = {
        "order": order,
        "site_name": settings.SITE_NAME,
        "shipping_line": _shipping_line(order),
        "item_lines": item_lines,
        "label_url": (shipment.label_url if shipment else "") or "",
        "tracking_code": (shipment.tracking_code if shipment else "") or "",
        "wallet_url": _site_url("/carteira/"),
    }
    _safe_send(
        subject=f"Nova venda #{str(order.id)[:8]}",
        template="emails/seller_new_sale.txt",
        context=context,
        recipient=seller_email,
    )


@shared_task
def send_dispute_opened_email(order_id: str):
    """
    Avisa a vendedora e a moderação que uma contestação foi aberta.

    Sem o título do item no corpo (política de discrição) e sem derrubar
    a resposta da API se o SMTP falhar.
    """
    from django.utils import timezone

    from .models import Order

    order = Order.objects.select_related("store__owner").get(id=order_id)
    context = {
        "order": order,
        "site_name": settings.SITE_NAME,
        "opened_at": timezone.now(),
        "order_url": _site_url(order.track_url),
    }
    subject = f"Contestação aberta — pedido #{order.short_id}"

    seller_email = getattr(order.store.owner, "email", "") or ""
    if seller_email:
        _safe_send(subject, "emails/dispute_opened.txt", {**context, "is_seller": True}, seller_email)

    moderation_email = (getattr(settings, "MODERATION_ALERT_EMAIL", "") or "").strip()
    if moderation_email:
        _safe_send(subject, "emails/dispute_opened.txt", {**context, "is_seller": False}, moderation_email)
    else:
        logger.warning(
            "Contestacao no pedido %s sem MODERATION_ALERT_EMAIL configurado — ninguem foi avisado.",
            order_id,
        )


@shared_task(bind=True, max_retries=3, default_retry_delay=60)
def emit_invoice_for_order(self, order_id: str):
    """NFS-e da COMISSAO da plataforma sobre o pedido + e-mail com o link."""
    from .invoicing import InvoiceProviderError, issue_service_invoice
    from .models import Invoice, Order

    order = Order.objects.select_related("buyer", "payment").get(id=order_id)
    if not settings.NFSE_PROVIDER_API_KEY and not settings.DEBUG:
        logger.info("NFS-e nao configurada — pulando pedido %s", order_id)
        return

    recipient_name = order.payer_name
    recipient_cpf = order.payer_cpf
    recipient_email = order.payer_email
    if not recipient_cpf or not recipient_email:
        logger.warning("Pedido %s sem CPF/e-mail do pagador — NFS-e pulada.", order_id)
        return

    charge_ref = ""
    try:
        charge_ref = order.payment.provider_charge_id
    except Exception:
        charge_ref = str(order.id)

    invoice, _ = Invoice.objects.get_or_create(
        order=order,
        defaults={
            "kind": Invoice.Kind.ORDER_COMMISSION,
            "reference_id": charge_ref,
            "recipient_name": recipient_name,
            "recipient_cpf": recipient_cpf,
            "recipient_email": recipient_email,
            "amount": order.platform_amount,
            "description": "Intermediação de anúncios classificados - taxa de serviço",
        },
    )
    if invoice.status == Invoice.Status.ISSUED:
        return

    try:
        issued = issue_service_invoice(
            reference_id=str(invoice.id),
            recipient_name=invoice.recipient_name,
            recipient_cpf=invoice.recipient_cpf,
            recipient_email=invoice.recipient_email,
            amount=invoice.amount,
            description=invoice.description,
        )
    except InvoiceProviderError as exc:
        invoice.status = Invoice.Status.FAILED
        invoice.save(update_fields=["status"])
        if not settings.NFSE_PROVIDER_API_KEY:
            return
        raise self.retry(exc=exc)

    invoice.provider_invoice_id = issued.provider_invoice_id
    invoice.pdf_url = issued.pdf_url
    invoice.status = Invoice.Status.ISSUED
    invoice.issued_at = timezone.now()
    invoice.save(update_fields=["provider_invoice_id", "pdf_url", "status", "issued_at"])

    _safe_send(
        subject=f"Sua nota fiscal — pedido #{str(order.id)[:8]}",
        template="emails/invoice_issued.txt",
        context={"invoice": invoice, "order": order, "site_name": settings.SITE_NAME},
        recipient=invoice.recipient_email,
    )


@shared_task(bind=True, max_retries=3, default_retry_delay=60)
def emit_invoice_for_subscription(self, user_id: str, amount: str, reference_id: str):
    """NFS-e da assinatura do comprador (100% servico da plataforma)."""
    from django.contrib.auth import get_user_model

    from .invoicing import InvoiceProviderError, issue_service_invoice
    from .models import Invoice

    if not settings.NFSE_PROVIDER_API_KEY and not settings.DEBUG:
        logger.info("NFS-e nao configurada — pulando assinatura %s", user_id)
        return

    user = get_user_model().objects.get(id=user_id)
    invoice = Invoice.objects.create(
        kind=Invoice.Kind.BUYER_SUBSCRIPTION,
        reference_id=reference_id,
        recipient_name=user.get_full_name() or user.username,
        recipient_cpf=user.cpf,
        recipient_email=user.email,
        amount=amount,
        description="Assinatura de acesso a plataforma de classificados",
    )
    try:
        issued = issue_service_invoice(
            reference_id=str(invoice.id),
            recipient_name=invoice.recipient_name,
            recipient_cpf=invoice.recipient_cpf,
            recipient_email=invoice.recipient_email,
            amount=invoice.amount,
            description=invoice.description,
        )
    except InvoiceProviderError as exc:
        invoice.status = Invoice.Status.FAILED
        invoice.save(update_fields=["status"])
        raise self.retry(exc=exc)

    invoice.provider_invoice_id = issued.provider_invoice_id
    invoice.pdf_url = issued.pdf_url
    invoice.status = Invoice.Status.ISSUED
    invoice.issued_at = timezone.now()
    invoice.save(update_fields=["provider_invoice_id", "pdf_url", "status", "issued_at"])

    _safe_send(
        subject="Sua nota fiscal — assinatura",
        template="emails/invoice_issued.txt",
        context={"invoice": invoice, "order": None, "site_name": settings.SITE_NAME},
        recipient=invoice.recipient_email,
    )
