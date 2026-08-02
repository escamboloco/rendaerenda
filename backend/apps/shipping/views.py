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
    POST usado na página de produto e no checkout: preço, prazo e
    transportadora, cotados a partir do CEP da REMETENTE (loja).

    Embalagem neutra é custo da vendedora — não entra no frete do comprador.
    Peças leves cotam como envelope pequeno (peso de calcinha média).
    """

    permission_classes = [AllowAny]
    throttle_scope = "freight"

    def post(self, request):
        serializer = FreightQuoteRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data

        products = list(Product.objects.select_related("store").filter(id__in=data["product_ids"]))
        if not products:
            return Response({"detail": "Produtos não encontrados."}, status=http_status.HTTP_404_NOT_FOUND)

        from .package_defaults import quote_package

        total_weight, length, width, height = quote_package(products)
        destination_cep = data["destination_cep"]
        store = products[0].store
        origin_cep = store.origin_cep
        declared_value = sum(p.price for p in products)

        if products_are_payment_test(products):
            options = [test_free_freight_option()]
        else:
            options = calculate_freight_options(
                destination_cep=destination_cep,
                weight_grams=total_weight,
                length_cm=length,
                width_cm=width,
                height_cm=height,
                origin_cep=origin_cep,
                declared_value=declared_value,
            )
        options = sorted(options, key=lambda o: (float(o.price), int(o.deadline_days or 99)))
        for option in options:
            save_quote(destination_cep, total_weight, option, origin_cep=origin_cep or "")

        origin_city = (store.origin_city or "").strip()
        origin_state = (store.origin_state or "").strip().upper()
        return Response(
            FreightOptionSerializer(
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
