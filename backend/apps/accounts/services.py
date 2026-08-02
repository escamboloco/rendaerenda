"""
Integracao com provider de verificacao de idade/KYC documental
(idwall, unico, CAF...). Nunca aceitar 'tenho 18+' como prova - sempre
CPF + data de nascimento validados em base oficial + prova de vida
facial (biometria), conforme Lei 15.211/2025.

Este modulo e um cliente fino; a chamada real ao provider deve ser
feita de forma assincrona (Celery) porque a checagem biometrica tem
latencia.
"""
from __future__ import annotations

import requests
from django.conf import settings

from .models import AgeVerification, User


class AgeVerificationError(Exception):
    pass


def is_configured() -> bool:
    """True quando existe provider contratado (URL + chave)."""
    return bool(
        (getattr(settings, "AGE_KYC_API_URL", "") or "").strip()
        and (getattr(settings, "AGE_KYC_API_KEY", "") or "").strip()
    )


def request_age_verification(user: User, selfie_video_ref: str, cpf: str, birth_date) -> AgeVerification:
    """
    Dispara a verificacao no provider externo. Retorna o registro em
    status PENDING - a aprovacao chega via webhook (ver views.age_verification_webhook).

    A URL vem de AGE_KYC_API_URL: cada bureau (idwall, unico, CAF, Serpro)
    tem endpoint e formato proprios, entao o endereco nunca e adivinhado a
    partir do nome do provider. Sem contrato configurado, levanta erro em
    vez de bater num host inexistente.
    """
    if not is_configured():
        raise AgeVerificationError(
            "Verificação de idade indisponível: o provider de biometria ainda não está configurado."
        )

    verification, _ = AgeVerification.objects.get_or_create(
        user=user,
        defaults={"provider": settings.AGE_KYC_PROVIDER},
    )

    try:
        response = requests.post(
            settings.AGE_KYC_API_URL,
            headers={"Authorization": f"Bearer {settings.AGE_KYC_API_KEY}"},
            json={
                "external_id": str(user.id),
                "cpf": cpf,
                "birth_date": birth_date.isoformat(),
                "selfie_video_ref": selfie_video_ref,
            },
            timeout=(5, 20),
        )
    except requests.RequestException as exc:
        raise AgeVerificationError("Não foi possível falar com o serviço de verificação.") from exc

    if response.status_code >= 400:
        # Nunca logar o corpo: pode conter CPF e dado biometrico.
        raise AgeVerificationError(f"Falha ao iniciar verificacao: HTTP {response.status_code}")

    try:
        payload = response.json()
        reference_id = payload["reference_id"]
    except (ValueError, KeyError) as exc:
        raise AgeVerificationError("Resposta inesperada do serviço de verificação.") from exc

    verification.provider_reference_id = reference_id
    verification.save(update_fields=["provider_reference_id"])
    return verification


def apply_verification_result(
    reference_id: str,
    approved: bool,
    liveness_score,
    document_validated: bool,
    validated_birth_date=None,
):
    """
    Chamado pelo webhook do provider. So aqui setamos is_age_verified=True -
    nunca em outro ponto do codigo (ver apps.accounts.models.User).

    A idade oficial vem de validated_birth_date (data registrada na base
    do CPF, retornada pelo provider) - NUNCA da data digitada no cadastro.
    Mesmo que o provider aprove a biometria, sem data validada >= 18 anos
    o resultado aqui e REJECTED (fail closed, Lei 15.211/2025).
    """
    import datetime

    from django.utils import timezone

    verification = AgeVerification.objects.select_related("user").get(provider_reference_id=reference_id)

    if isinstance(validated_birth_date, str):
        validated_birth_date = datetime.date.fromisoformat(validated_birth_date)
    verification.validated_birth_date = validated_birth_date
    verification.liveness_score = liveness_score
    verification.document_validated = document_validated

    is_adult = verification.validated_age is not None and verification.validated_age >= 18
    final_approved = bool(approved and document_validated and is_adult)
    verification.status = (
        AgeVerification.Status.APPROVED if final_approved else AgeVerification.Status.REJECTED
    )
    verification.reviewed_at = timezone.now()
    verification.save(
        update_fields=["status", "liveness_score", "document_validated", "validated_birth_date", "reviewed_at"]
    )

    user = verification.user
    user.is_age_verified = final_approved
    # Menor de idade confirmado em base oficial tentando entrar: banimento
    # por CPF imediato (docs/BASE_JURIDICA.md secao 3, linha vermelha 1).
    if verification.validated_age is not None and verification.validated_age < 18:
        user.ban("Menor de idade confirmado na verificação oficial de CPF.")
    else:
        user.save(update_fields=["is_age_verified"])
    return verification
