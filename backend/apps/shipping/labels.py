"""
Compra da etiqueta SuperFrete para a vendedora imprimir e postar.

Chamado no pagamento confirmado, por cron de retentativa e pela API da
carteira. Embalagem neutra é da vendedora; a plataforma só paga o frete.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass

from django.conf import settings
from django.core.mail import send_mail
from django.template.loader import render_to_string

from . import superfrete
from .package_defaults import cheapest_option, quote_package
from .services import calculate_freight_options, platform_buys_shipping_label, shipping_sender

logger = logging.getLogger(__name__)


@dataclass
class LabelPurchaseResult:
    ok: bool
    label_url: str = ""
    tracking_code: str = ""
    detail: str = ""
    retryable: bool = False


def resolve_superfrete_service_id(order, shipment, *, weight, length, width, height) -> int | None:
    """
    Garante um service_id SuperFrete mesmo se o checkout salvou 'pac'
    (tarifa fixa / cotação offline).
    """
    service = (shipment.service or "").strip()
    if service.startswith("sf-"):
        try:
            return int(service.removeprefix("sf-"))
        except ValueError:
            pass

    address = order.shipping_address or {}
    destination = "".join(c for c in str(address.get("cep", "")) if c.isdigit())
    origin = (order.store.origin_cep or "").strip()
    if len(destination) == 8 and origin:
        try:
            options = calculate_freight_options(
                destination_cep=destination,
                weight_grams=weight,
                length_cm=length,
                width_cm=width,
                height_cm=height,
                origin_cep=origin,
                declared_value=order.items_total,
            )
            chosen = cheapest_option(
                [o for o in options if str(o.service).startswith("sf-")]
            )
            if chosen:
                shipment.service = chosen.service
                shipment.save(update_fields=["service"])
                return int(chosen.service.removeprefix("sf-"))
        except Exception:
            logger.exception(
                "Falha ao recotar SuperFrete para etiqueta do pedido %s", order.id
            )

    # Fallback: primeiro serviço configurado (Mini Envios = 17 por padrão).
    raw = (getattr(settings, "SUPERFRETE_SERVICES", "") or "17").split(",")[0].strip()
    try:
        service_id = int(raw)
    except ValueError:
        return None
    shipment.service = f"sf-{service_id}"
    shipment.save(update_fields=["service"])
    return service_id


def purchase_label_for_order(order_id: str) -> LabelPurchaseResult:
    """
    Compra (ou finaliza) a etiqueta e avisa a vendedora por e-mail.
    Idempotente: se já houver label_url, só devolve sucesso.
    """
    from apps.payments.models import Order

    if not platform_buys_shipping_label():
        return LabelPurchaseResult(ok=False, detail="Compra de etiqueta desligada.")

    try:
        order = Order.objects.select_related("store__owner", "buyer", "shipment").get(
            id=order_id
        )
    except Order.DoesNotExist:
        return LabelPurchaseResult(ok=False, detail="Pedido não encontrado.")

    if not hasattr(order, "shipment"):
        return LabelPurchaseResult(ok=False, detail="Pedido sem envio físico.")

    shipment = order.shipment
    if shipment.label_url:
        return LabelPurchaseResult(
            ok=True,
            label_url=shipment.label_url,
            tracking_code=shipment.tracking_code or "",
            detail="Etiqueta já pronta.",
        )

    if order.status not in (Order.Status.PAID, Order.Status.SHIPPED):
        return LabelPurchaseResult(ok=False, detail="Pedido ainda não está pago.")

    physical_items = [
        item
        for item in order.items.select_related("product").all()
        if item.product.requires_shipping
    ]
    if not physical_items:
        return LabelPurchaseResult(ok=False, detail="Pedido sem itens físicos.")

    products = [item.product for item in physical_items]
    quantities = {str(item.product_id): item.quantity for item in physical_items}
    weight, length, width, height = quote_package(products, quantities)

    try:
        if shipment.provider_order_id:
            if shipment.shipping_provider and shipment.shipping_provider != "superfrete":
                return LabelPurchaseResult(
                    ok=False,
                    detail="Etiqueta de outro integrador.",
                )
            provider_order_id = shipment.provider_order_id
        else:
            service_id = resolve_superfrete_service_id(
                order,
                shipment,
                weight=weight,
                length=length,
                width=width,
                height=height,
            )
            if service_id is None:
                return LabelPurchaseResult(
                    ok=False,
                    detail="Sem serviço SuperFrete disponível.",
                    retryable=True,
                )

            address = order.shipping_address or {}
            provider_order_id = superfrete.create_label(
                service_id=service_id,
                sender=shipping_sender(order.store),
                recipient={
                    "name": order.payer_name,
                    "document": order.payer_cpf,
                    "email": order.payer_email,
                    "postal_code": address.get("cep", ""),
                    "address": address.get("street", ""),
                    "number": address.get("number", ""),
                    "complement": address.get("complement", ""),
                    "district": address.get("neighborhood", ""),
                    "city": address.get("city", ""),
                    "state_abbr": address.get("state", ""),
                },
                products=[
                    {
                        "name": "Peça de vestuário usada",
                        "quantity": item.quantity,
                        "unitary_value": item.unit_price,
                    }
                    for item in physical_items
                ],
                weight_grams=weight,
                length_cm=length,
                width_cm=width,
                height_cm=height,
                declared_value=order.items_total,
                order_reference=str(order.id),
            )
            shipment.provider_order_id = provider_order_id
            shipment.shipping_provider = "superfrete"
            shipment.save(update_fields=["provider_order_id", "shipping_provider"])

        bought = superfrete.finalize_label(provider_order_id)
    except superfrete.SuperFreteConfigurationError as exc:
        logger.warning("Etiqueta do pedido %s não configurada: %s", order_id, exc)
        return LabelPurchaseResult(ok=False, detail=str(exc), retryable=True)
    except superfrete.SuperFreteError as exc:
        logger.warning("Falha ao comprar etiqueta do pedido %s: %s", order_id, exc)
        return LabelPurchaseResult(ok=False, detail=str(exc), retryable=True)

    shipment.provider_order_id = bought.order_id
    shipment.shipping_provider = "superfrete"
    shipment.label_url = bought.label_url
    if bought.tracking_code:
        shipment.tracking_code = bought.tracking_code
    shipment.save(
        update_fields=[
            "provider_order_id",
            "shipping_provider",
            "label_url",
            "tracking_code",
        ]
    )

    _email_label_ready(order, shipment)
    return LabelPurchaseResult(
        ok=True,
        label_url=shipment.label_url,
        tracking_code=shipment.tracking_code or "",
        detail="Etiqueta pronta.",
    )


def _email_label_ready(order, shipment) -> None:
    seller_email = getattr(order.store.owner, "email", "") or ""
    if not seller_email:
        logger.warning(
            "Pedido %s: loja sem e-mail — etiqueta pronta só na carteira.", order.id
        )
        return
    scheme = "http" if settings.DEBUG else "https"
    wallet_url = f"{scheme}://{settings.SITE_DOMAIN}/carteira/"
    try:
        send_mail(
            subject=f"Etiqueta pronta — pedido #{str(order.id)[:8]}",
            message=render_to_string(
                "emails/label_ready.txt",
                {
                    "order": order,
                    "shipment": shipment,
                    "site_name": settings.SITE_NAME,
                    "wallet_url": wallet_url,
                },
            ),
            from_email=settings.DEFAULT_FROM_EMAIL,
            recipient_list=[seller_email],
        )
    except Exception:
        logger.exception("Falha ao enviar e-mail de etiqueta do pedido %s", order.id)


def buy_pending_labels(*, limit: int = 30) -> dict:
    """Retenta pedidos pagos sem PDF de etiqueta."""
    from apps.payments.models import Order

    from .models import Shipment

    pending = (
        Shipment.objects.filter(
            label_url="",
            order__status=Order.Status.PAID,
        )
        .select_related("order")
        .order_by("order__created_at")[:limit]
    )
    stats = {"tried": 0, "ok": 0, "failed": 0}
    for shipment in pending:
        stats["tried"] += 1
        result = purchase_label_for_order(str(shipment.order_id))
        if result.ok:
            stats["ok"] += 1
        else:
            stats["failed"] += 1
            logger.info(
                "Retentativa de etiqueta do pedido %s: %s",
                shipment.order_id,
                result.detail,
            )
    return stats
