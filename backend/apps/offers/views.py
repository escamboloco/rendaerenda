from django.contrib.auth.decorators import login_required
from django.core.exceptions import ValidationError as DjangoValidationError
from django.shortcuts import get_object_or_404, render
from rest_framework import status
from rest_framework.exceptions import PermissionDenied, ValidationError
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.stores.models import Store

from .models import CustomOrderRequest
from .serializers import CustomRequestCreateSerializer, CustomRequestSerializer, SellerResponseSerializer
from .services import accept_request, counter_request, create_custom_request


@login_required
def my_requests_page(request):
    """Pagina unica: pedidos que EU fiz (comprador) e pedidos da MINHA loja (vendedora)."""
    sent = CustomOrderRequest.objects.filter(buyer=request.user).select_related("store", "product")
    received = CustomOrderRequest.objects.none()
    store = getattr(request.user, "store", None)
    if store:
        received = CustomOrderRequest.objects.filter(store=store).select_related("buyer", "product")
    return render(request, "offers/requests.html", {"sent": sent, "received": received, "store": store})


class CustomRequestCreateView(APIView):
    """POST /api/pedidos-personalizados/ — comprador descreve o item físico e oferece um valor."""

    permission_classes = [IsAuthenticated]
    throttle_scope = "offers"

    def post(self, request):
        if not request.user.is_phone_verified:
            return Response(
                {"detail": "Confirme seu celular (vinculado ao seu CPF) antes de enviar pedidos.",
                 "action": "verify_phone"},
                status=status.HTTP_403_FORBIDDEN,
            )

        serializer = CustomRequestCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        store = get_object_or_404(Store, slug=data["store_slug"], status=Store.Status.ACTIVE)
        if store.owner_id == request.user.id:
            raise PermissionDenied("Você não pode fazer pedido para a própria loja.")

        try:
            obj = create_custom_request(
                buyer=request.user,
                store=store,
                title=data["title"],
                description=data["description"],
                offered_price=data["offered_price"],
            )
        except DjangoValidationError as exc:
            raise ValidationError(exc.messages)
        return Response(CustomRequestSerializer(obj).data, status=status.HTTP_201_CREATED)


class SellerRespondView(APIView):
    """POST /api/vendedora/pedidos-personalizados/<id>/responder/ — aceitar, recusar ou contra-propor."""

    permission_classes = [IsAuthenticated]
    throttle_scope = "offers"

    def post(self, request, request_id):
        store = getattr(request.user, "store", None)
        if not store:
            raise PermissionDenied("Usuário não possui loja.")
        obj = get_object_or_404(
            CustomOrderRequest, id=request_id, store=store, status=CustomOrderRequest.Status.PENDING
        )

        serializer = SellerResponseSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data

        try:
            if data["action"] == "accept":
                accept_request(obj)
            elif data["action"] == "counter":
                counter_request(
                    obj, counter_price=data["counter_price"], counter_message=data.get("counter_message", "")
                )
            else:
                obj.status = CustomOrderRequest.Status.REJECTED
                obj.mark_responded()
                obj.save(update_fields=["status", "responded_at"])
        except DjangoValidationError as exc:
            raise ValidationError(exc.messages)
        return Response(CustomRequestSerializer(obj).data)


class BuyerDecideCounterView(APIView):
    """POST /api/pedidos-personalizados/<id>/decidir/ — comprador aceita a contra-proposta ou cancela."""

    permission_classes = [IsAuthenticated]
    throttle_scope = "offers"

    def post(self, request, request_id):
        obj = get_object_or_404(CustomOrderRequest, id=request_id, buyer=request.user)
        decision = request.data.get("action")

        if decision == "accept" and obj.status == CustomOrderRequest.Status.COUNTERED:
            accept_request(obj)
        elif decision == "cancel" and obj.status in (
            CustomOrderRequest.Status.PENDING,
            CustomOrderRequest.Status.COUNTERED,
        ):
            obj.status = CustomOrderRequest.Status.CANCELED
            obj.mark_responded()
            obj.save(update_fields=["status", "responded_at"])
        else:
            raise ValidationError("Ação inválida para o estado atual do pedido.")
        return Response(CustomRequestSerializer(obj).data)
