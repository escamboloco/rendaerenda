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
    transportadora, cotados a partir do CEP da REMETENTE (loja). A taxa
    de embalagem (PACKAGING_FEE) é somada em cada opção — o valor
    exibido é exatamente o que o comprador vai pagar de envio.
    """

    permission_classes = [AllowAny]
    throttle_scope = None

    def post(self, request):
        from django.conf import settings

        serializer = FreightQuoteRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data

        products = list(Product.objects.select_related("store").filter(id__in=data["product_ids"]))
        if not products:
            return Response({"detail": "Produtos não encontrados."}, status=http_status.HTTP_404_NOT_FOUND)
        total_weight = sum(p.weight_grams for p in products)
        destination_cep = data["destination_cep"]
        origin_cep = products[0].store.origin_cep
        declared_value = sum(p.price for p in products)

        if products_are_payment_test(products):
            options = [test_free_freight_option()]
            packaging = 0.0
        else:
            options = calculate_freight_options(
                destination_cep=destination_cep,
                weight_grams=total_weight,
                length_cm=max((p.length_cm for p in products), default=16),
                width_cm=max((p.width_cm for p in products), default=11),
                height_cm=sum(p.height_cm for p in products),
                origin_cep=origin_cep,
                declared_value=declared_value,
            )
            packaging = float(settings.PACKAGING_FEE)
        for option in options:
            save_quote(destination_cep, total_weight, option)

        return Response(
            FreightOptionSerializer(
                [
                    {
                        "service": o.service,
                        "label": o.label,
                        "price": round(o.price + packaging, 2),
                        "deadline_days": o.deadline_days,
                        "company": o.company,
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


class DropoffPointsView(APIView):
    """GET /api/vendedora/pontos-coleta/ — pontos de postagem mais próximos do CEP da loja."""

    permission_classes = [IsAuthenticated]

    def get(self, request):
        from django.conf import settings

        from . import melhor_envio

        store = getattr(request.user, "store", None)
        if not store:
            raise PermissionDenied("Usuário não possui loja.")
        cep = store.origin_cep or settings.CORREIOS_ORIGIN_CEP
        if not cep:
            return Response({"detail": "Cadastre o CEP de postagem da sua loja."}, status=http_status.HTTP_400_BAD_REQUEST)

        try:
            points = melhor_envio.find_dropoff_points(cep=cep)
        except melhor_envio.MelhorEnvioError:
            return Response({"detail": "Não foi possível buscar os pontos agora."}, status=http_status.HTTP_502_BAD_GATEWAY)

        return Response([
            {
                "name": p.get("name", ""),
                "company": (p.get("company") or {}).get("name", ""),
                "address": (p.get("address") or {}).get("address", ""),
                "number": (p.get("address") or {}).get("number", ""),
                "city": (p.get("address") or {}).get("city", ""),
                "state": (p.get("address") or {}).get("state_abbr", ""),
            }
            for p in points[:5]
        ])
