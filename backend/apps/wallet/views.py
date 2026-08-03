from django.conf import settings
from django.contrib.auth.decorators import login_required
from django.core.exceptions import ValidationError as DjangoValidationError
from django.shortcuts import render
from django.utils import timezone
from rest_framework import status
from rest_framework.exceptions import PermissionDenied, ValidationError
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from .models import WalletEntry, WithdrawalRequest
from .serializers import WalletBalanceSerializer, WalletEntrySerializer, WithdrawalRequestSerializer
from .services import request_withdrawal


def _seller_store(request):
    store = getattr(request.user, "store", None)
    if not store:
        raise PermissionDenied("Usuário não possui loja.")
    return store


@login_required
def dashboard(request):
    store = getattr(request.user, "store", None)
    if not store:
        return render(request, "wallet/no_store.html")

    from apps.payments.models import Order

    orders = (
        Order.objects.filter(
            store=store,
            status__in=[Order.Status.PAID, Order.Status.SHIPPED, Order.Status.DELIVERED],
        )
        .select_related("shipment")
        .order_by("-created_at")[:30]
    )

    return render(
        request,
        "wallet/dashboard.html",
        {
            "store": store,
            "available_balance": WalletEntry.objects.available_balance(store),
            "pending_balance": WalletEntry.objects.pending_balance(store),
            "entries": WalletEntry.objects.filter(store=store).order_by("-created_at")[:50],
            # "Retido ate quando": o saldo pendente sozinho nao responde a
            # pergunta que a vendedora faz. Cada linha traz a data em que
            # aquele valor vira sacavel, e a primeira delas vira o destaque.
            # Inclui REFERRAL_BONUS: para quem é embaixadora, esse retido
            # também é dinheiro dela esperando a mesma liberação.
            "held_entries": (
                WalletEntry.objects.filter(
                    store=store,
                    kind__in=[WalletEntry.Kind.SALE_CREDIT, WalletEntry.Kind.REFERRAL_BONUS],
                    available_at__gt=timezone.now(),
                )
                .select_related("order")
                .order_by("available_at")[:20]
            ),
            "next_release_at": (
                WalletEntry.objects.filter(
                    store=store,
                    kind__in=[WalletEntry.Kind.SALE_CREDIT, WalletEntry.Kind.REFERRAL_BONUS],
                    available_at__gt=timezone.now(),
                )
                .order_by("available_at")
                .values_list("available_at", flat=True)
                .first()
            ),
            "dispute_window_days": settings.DISPUTE_WINDOW_DAYS,
            "withdrawals": WithdrawalRequest.objects.filter(store=store).order_by("-requested_at")[:20],
            "release_days": settings.WALLET_RELEASE_DAYS_AFTER_SHIPPING,
            "orders": orders,
        },
    )


class WalletBalanceView(APIView):
    """GET /api/carteira/ — saldo disponível (sacável agora) e pendente (ainda em janela de liberação)."""

    permission_classes = [IsAuthenticated]

    def get(self, request):
        store = _seller_store(request)
        data = {
            "available_balance": WalletEntry.objects.available_balance(store),
            "pending_balance": WalletEntry.objects.pending_balance(store),
        }
        return Response(WalletBalanceSerializer(data).data)


class WalletHistoryView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        store = _seller_store(request)
        entries = WalletEntry.objects.filter(store=store).order_by("-created_at")[:100]
        return Response(WalletEntrySerializer(entries, many=True).data)


class WithdrawalRequestView(APIView):
    """POST /api/carteira/saque/ — saque via Pix, qualquer valor até o saldo disponível, a qualquer momento."""

    permission_classes = [IsAuthenticated]
    throttle_scope = "withdrawal"

    def post(self, request):
        store = _seller_store(request)
        serializer = WithdrawalRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        try:
            withdrawal = request_withdrawal(store=store, amount=serializer.validated_data["amount"])
        except DjangoValidationError as exc:
            raise ValidationError(exc.messages)

        return Response(WithdrawalRequestSerializer(withdrawal).data, status=status.HTTP_201_CREATED)

    def get(self, request):
        store = _seller_store(request)
        withdrawals = WithdrawalRequest.objects.filter(store=store).order_by("-requested_at")[:50]
        return Response(WithdrawalRequestSerializer(withdrawals, many=True).data)
