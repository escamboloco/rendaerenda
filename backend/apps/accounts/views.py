import hmac
import json

from django.conf import settings
from django.contrib.auth.decorators import login_required
from django.http import HttpResponseForbidden, JsonResponse
from django.shortcuts import redirect, render
from django.urls import reverse
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.debug import sensitive_post_parameters
from django.views.decorators.http import require_http_methods
from rest_framework import parsers, status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from .deletion import AccountDeletionError, account_has_open_orders, delete_user_account
from .models import SellerKYC, generate_kyc_code
from .serializers import AgeVerificationRequestSerializer, SellerKYCSerializer
from .services import AgeVerificationError, apply_verification_result, request_age_verification


@login_required
def verification_page(request):
    verification = getattr(request.user, "age_verification", None)
    return render(request, "accounts/verification.html", {"verification": verification})


@login_required
def seller_kyc_page(request):
    """
    Página de verificação. A linha do KYC é criada já na primeira visita
    para o código carimbado na selfie ficar estável durante a captura.
    """
    kyc, _ = SellerKYC.objects.get_or_create(user=request.user)
    # Em reenvio após recusa, gera código novo para invalidar selfie antiga.
    if kyc.status == SellerKYC.Status.REJECTED and request.GET.get("novo_codigo") == "1":
        kyc.verification_code = generate_kyc_code()
        kyc.save(update_fields=["verification_code"])
        return redirect("accounts_pages:seller_kyc_page")
    return render(request, "accounts/seller_kyc.html", {"kyc": kyc})


@login_required
def phone_page(request):
    verification = getattr(request.user, "phone_verification", None)
    return render(request, "accounts/phone.html", {"verification": verification})


@login_required
def profile_page(request):
    """Hub do comprador: conta, transações, pedidos, rastreios e conversas."""
    if request.method == "POST":
        alias = request.POST.get("public_alias", "").strip()[:40]
        request.user.public_alias = alias
        request.user.save(update_fields=["public_alias"])
        return redirect(f"{reverse('accounts_pages:profile_page')}?salvo=1")

    from apps.payments.models import Order, Payment

    orders = list(
        Order.objects.filter(buyer=request.user)
        .select_related("store", "shipment", "payment", "invoice")
        .prefetch_related("items", "messages")
        .order_by("-created_at")[:50]
    )
    active_statuses = {
        Order.Status.AWAITING_PAYMENT,
        Order.Status.PAID,
        Order.Status.SHIPPED,
        Order.Status.DISPUTED,
    }
    conversations = [order for order in orders if order.messages.all()]
    stats = {
        "orders": len(orders),
        "active": sum(order.status in active_statuses for order in orders),
        "spent": sum(
            (order.grand_total for order in orders if order.status not in {
                Order.Status.CANCELED,
                Order.Status.EXPIRED,
                Order.Status.REFUNDED,
            }),
            start=0,
        ),
        "chats": len(conversations),
    }
    return render(
        request,
        "accounts/profile.html",
        {
            "orders": orders,
            "conversations": conversations[:20],
            "stats": stats,
            "payment_methods": Payment.Method,
            "saved": request.GET.get("salvo") == "1",
        },
    )


@login_required
@require_http_methods(["GET", "POST"])
@sensitive_post_parameters("password")
def delete_account_page(request):
    """Exclusão de conta com confirmação de senha (LGPD)."""
    error = ""
    blocked = account_has_open_orders(request.user)
    if request.method == "POST":
        if blocked:
            error = (
                "Há pedidos em andamento. Conclua ou cancele antes de excluir a conta."
            )
        elif request.POST.get("confirm_delete") != "EXCLUIR":
            error = 'Digite EXCLUIR no campo de confirmação para continuar.'
        else:
            try:
                delete_user_account(
                    request.user,
                    password=request.POST.get("password", ""),
                    request=request,
                )
                return redirect("stores:home")
            except AccountDeletionError as exc:
                error = str(exc)
    return render(
        request,
        "accounts/delete_account.html",
        {"error": error, "blocked": blocked},
    )

class AgeVerificationRequestView(APIView):
    """POST /api/verificacao-idade/ — dispara a checagem biométrica no provider (idwall/unico/CAF)."""

    permission_classes = [IsAuthenticated]
    throttle_scope = "checkout"

    def post(self, request):
        from .services import is_configured

        if request.user.is_age_verified:
            return Response({"detail": "Já verificado."})
        if not is_configured():
            return Response(
                {
                    "detail": (
                        "A verificação por biometria ainda não está ativa nesta instalação. "
                        "Configure AGE_KYC_API_URL e AGE_KYC_API_KEY."
                    )
                },
                status=status.HTTP_503_SERVICE_UNAVAILABLE,
            )

        serializer = AgeVerificationRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        try:
            verification = request_age_verification(
                user=request.user,
                selfie_video_ref=serializer.validated_data["selfie_video_ref"],
                cpf=request.user.cpf,
                birth_date=request.user.birth_date,
            )
        except AgeVerificationError as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_502_BAD_GATEWAY)

        return Response({"status": verification.status}, status=status.HTTP_202_ACCEPTED)


@csrf_exempt
def age_verification_webhook(request):
    """Callback do provider de KYC com o resultado da checagem de idade/biometria."""
    if request.method != "POST":
        return JsonResponse({"detail": "method not allowed"}, status=405)

    # Sem chave configurada o endpoint fica FECHADO. Comparar com "" faria
    # hmac.compare_digest("", "") == True e deixaria qualquer um aprovar a
    # verificacao de idade de qualquer conta.
    expected = (getattr(settings, "AGE_KYC_API_KEY", "") or "").strip()
    if not expected:
        return JsonResponse({"detail": "webhook de KYC não configurado"}, status=503)

    token = request.headers.get("X-Kyc-Webhook-Token", "")
    if not hmac.compare_digest(token, expected):
        return HttpResponseForbidden("Token inválido.")

    if len(request.body) > 64 * 1024:
        return JsonResponse({"detail": "payload muito grande"}, status=413)
    try:
        payload = json.loads(request.body or b"{}")
        reference_id = str(payload["reference_id"]).strip()
        approved = payload["approved"]
        if not reference_id or not isinstance(approved, bool):
            raise ValueError
        apply_verification_result(
            reference_id=reference_id,
            approved=approved,
            liveness_score=payload.get("liveness_score"),
            document_validated=bool(payload.get("document_validated", False)),
            validated_birth_date=payload.get("birth_date"),
        )
    except (json.JSONDecodeError, KeyError, TypeError, ValueError):
        return JsonResponse({"detail": "payload inválido"}, status=400)
    return JsonResponse({"received": True})


class PhoneVerificationRequestView(APIView):
    """POST /api/telefone/solicitar/ — valida titularidade da linha no CPF e dispara o SMS com OTP."""

    permission_classes = [IsAuthenticated]
    throttle_scope = "phone"

    def post(self, request):
        from .phone import PhoneVerificationError, start_phone_verification

        if request.user.is_phone_verified:
            return Response({"detail": "Telefone já verificado."})
        try:
            start_phone_verification(request.user, request.data.get("phone_number", ""))
        except PhoneVerificationError as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST)
        return Response({"status": "code_sent"}, status=status.HTTP_202_ACCEPTED)


class PhoneVerificationConfirmView(APIView):
    """POST /api/telefone/confirmar/ — confere o OTP recebido por SMS."""

    permission_classes = [IsAuthenticated]
    throttle_scope = "phone"

    def post(self, request):
        from .phone import PhoneVerificationError, confirm_phone_verification

        try:
            confirm_phone_verification(request.user, request.data.get("code", ""))
        except PhoneVerificationError as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST)
        return Response({"status": "verified"})


class SellerKYCSubmitView(APIView):
    """
    POST /api/vendedora/kyc/ — documento frente/verso + selfie com o
    código da conta carimbado na foto + termo de maioridade e cessão.

    NÃO exige idade já verificada: é este envio que produz a verificação.
    A conferência é humana (admin), e é lá que a data de nascimento do
    documento vira a idade oficial da conta.
    """

    permission_classes = [IsAuthenticated]
    parser_classes = [parsers.MultiPartParser]
    throttle_scope = "checkout"

    def post(self, request):
        if request.user.is_banned:
            return Response({"detail": "Conta suspensa."}, status=status.HTTP_403_FORBIDDEN)
        serializer = SellerKYCSerializer(data=request.data, context={"request": request})
        serializer.is_valid(raise_exception=True)
        kyc = serializer.save()
        return Response({"status": kyc.status}, status=status.HTTP_202_ACCEPTED)
