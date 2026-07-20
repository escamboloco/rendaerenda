import logging
from datetime import timedelta

from celery import shared_task
from django.conf import settings
from django.core.mail import send_mail
from django.template.loader import render_to_string
from django.utils import timezone

from .models import Shipment
from .services import mark_delivered, track_shipment

logger = logging.getLogger(__name__)


@shared_task
def send_shipment_posted_email(shipment_id: str):
    """Avisa o comprador que o item foi postado, com o codigo de rastreio."""
    shipment = Shipment.objects.select_related("order__buyer").get(id=shipment_id)
    send_mail(
        subject=f"Seu pedido #{str(shipment.order_id)[:8]} foi postado",
        message=render_to_string(
            "emails/shipment_posted.txt",
            {"shipment": shipment, "order": shipment.order, "site_name": settings.SITE_NAME},
        ),
        from_email=settings.DEFAULT_FROM_EMAIL,
        recipient_list=[shipment.order.buyer.email],
    )


@shared_task(bind=True, max_retries=5, default_retry_delay=120)
def buy_label_for_order(self, order_id: str):
    """
    Fluxo automatizado da etiqueta (docs/checkout.md): assim que o
    pagamento confirma, a PLATAFORMA compra a etiqueta no Melhor Envio
    com o frete que o comprador ja pagou, e a vendedora recebe por
    e-mail o PDF pronto pra imprimir e colar + o ponto de coleta mais
    proximo. Ela nao paga nada nem digita codigo de rastreio.
    """
    from apps.payments.models import Order

    from . import melhor_envio

    order = Order.objects.select_related("store__owner", "buyer", "shipment").get(id=order_id)
    shipment = order.shipment
    if shipment.label_url:
        return  # idempotente - webhook do PSP pode repetir

    if not shipment.service.startswith("me-"):
        # Modo Correios direto: sem compra automatica de etiqueta - a
        # vendedora posta e registra o rastreio manualmente no painel.
        return

    first_item = order.items.select_related("product").first()
    product = first_item.product

    try:
        bought = melhor_envio.buy_label(
            service_id=int(shipment.service.removeprefix("me-")),
            origin_cep=order.store.origin_cep or settings.CORREIOS_ORIGIN_CEP,
            destination_cep=order.shipping_address.get("cep", ""),
            seller_name=order.store.owner.get_full_name() or order.store.owner.username,
            seller_document=order.store.owner.cpf,
            buyer_name=order.buyer.get_full_name() or order.buyer.username,
            buyer_document=order.buyer.cpf,
            shipping_address=order.shipping_address,
            weight_grams=product.weight_grams,
            length_cm=product.length_cm,
            width_cm=product.width_cm,
            height_cm=product.height_cm,
            declared_value=order.items_total,
            order_reference=str(order.id),
        )
    except melhor_envio.MelhorEnvioError as exc:
        logger.warning("Falha ao comprar etiqueta do pedido %s: %s", order_id, exc)
        raise self.retry(exc=exc)

    shipment.melhor_envio_order_id = bought.order_id
    shipment.label_url = bought.label_url
    if bought.tracking_code:
        shipment.tracking_code = bought.tracking_code
    shipment.save(update_fields=["melhor_envio_order_id", "label_url", "tracking_code"])

    # Ponto de coleta mais proximo da vendedora, incluido no e-mail.
    nearest = None
    try:
        points = melhor_envio.find_dropoff_points(
            cep=order.store.origin_cep or settings.CORREIOS_ORIGIN_CEP
        )
        nearest = points[0] if points else None
    except melhor_envio.MelhorEnvioError:
        pass

    send_mail(
        subject=f"Etiqueta pronta — pedido #{str(order.id)[:8]}",
        message=render_to_string(
            "emails/label_ready.txt",
            {"order": order, "shipment": shipment, "nearest": nearest, "site_name": settings.SITE_NAME},
        ),
        from_email=settings.DEFAULT_FROM_EMAIL,
        recipient_list=[order.store.owner.email],
    )


@shared_task
def poll_active_shipments():
    """Roda periodicamente (celery beat) e atualiza rastreio dos envios em andamento."""
    active = Shipment.objects.filter(
        status__in=[Shipment.Status.AWAITING_POSTING, Shipment.Status.POSTED, Shipment.Status.IN_TRANSIT]
    )
    for shipment in active:
        try:
            if shipment.melhor_envio_order_id:
                _sync_melhor_envio_status(shipment)
            elif shipment.tracking_code:
                track_shipment(shipment)
        except Exception:
            logger.exception("Falha ao rastrear envio %s", shipment.id)


def _sync_melhor_envio_status(shipment: Shipment):
    from . import melhor_envio

    data = melhor_envio.track(shipment.melhor_envio_order_id)
    me_status = data.get("status", "")
    tracking = data.get("tracking") or shipment.tracking_code

    was_awaiting = shipment.status == Shipment.Status.AWAITING_POSTING
    if me_status == "posted" and shipment.status == Shipment.Status.AWAITING_POSTING:
        shipment.status = Shipment.Status.POSTED
        shipment.posted_at = timezone.now()
    elif me_status == "delivered":
        mark_delivered(shipment)

    shipment.tracking_code = tracking
    shipment.last_tracking_event = me_status
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
    Roda de hora em hora (celery beat). Libera o saldo da vendedora
    quando: o comprador confirmou o recebimento, OU a janela de
    contestacao (DELIVERY_CONFIRMATION_WINDOW_HOURS, 24h por padrao)
    passou desde a entrega sem contestacao. docs/checkout.md.
    """
    from apps.wallet.services import release_sale

    window = timedelta(hours=settings.DELIVERY_CONFIRMATION_WINDOW_HOURS)
    cutoff = timezone.now() - window

    to_release = Shipment.objects.filter(
        status=Shipment.Status.DELIVERED,
        buyer_disputed_at__isnull=True,
        order__wallet_entries__available_at__gt=timezone.now(),
    ).filter(
        models_q_confirmed_or_expired(cutoff)
    ).select_related("order").distinct()

    for shipment in to_release:
        release_sale(shipment.order)
        logger.info("Saldo liberado para o pedido %s", shipment.order_id)


def models_q_confirmed_or_expired(cutoff):
    from django.db.models import Q

    return Q(buyer_confirmed_at__isnull=False) | Q(delivered_at__lte=cutoff)
