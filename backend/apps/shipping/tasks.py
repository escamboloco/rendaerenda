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
    Melhor Envio com o frete pago pelo comprador. Remetente = nome neutro
    da plataforma; CEP de origem = da vendedora.
    """
    from apps.payments.models import Order

    from . import melhor_envio
    from .services import platform_buys_shipping_label

    if not platform_buys_shipping_label():
        return

    order = Order.objects.select_related("store__owner", "buyer", "shipment").get(id=order_id)
    if not hasattr(order, "shipment"):
        return
    shipment = order.shipment
    if shipment.label_url:
        return

    if not shipment.service.startswith("me-"):
        # Cotação flat / Correios direto: sem compra automática.
        logger.info(
            "Pedido %s sem serviço Melhor Envio (%s) — etiqueta manual.",
            order_id,
            shipment.service,
        )
        return

    physical_items = [
        item
        for item in order.items.select_related("product").all()
        if item.product.requires_shipping
    ]
    if not physical_items:
        return

    weight = sum(item.product.weight_grams * item.quantity for item in physical_items)
    length = max(item.product.length_cm for item in physical_items)
    width = max(item.product.width_cm for item in physical_items)
    height = sum(item.product.height_cm * item.quantity for item in physical_items)

    try:
        bought = melhor_envio.buy_label(
            service_id=int(shipment.service.removeprefix("me-")),
            origin_cep=order.store.origin_cep or settings.CORREIOS_ORIGIN_CEP,
            destination_cep=(order.shipping_address or {}).get("cep", ""),
            buyer_name=order.payer_name,
            buyer_document=order.payer_cpf,
            shipping_address=order.shipping_address or {},
            weight_grams=weight,
            length_cm=length,
            width_cm=width,
            height_cm=height,
            declared_value=order.items_total,
            order_reference=str(order.id),
        )
    except melhor_envio.MelhorEnvioError as exc:
        logger.warning("Falha ao comprar etiqueta do pedido %s: %s", order_id, exc)
        # Sem token / sandbox vazio: não fica em retry infinito (dev/testes).
        if not (settings.MELHOR_ENVIO_TOKEN or "").strip():
            return
        raise self.retry(exc=exc)

    shipment.melhor_envio_order_id = bought.order_id
    shipment.label_url = bought.label_url
    if bought.tracking_code:
        shipment.tracking_code = bought.tracking_code
    shipment.save(update_fields=["melhor_envio_order_id", "label_url", "tracking_code"])

    nearest = None
    try:
        points = melhor_envio.find_dropoff_points(
            cep=order.store.origin_cep or settings.CORREIOS_ORIGIN_CEP
        )
        nearest = points[0] if points else None
    except melhor_envio.MelhorEnvioError:
        pass

    seller_email = order.store.owner.email
    if seller_email:
        try:
            send_mail(
                subject=f"Etiqueta pronta — pedido #{str(order.id)[:8]}",
                message=render_to_string(
                    "emails/label_ready.txt",
                    {
                        "order": order,
                        "shipment": shipment,
                        "nearest": nearest,
                        "site_name": settings.SITE_NAME,
                    },
                ),
                from_email=settings.DEFAULT_FROM_EMAIL,
                recipient_list=[seller_email],
            )
        except Exception:
            logger.exception("Falha ao enviar e-mail de etiqueta do pedido %s", order_id)


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
