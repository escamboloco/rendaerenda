import logging
from datetime import timedelta

from celery import shared_task
from django.conf import settings
from django.core.mail import send_mail
from django.template.loader import render_to_string
from django.utils import timezone

from .labels import purchase_label_for_order
from .models import Shipment
from .services import mark_delivered, track_shipment

logger = logging.getLogger(__name__)


@shared_task
def send_shipment_posted_email(shipment_id: str):
    """Avisa o comprador que o item foi postado, com o codigo de rastreio."""
    shipment = Shipment.objects.select_related("order__buyer").get(id=shipment_id)
    recipient = shipment.order.payer_email
    if not recipient:
        logger.warning("Pedido %s sem e-mail do comprador — e-mail de postagem pulado.", shipment.order_id)
        return
    try:
        send_mail(
            subject=f"Seu pedido #{str(shipment.order_id)[:8]} foi postado",
            message=render_to_string(
                "emails/shipment_posted.txt",
                {"shipment": shipment, "order": shipment.order, "site_name": settings.SITE_NAME},
            ),
            from_email=settings.DEFAULT_FROM_EMAIL,
            recipient_list=[recipient],
        )
    except Exception:
        logger.exception("Falha ao enviar e-mail de postagem do pedido %s", shipment.order_id)


@shared_task(bind=True, max_retries=5, default_retry_delay=120)
def buy_label_for_order(self, order_id: str):
    """
    Assim que o pagamento confirma, a plataforma compra a etiqueta no
    SuperFrete com o frete pago pelo comprador. Remetente = nome neutro
    da plataforma; CEP de origem = da vendedora.
    """
    result = purchase_label_for_order(order_id)
    if result.ok:
        return
    # Sem worker Celery no Render (ALWAYS_EAGER): o cron buy_pending_labels
    # retenta. Com broker real, reagendamos aqui.
    if result.retryable and not getattr(settings, "CELERY_TASK_ALWAYS_EAGER", False):
        raise self.retry(exc=Exception(result.detail or "etiqueta pendente"))
    logger.warning(
        "Etiqueta do pedido %s pendente (%s) — será retentada pelo cron.",
        order_id,
        result.detail,
    )


@shared_task
def poll_active_shipments():
    """Roda periodicamente (celery beat) e atualiza rastreio dos envios em andamento."""
    active = Shipment.objects.filter(
        status__in=[Shipment.Status.AWAITING_POSTING, Shipment.Status.POSTED, Shipment.Status.IN_TRANSIT]
    )
    for shipment in active:
        try:
            if (
                shipment.shipping_provider == "superfrete"
                and shipment.provider_order_id
            ):
                _sync_superfrete_status(shipment)
            elif shipment.tracking_code:
                track_shipment(shipment)
        except Exception:
            logger.exception("Falha ao rastrear envio %s", shipment.id)


def _sync_superfrete_status(shipment: Shipment):
    from . import superfrete

    data = superfrete.track(shipment.provider_order_id)
    provider_status = data.get("status", "")
    tracking = data.get("tracking") or shipment.tracking_code

    was_awaiting = shipment.status == Shipment.Status.AWAITING_POSTING
    if provider_status == "posted" and shipment.status == Shipment.Status.AWAITING_POSTING:
        shipment.status = Shipment.Status.POSTED
        shipment.posted_at = timezone.now()
    elif provider_status in {"in_transit", "in-transit"}:
        shipment.status = Shipment.Status.IN_TRANSIT
    elif provider_status == "delivered":
        mark_delivered(shipment)
    elif provider_status in {"cancelled", "canceled"}:
        shipment.status = Shipment.Status.RETURNED

    shipment.tracking_code = tracking
    shipment.last_tracking_event = provider_status
    shipment.last_tracking_check_at = timezone.now()
    shipment.save()

    if was_awaiting and shipment.status == Shipment.Status.POSTED and tracking:
        from apps.payments.models import Order

        shipment.order.status = Order.Status.SHIPPED
        shipment.order.save(update_fields=["status"])
        send_shipment_posted_email.delay(str(shipment.id))


@shared_task
def release_confirmed_deliveries():
    """
    Libera o saldo da vendedora quando o comprador confirma ou a janela
    de contestacao passa sem disputa.
    """
    from apps.wallet.services import release_and_payout

    window = timedelta(hours=settings.DELIVERY_CONFIRMATION_WINDOW_HOURS)
    cutoff = timezone.now() - window

    to_release = (
        Shipment.objects.filter(
            status=Shipment.Status.DELIVERED,
            buyer_disputed_at__isnull=True,
            order__wallet_entries__available_at__gt=timezone.now(),
        )
        .filter(models_q_confirmed_or_expired(cutoff))
        .select_related("order")
        .distinct()
    )

    for shipment in to_release:
        if release_and_payout(shipment.order):
            logger.info("Custodia liberada e repasse disparado para o pedido %s", shipment.order_id)


def models_q_confirmed_or_expired(cutoff):
    from django.db.models import Q

    return Q(buyer_confirmed_at__isnull=False) | Q(delivered_at__lte=cutoff)
