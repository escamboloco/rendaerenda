import hmac
import json

from django.conf import settings
from django.contrib.auth.decorators import login_required
from django.http import HttpResponseForbidden, JsonResponse
from django.shortcuts import render
from django.views.decorators.csrf import csrf_exempt
from rest_framework import parsers, status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from .serializers import AgeVerificationRequestSerializer, SellerKYCSerializer
from .services import AgeVerificationError, apply_verification_result, request_age_verification


@login_required
def verification_page(request):
    verification = getattr(request.user, "age_verification", None)
    return render(request, "accounts/verification.html", {"verification": verification})


@login_required
def seller_kyc_page(request):
    kyc = getattr(request.user, "seller_kyc", None)
    return render(request, "accounts/seller_kyc.html", {"kyc": kyc})


@login_required
def phone_page(request):
    verification = getattr(request.user, "phone_verification", None)
    return render(request, "accounts/phone.html", {"verification": verification})


@login_required
def profile_page(request):
    """Perfil minimo: apelido de interacao + status das verificacoes."""
    if request.method == "POST":
        alias = request.POST.get("public_alias", "").strip()[:40]
        request.user.public_alias = alias
        request.user.save(update_fields=["public_alias"])
        return render(request, "accounts/profile.html", {"saved": True})
    return render(request, "accounts/profile.html")


class AgeVerificationRequestView(APIView):
    """POST /api/verificacao-idade/ — dispara a checagem biométrica no provider (idwall/unico/CAF)."""

    permission_classes = [IsAuthenticated]
    throttle_scope = "checkout"

    def post(self, request):
        if request.user.is_age_verified:
            return Response({"detail": "Já verificado."})

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

    token = request.headers.get("X-Kyc-Webhook-Token", "")
    if not hmac.compare_digest(token, settings.AGE_KYC_API_KEY):
        return HttpResponseForbidden("Token inválido.")

    payload = json.loads(request.body)
    apply_verification_result(
        reference_id=payload["reference_id"],
        approved=payload["approved"],
        liveness_score=payload.get("liveness_score"),
        document_validated=payload.get("document_validated", False),
        validated_birth_date=payload.get("birth_date"),
    )
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
    """POST /api/vendedora/kyc/ — documento frente/verso + selfie + termo de maioridade e cessão de imagem."""

    permission_classes = [IsAuthenticated]
    parser_classes = [parsers.MultiPartParser]
    throttle_scope = "checkout"

    def post(self, request):
        if not request.user.is_age_verified:
            return Response(
                {"detail": "Verificação de idade precisa estar aprovada antes do KYC de vendedora."},
                status=status.HTTP_403_FORBIDDEN,
            )
        serializer = SellerKYCSerializer(data=request.data, context={"request": request})
        serializer.is_valid(raise_exception=True)
        kyc = serializer.save()
        return Response({"status": kyc.status}, status=status.HTTP_202_ACCEPTED)
