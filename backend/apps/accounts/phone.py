"""
Verificacao de telefone vinculada ao CPF, em duas etapas:

  1. `check_phone_belongs_to_cpf` - consulta um bureau de dados
     (Serpro Datavalid, idwall, AlliN/telecom score etc.) que confirma
     se a linha movel esta registrada no CPF do titular da conta.
     Nenhuma operadora expoe isso de graca: e um servico contratado,
     igual ao KYC. Sem essa confirmacao o SMS nem e disparado - e isso
     que garante "o CPF cadastrado e o dono do numero que recebe o SMS".
  2. `start_phone_verification` / `confirm_phone_verification` - OTP de
     6 digitos por SMS (provider generico via HTTP, ex.: Zenvia, Twilio,
     AWS SNS). O codigo so existe em claro dentro do SMS; no banco fica
     o hash.

Em DEBUG sem credenciais configuradas, o bureau aprova e o "SMS" vai
para o log - producao sem credencial levanta erro em vez de aprovar
silenciosamente (fail closed).
"""
from __future__ import annotations

import logging
import re
import secrets
from datetime import timedelta

import requests
from django.conf import settings
from django.contrib.auth.hashers import check_password, make_password
from django.utils import timezone

from .models import PhoneVerification, User

logger = logging.getLogger(__name__)

PHONE_RE = re.compile(r"^55\d{10,11}$")  # 55 + DDD + numero (movel com 9 digitos)


class PhoneVerificationError(Exception):
    pass


def normalize_phone(raw: str) -> str:
    digits = re.sub(r"\D", "", raw or "")
    if digits.startswith("0"):
        digits = digits.lstrip("0")
    if not digits.startswith("55"):
        digits = f"55{digits}"
    if not PHONE_RE.match(digits):
        raise PhoneVerificationError("Número de celular inválido. Use DDD + número.")
    return digits


def check_phone_belongs_to_cpf(phone_number: str, cpf: str) -> bool:
    """Bureau: a linha pertence ao titular deste CPF?"""
    api_url = settings.PHONE_CPF_BUREAU_URL
    api_key = settings.PHONE_CPF_BUREAU_API_KEY
    if not api_url or not api_key:
        if settings.DEBUG:
            logger.warning("PHONE_CPF_BUREAU_* não configurado - aprovando em DEBUG (%s).", phone_number[-4:])
            return True
        raise PhoneVerificationError("Serviço de validação de titularidade indisponível.")

    resp = requests.post(
        api_url,
        headers={"Authorization": f"Bearer {api_key}"},
        json={"cpf": cpf, "phone_number": phone_number},
        timeout=15,
    )
    if resp.status_code >= 400:
        raise PhoneVerificationError("Falha ao validar a titularidade do número.")
    return bool(resp.json().get("match"))


def send_sms(phone_number: str, message: str) -> None:
    api_url = settings.SMS_PROVIDER_URL
    api_key = settings.SMS_PROVIDER_API_KEY
    if not api_url or not api_key:
        if settings.DEBUG:
            logger.warning("SMS_PROVIDER_* não configurado - SMS para ...%s: %s", phone_number[-4:], message)
            return
        raise PhoneVerificationError("Serviço de SMS indisponível.")

    resp = requests.post(
        api_url,
        headers={"Authorization": f"Bearer {api_key}"},
        json={"to": phone_number, "message": message},
        timeout=15,
    )
    if resp.status_code >= 400:
        raise PhoneVerificationError("Falha ao enviar o SMS.")


def start_phone_verification(user: User, raw_phone: str) -> PhoneVerification:
    phone = normalize_phone(raw_phone)

    if not check_phone_belongs_to_cpf(phone, user.cpf):
        PhoneVerification.objects.update_or_create(
            user=user,
            defaults={
                "phone_number": phone,
                "otp_hash": "",
                "expires_at": None,
                "attempts": 0,
                "cpf_ownership_match": False,
                "status": PhoneVerification.Status.CPF_MISMATCH,
                "verified_at": None,
            },
        )
        raise PhoneVerificationError(
            "Este número não está registrado no seu CPF. Use um celular cujo titular seja você."
        )

    code = f"{secrets.randbelow(1_000_000):06d}"
    verification, _ = PhoneVerification.objects.update_or_create(
        user=user,
        defaults={
            "phone_number": phone,
            "otp_hash": make_password(code),
            "expires_at": timezone.now() + timedelta(minutes=PhoneVerification.OTP_TTL_MINUTES),
            "attempts": 0,
            "cpf_ownership_match": True,
            "status": PhoneVerification.Status.AWAITING_CODE,
            "verified_at": None,
        },
    )
    # Mensagem discreta: sem nome do site com conteudo, sem contexto adulto.
    send_sms(phone, f"Seu codigo de confirmacao: {code}. Expira em {PhoneVerification.OTP_TTL_MINUTES} minutos.")
    return verification


def confirm_phone_verification(user: User, code: str) -> PhoneVerification:
    verification = getattr(user, "phone_verification", None)
    if not verification or verification.status != PhoneVerification.Status.AWAITING_CODE:
        raise PhoneVerificationError("Nenhuma verificação em andamento. Solicite um novo código.")
    if verification.is_expired():
        raise PhoneVerificationError("Código expirado. Solicite um novo.")
    if verification.attempts >= PhoneVerification.MAX_ATTEMPTS:
        raise PhoneVerificationError("Muitas tentativas. Solicite um novo código.")

    verification.attempts += 1
    if not check_password(code or "", verification.otp_hash):
        verification.save(update_fields=["attempts"])
        raise PhoneVerificationError("Código incorreto.")

    verification.status = PhoneVerification.Status.VERIFIED
    verification.verified_at = timezone.now()
    verification.otp_hash = ""
    verification.save(update_fields=["attempts", "status", "verified_at", "otp_hash"])

    user.phone_number = verification.phone_number
    user.is_phone_verified = True
    user.save(update_fields=["phone_number", "is_phone_verified"])
    return verification
