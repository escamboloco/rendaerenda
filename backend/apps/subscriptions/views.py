from django.shortcuts import redirect
from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from .serializers import SubscriptionCheckoutSerializer
from .services import cancel_subscription, start_or_renew_subscription


def plans(request):
    # Modelo de negocio atual (docs/checkout.md): navegar e comprar NAO
    # exigem assinatura - a plataforma ganha so a comissao da venda. A
    # pagina de planos foi desativada; a URL permanece redirecionando pra
    # home para nao quebrar links antigos/indexados. O app subscriptions
    # segue instalado (historico de assinantes + possivel plano opcional
    # futuro de beneficios).
    return redirect("stores:home", permanent=True)


class SubscriptionCheckoutView(APIView):
    """POST /api/assinatura/checkout/ — inicia a cobranca (Pix/cartão) do plano escolhido."""

    permission_classes = [IsAuthenticated]
    throttle_scope = "checkout"

    def post(self, request):
        if not request.user.is_phone_verified:
            return Response(
                {"detail": "Confirme seu celular (vinculado ao seu CPF) antes de assinar.",
                 "action": "verify_phone"},
                status=status.HTTP_403_FORBIDDEN,
            )
        serializer = SubscriptionCheckoutSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        plan = serializer.validated_data["plan_id"]
        method = serializer.validated_data["payment_method"]

        charge = start_or_renew_subscription(user=request.user, plan=plan, method=method)
        return Response(
            {"payment_url": charge.payment_url, "pix_qr_code": charge.pix_qr_code},
            status=status.HTTP_201_CREATED,
        )


class SubscriptionCancelView(APIView):
    """POST /api/assinatura/cancelar/ — cancela a renovacao (permanece ativa ate current_period_end)."""

    permission_classes = [IsAuthenticated]

    def post(self, request):
        subscription = getattr(request.user, "subscription", None)
        if not subscription:
            return Response({"detail": "Você não tem assinatura ativa."}, status=status.HTTP_404_NOT_FOUND)
        cancel_subscription(subscription)
        return Response({"status": subscription.status})
