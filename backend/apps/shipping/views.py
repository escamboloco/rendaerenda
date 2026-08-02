from django.shortcuts import get_object_or_404
from django.utils import timezone
from rest_framework import status as http_status
from rest_framework.exceptions import PermissionDenied
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.catalog.models import Product
from apps.payments.models import Order

from .models import Shipment
from .serializers import FreightOptionSerializer, FreightQuoteRequestSerializer, MarkPostedSerializer
from .services import (
    calculate_freight_options,
    products_are_payment_test,
    save_quote,
    test_free_freight_option,
)
from .tasks import send_shipment_posted_email


class FreightQuoteView(APIView):
    """
    POST usado na sacola, na página de produto e no checkout.

    Embalagem neutra é custo da vendedora — não entra no frete do comprador.
    Peças leves cotam como envelope pequeno. Cada peça usa o valor declarado
    pela vendedora (ou o preço do anúncio) no seguro.

    Resposta: objeto com `options` (envio único da sacola — o que o checkout
    cobra) e `items` (cotação individual por peça, para transparência).
    """

    permission_classes = [AllowAny]
    throttle_scope = "freight"

    def post(self, request):
        from decimal import Decimal

        from .package_defaults import cheapest_option, quote_package

        serializer = FreightQuoteRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data

        products = list(
            Product.objects.select_related("store").filter(id__in=data["product_ids"])
        )
        if not products:
            return Response(
                {"detail": "Produtos não encontrados."},
                status=http_status.HTTP_404_NOT_FOUND,
            )

        quantities = {
            str(key): int(value)
            for key, value in (data.get("quantities") or {}).items()
        }
        for product in products:
            quantities.setdefault(str(product.id), 1)

        destination_cep = data["destination_cep"]
        store = products[0].store
        origin_cep = store.origin_cep
        origin_city = (store.origin_city or "").strip()
        origin_state = (store.origin_state or "").strip().upper()

        physical = [p for p in products if p.requires_shipping]
        if not physical:
            free = test_free_freight_option()
            payload = {
                "service": free.service,
                "label": free.label,
                "price": 0.0,
                "deadline_days": free.deadline_days,
                "company": free.company,
                "origin_city": origin_city,
                "origin_state": origin_state,
            }
            return Response(
                {
                    "options": [payload],
                    "items": [],
                    "items_freight_total": 0.0,
                    "origin_city": origin_city,
                    "origin_state": origin_state,
                }
            )

        # --- cotação individual por peça (transparência na sacola) ---
        item_rows = []
        items_total = 0.0
        for product in physical:
            qty = quantities.get(str(product.id), 1)
            weight, length, width, height = quote_package(
                [product], {str(product.id): qty}
            )
            declared = float(product.shipping_declared_value) * qty
            if products_are_payment_test([product]):
                item_options = [test_free_freight_option()]
            else:
                try:
                    item_options = calculate_freight_options(
                        destination_cep=destination_cep,
                        weight_grams=weight,
                        length_cm=length,
                        width_cm=width,
                        height_cm=height,
                        origin_cep=origin_cep,
                        declared_value=declared,
                    )
                except Exception:
                    item_options = []
            chosen = cheapest_option(item_options)
            price = round(float(chosen.price), 2) if chosen else 0.0
            items_total = round(items_total + price, 2)
            item_rows.append(
                {
                    "product_id": str(product.id),
                    "title": product.title,
                    "qty": qty,
                    "declared_value": str(
                        (product.shipping_declared_value * qty).quantize(Decimal("0.01"))
                    ),
                    "price": price,
                    "label": chosen.label if chosen else "Indisponível",
                    "deadline_days": chosen.deadline_days if chosen else None,
                    "service": chosen.service if chosen else "",
                }
            )

        # --- envio único da sacola (o que o checkout cobra) ---
        total_weight, length, width, height = quote_package(physical, quantities)
        declared_value = sum(
            float(p.shipping_declared_value) * quantities.get(str(p.id), 1)
            for p in physical
        )

        if products_are_payment_test(physical):
            options = [test_free_freight_option()]
        else:
            try:
                options = calculate_freight_options(
                    destination_cep=destination_cep,
                    weight_grams=total_weight,
                    length_cm=length,
                    width_cm=width,
                    height_cm=height,
                    origin_cep=origin_cep,
                    declared_value=declared_value,
                )
            except Exception:
                options = []
        options = sorted(
            options, key=lambda o: (float(o.price), int(o.deadline_days or 99))
        )
        for option in options:
            save_quote(
                destination_cep, total_weight, option, origin_cep=origin_cep or ""
            )

        serialized = FreightOptionSerializer(
            [
                {
                    "service": o.service,
                    "label": o.label,
                    "price": round(float(o.price), 2),
                    "deadline_days": o.deadline_days,
                    "company": o.company,
                    "origin_city": origin_city,
                    "origin_state": origin_state,
                }
                for o in options
            ],
            many=True,
        ).data
        return Response(
            {
                "options": serialized,
                "items": item_rows,
                "items_freight_total": items_total,
                "origin_city": origin_city,
                "origin_state": origin_state,
            }
        )


class MarkPostedView(APIView):
    """
    POST /api/vendedora/pedidos/<order_id>/postagem/ — a vendedora registra
    o código de rastreio após postar nos Correios. Dispara o e-mail de
    rastreio para o comprador e inicia o poll periódico do rastreio
    (celery beat), que libera o saldo antecipado na entrega.
    """

    permission_classes = [IsAuthenticated]
    throttle_scope = "checkout"

    def post(self, request, order_id):
        store = getattr(request.user, "store", None)
        if not store:
            raise PermissionDenied("Usuário não possui loja.")
        order = get_object_or_404(Order, id=order_id, store=store)
        if order.status not in (Order.Status.PAID, Order.Status.SHIPPED):
            return Response(
                {"detail": "Só é possível registrar postagem de pedido pago."},
                status=http_status.HTTP_409_CONFLICT,
            )

        serializer = MarkPostedSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        shipment = order.shipment
        shipment.tracking_code = serializer.validated_data["tracking_code"]
        shipment.status = Shipment.Status.POSTED
        shipment.posted_at = timezone.now()
        shipment.save(update_fields=["tracking_code", "status", "posted_at"])

        order.status = Order.Status.SHIPPED
        order.save(update_fields=["status"])

        send_shipment_posted_email.delay(str(shipment.id))
        return Response({"status": shipment.status, "tracking_code": shipment.tracking_code})


class RequestLabelView(APIView):
    """
    POST /api/vendedora/pedidos/<order_id>/etiqueta/ — a vendedora pede
    (ou retenta) a compra da etiqueta SuperFrete e recebe o link do PDF.
    """

    permission_classes = [IsAuthenticated]
    throttle_scope = "checkout"

    def post(self, request, order_id):
        from .labels import purchase_label_for_order

        store = getattr(request.user, "store", None)
        if not store:
            raise PermissionDenied("Usuário não possui loja.")
        order = get_object_or_404(Order, id=order_id, store=store)
        if order.status not in (Order.Status.PAID, Order.Status.SHIPPED):
            return Response(
                {"detail": "Só é possível gerar etiqueta de pedido pago."},
                status=http_status.HTTP_409_CONFLICT,
            )
        if not hasattr(order, "shipment"):
            return Response(
                {"detail": "Este pedido não tem envio físico."},
                status=http_status.HTTP_400_BAD_REQUEST,
            )

        result = purchase_label_for_order(str(order.id))
        if result.ok:
            return Response(
                {
                    "status": "ready",
                    "label_url": result.label_url,
                    "tracking_code": result.tracking_code,
                    "detail": result.detail,
                }
            )
        return Response(
            {
                "status": "pending",
                "detail": result.detail
                or "Ainda não foi possível gerar a etiqueta. Tente de novo em instantes.",
            },
            status=http_status.HTTP_503_SERVICE_UNAVAILABLE,
        )


class DeliveryConfirmationView(APIView):
    """
    POST /api/pedidos/<order_id>/recebimento/ — o comprador confirma que
    o item chegou de acordo (libera o saldo da vendedora na hora) ou
    contesta (trava a liberação para análise). Sem ação em até
    DELIVERY_CONFIRMATION_WINDOW_HOURS após a entrega, a liberação é
    automática (docs/checkout.md).
    """

    permission_classes = [IsAuthenticated]
    throttle_scope = "checkout"

    def post(self, request, order_id):
        from apps.wallet.services import release_sale

        order = get_object_or_404(Order, id=order_id, buyer=request.user)
        shipment = order.shipment
        if shipment.status != Shipment.Status.DELIVERED:
            return Response(
                {"detail": "A confirmação fica disponível quando a entrega for registrada."},
                status=http_status.HTTP_409_CONFLICT,
            )
        if shipment.buyer_confirmed_at or shipment.buyer_disputed_at:
            return Response({"detail": "Você já respondeu sobre este pedido."}, status=http_status.HTTP_409_CONFLICT)

        action = request.data.get("action")
        if action == "confirm":
            shipment.buyer_confirmed_at = timezone.now()
            shipment.save(update_fields=["buyer_confirmed_at"])
            release_sale(order)
            return Response({"status": "confirmed"})
        if action == "dispute":
            shipment.buyer_disputed_at = timezone.now()
            shipment.save(update_fields=["buyer_disputed_at"])
            order.status = Order.Status.DISPUTED
            order.save(update_fields=["status"])
            return Response({"status": "disputed"})
        return Response({"detail": "Ação inválida (use confirm ou dispute)."}, status=http_status.HTTP_400_BAD_REQUEST)
