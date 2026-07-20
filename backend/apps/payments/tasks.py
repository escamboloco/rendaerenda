"""
E-mails transacionais e emissao de NF do pedido - tudo assincrono
(Celery) para o webhook do PSP responder rapido.

Politica de discricao (docs/BASE_JURIDICA.md secao 4.4 + skill): nem o
assunto nem o corpo dos e-mails citam o nicho ou os titulos dos itens -
so numero do pedido, valores e link para ver os detalhes logado.
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


@shared_task
def send_order_confirmation_email(order_id: str):
    from .models import Order

    order = Order.objects.select_related("buyer", "store").prefetch_related("items").get(id=order_id)
    context = {
        "order": order,
        "site_name": settings.SITE_NAME,
        "order_url": _site_url("/pedidos-personalizados/"),
    }
    send_mail(
        subject=f"Pedido confirmado #{str(order.id)[:8]}",
        message=render_to_string("emails/order_confirmation.txt", context),
        from_email=settings.DEFAULT_FROM_EMAIL,
        recipient_list=[order.buyer.email],
    )


@shared_task(bind=True, max_retries=3, default_retry_delay=60)
def emit_invoice_for_order(self, order_id: str):
    """NFS-e da COMISSAO da plataforma sobre o pedido + e-mail com o link."""
    from .invoicing import InvoiceProviderError, issue_service_invoice
    from .models import Invoice, Order

    order = Order.objects.select_related("buyer").get(id=order_id)
    invoice, _ = Invoice.objects.get_or_create(
        order=order,
        defaults={
            "kind": Invoice.Kind.ORDER_COMMISSION,
            "reference_id": order.payment.provider_charge_id,
            # Identidade CIVIL do tomador - obrigacao fiscal, nunca o apelido.
            "recipient_name": order.buyer.get_full_name() or order.buyer.username,
            "recipient_cpf": order.buyer.cpf,
            "recipient_email": order.buyer.email,
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
        raise self.retry(exc=exc)

    invoice.provider_invoice_id = issued.provider_invoice_id
    invoice.pdf_url = issued.pdf_url
    invoice.status = Invoice.Status.ISSUED
    invoice.issued_at = timezone.now()
    invoice.save(update_fields=["provider_invoice_id", "pdf_url", "status", "issued_at"])

    send_mail(
        subject=f"Sua nota fiscal — pedido #{str(order.id)[:8]}",
        message=render_to_string(
            "emails/invoice_issued.txt",
            {"invoice": invoice, "order": order, "site_name": settings.SITE_NAME},
        ),
        from_email=settings.DEFAULT_FROM_EMAIL,
        recipient_list=[invoice.recipient_email],
    )


@shared_task(bind=True, max_retries=3, default_retry_delay=60)
def emit_invoice_for_subscription(self, user_id: str, amount: str, reference_id: str):
    """NFS-e da assinatura do comprador (100% servico da plataforma)."""
    from django.contrib.auth import get_user_model

    from .invoicing import InvoiceProviderError, issue_service_invoice
    from .models import Invoice

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

    send_mail(
        subject="Sua nota fiscal — assinatura",
        message=render_to_string(
            "emails/invoice_issued.txt",
            {"invoice": invoice, "order": None, "site_name": settings.SITE_NAME},
        ),
        from_email=settings.DEFAULT_FROM_EMAIL,
        recipient_list=[invoice.recipient_email],
    )
