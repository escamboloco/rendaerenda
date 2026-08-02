"""
Regra de negocio da integracao com a Instituicao de Pagamento (PSP).

Dois modos (settings.ASAAS_ACCOUNT_TYPE):

  pf — Conta pessoa fisica. Sem subconta/split (bloqueado pelo Bacen).
       Cobra 100% na conta da plataforma; na confirmacao repassa a parte
       da vendedora via Pix (POST /transfers).

  pj — Conta CNPJ. Subconta por vendedora + split na propria cobranca.

O HTTP cru fica em apps/payments/asaas.py. Aqui so tem a traducao entre o
dominio (pedido, vendedora, comissao) e o PSP.
"""
from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import date
from decimal import Decimal

from django.conf import settings
from django.utils import timezone

from .asaas import AsaasClient, AsaasError, digits, payer_document_from_webhook

logger = logging.getLogger(__name__)

# Mantido publico: varios modulos ja importam `_digits` deste arquivo.
_digits = digits

BILLING_TYPES = {
    "pix": "PIX",
    "credit_card": "CREDIT_CARD",
    "debit_card": "DEBIT_CARD",
    "boleto": "BOLETO",
}


def asaas_uses_split() -> bool:
    """True so com conta PJ (subcontas + split nativo)."""
    return getattr(settings, "ASAAS_ACCOUNT_TYPE", "pf") == "pj"


def payment_is_configured() -> bool:
    return bool((getattr(settings, "ASAAS_API_KEY", "") or "").strip())


@dataclass
class SubaccountResult:
    provider_subaccount_id: str
    pix_key: str | None
    api_key: str | None = None


@dataclass
class ChargeResult:
    provider_charge_id: str
    payment_url: str | None
    pix_qr_code: str | None
    pix_copy_paste: str | None = None
    status: str = "PENDING"
    is_paid: bool = False
    pix_expires_at: str | None = None
    value: Decimal | None = None


def detect_pix_key_type(pix_key: str) -> str:
    """Infere o tipo da chave Pix pro Asaas (CPF/CNPJ/EMAIL/PHONE/EVP)."""
    key = (pix_key or "").strip()
    if "@" in key:
        return "EMAIL"
    if "-" in key and len(key) >= 32:
        return "EVP"
    numeric = digits(key)
    if len(numeric) == 14:
        return "CNPJ"
    if len(numeric) == 11:
        # 11 digitos e ambiguo (CPF x celular com DDD). Chave de telefone no
        # Asaas so e aceita no formato internacional, entao exigimos o "+"
        # para tratar como PHONE; o resto e CPF, que e o caso comum.
        return "PHONE" if key.startswith("+") else "CPF"
    if len(numeric) in (10, 12, 13):
        return "PHONE"
    return "EVP"


def age_from_birth_date(birth_date: date) -> int:
    today = timezone.localdate()
    return today.year - birth_date.year - (
        (today.month, today.day) < (birth_date.month, birth_date.day)
    )


def is_adult(birth_date: date) -> bool:
    return age_from_birth_date(birth_date) >= 18


# Alias historico usado em apps.payments.views.
_adult_from_birth = is_adult


class PaymentProvider(ABC):
    @abstractmethod
    def create_seller_subaccount(self, *, seller_name: str, cpf: str, email: str) -> SubaccountResult: ...

    @abstractmethod
    def create_split_charge(
        self,
        *,
        order_id: str,
        method: str,
        total_amount: Decimal,
        seller_subaccount_id: str,
        seller_amount: Decimal,
        platform_amount: Decimal,
        customer_cpf: str,
        customer_name: str,
        customer_email: str,
        return_url: str = "",
    ) -> ChargeResult: ...

    @abstractmethod
    def request_seller_withdrawal(
        self,
        *,
        seller_subaccount_id: str,
        amount: Decimal,
        pix_key: str,
        pix_key_type: str = "CPF",
        api_key: str | None = None,
        reference: str = "",
    ) -> str: ...

    @abstractmethod
    def create_charge(
        self, *, reference_id: str, method: str, amount: Decimal,
        customer_cpf: str, customer_name: str = "", customer_email: str = "",
    ) -> ChargeResult:
        """Cobranca 100% para a plataforma, sem split (plano de loja, boost, assinatura)."""
        ...

    @abstractmethod
    def get_charge(self, provider_charge_id: str) -> ChargeResult:
        """Estado atual da cobranca no PSP — base do polling e da reconciliacao."""
        ...

    @abstractmethod
    def get_payer_document(self, *, provider_charge_id: str, webhook_payload: dict | None = None) -> str | None:
        """CPF/CNPJ de quem efetivamente pagou (Pix). None se o PSP nao informou."""
        ...

    @abstractmethod
    def refund_charge(self, *, provider_charge_id: str) -> None: ...

    def cancel_unpaid_charge(self, *, provider_charge_id: str) -> None:
        """Cancela cobrança pendente. Default: noop (provider específico pode sobrescrever)."""
        return None


class AsaasProvider(PaymentProvider):
    """
    Conta Asaas (PF ou PJ). Nicho declarado ao PSP: vestuario intimo usado
    entre pessoas fisicas — NAO conteudo adulto digital. Manter o aceite
    por escrito (docs/BASE_JURIDICA.md secao 5).
    """

    def __init__(self, api_key: str | None = None):
        self.client = AsaasClient(api_key=api_key)

    # ------------------------------------------------------------ subcontas

    def create_seller_subaccount(self, *, seller_name: str, cpf: str, email: str) -> SubaccountResult:
        if not asaas_uses_split():
            # Bacen nao permite subconta em conta pessoa fisica.
            logger.info("Asaas PF: subconta ignorada para a loja de %s", email or "vendedora")
            return SubaccountResult(provider_subaccount_id="", pix_key=None, api_key="")

        data = self.client.create_account(name=seller_name, cpf_cnpj=cpf, email=email)
        return SubaccountResult(
            provider_subaccount_id=data.get("walletId") or data["id"],
            pix_key=None,
            api_key=data.get("apiKey") or "",
        )

    # ------------------------------------------------------------- cobrancas

    def create_split_charge(
        self,
        *,
        order_id: str,
        method: str,
        total_amount: Decimal,
        seller_subaccount_id: str,
        seller_amount: Decimal,
        platform_amount: Decimal,
        customer_cpf: str,
        customer_name: str,
        customer_email: str,
        return_url: str = "",
    ) -> ChargeResult:
        customer_id = self.client.get_or_create_customer(
            cpf_cnpj=customer_cpf, name=customer_name, email=customer_email
        )
        split = None
        description = f"Pedido {order_id}"
        if asaas_uses_split() and seller_subaccount_id:
            split = [{"walletId": seller_subaccount_id, "fixedValue": float(seller_amount)}]
        else:
            # Sem split: registra o valor devido a vendedora na descricao
            # (rastro de auditoria no extrato do Asaas).
            description = f"Pedido {order_id} | repasse vendedora R$ {seller_amount}"

        payment = self.client.create_payment(
            customer_id=customer_id,
            billing_type=BILLING_TYPES[method],
            value=total_amount,
            external_reference=str(order_id),
            description=description,
            split=split,
            return_url=return_url,
        )
        return _charge_result(payment)

    def create_charge(
        self, *, reference_id: str, method: str, amount: Decimal,
        customer_cpf: str, customer_name: str = "", customer_email: str = "",
    ) -> ChargeResult:
        customer_id = self.client.get_or_create_customer(
            cpf_cnpj=customer_cpf, name=customer_name, email=customer_email
        )
        payment = self.client.create_payment(
            customer_id=customer_id,
            billing_type=BILLING_TYPES[method],
            value=amount,
            external_reference=reference_id,
        )
        return _charge_result(payment)

    def get_charge(self, provider_charge_id: str) -> ChargeResult:
        payment = self.client.get_payment(provider_charge_id)
        if not payment.pix_copy_paste and not payment.is_paid:
            self.client.attach_pix(payment)
        return _charge_result(payment)

    def get_payer_document(self, *, provider_charge_id: str, webhook_payload: dict | None = None) -> str | None:
        if webhook_payload:
            doc = payer_document_from_webhook(webhook_payload)
            if doc:
                return doc
        return self.client.get_payer_document(provider_charge_id) or None

    def refund_charge(self, *, provider_charge_id: str) -> None:
        self.client.refund_payment(provider_charge_id)

    def cancel_unpaid_charge(self, *, provider_charge_id: str) -> None:
        try:
            self.client.delete_payment(provider_charge_id)
        except AsaasError as exc:
            # Já paga/estornada: a confirmação/refund trata o restante.
            logger.info(
                "Não foi possível cancelar a cobrança %s: %s",
                provider_charge_id,
                exc.user_message,
            )

    # ------------------------------------------------------------- repasses

    def request_seller_withdrawal(
        self,
        *,
        seller_subaccount_id: str,
        amount: Decimal,
        pix_key: str,
        pix_key_type: str = "CPF",
        api_key: str | None = None,
        reference: str = "",
    ) -> str:
        key_type = (pix_key_type or detect_pix_key_type(pix_key)).upper()
        use_subaccount_key = bool(asaas_uses_split() and api_key)
        data = self.client.transfer_pix(
            value=amount,
            pix_key=pix_key,
            pix_key_type=key_type,
            description="Repasse de venda",
            api_key=api_key if use_subaccount_key else None,
            wallet_id=(
                seller_subaccount_id
                if asaas_uses_split() and seller_subaccount_id and not use_subaccount_key
                else None
            ),
            external_reference=reference or None,
        )
        return data["id"]


def _charge_result(payment) -> ChargeResult:
    return ChargeResult(
        provider_charge_id=payment.id,
        payment_url=payment.invoice_url,
        pix_qr_code=payment.pix_qr_code_image,
        pix_copy_paste=payment.pix_copy_paste,
        status=payment.status,
        is_paid=payment.is_paid,
        pix_expires_at=payment.pix_expires_at,
        value=getattr(payment, "value", None),
    )


def get_payment_provider() -> PaymentProvider:
    if settings.PAYMENT_PROVIDER == "asaas":
        return AsaasProvider()
    raise NotImplementedError(f"Provider {settings.PAYMENT_PROVIDER} não implementado ainda (ex.: Iugu).")


def verify_payer_cpf(payment, webhook_payload: dict | None = None) -> bool:
    """
    Confere se quem pagou e o titular do pedido (comprador logado ou guest).

    E uma trava de idade, nao de fraude: o CPF do pagador e a unica prova
    de que um adulto identificado esta comprando (docs/BASE_JURIDICA.md).
    CPF divergente -> estorno automatico, se
    settings.REFUND_ON_PAYER_CPF_MISMATCH estiver ligado.

    Retorna False quando o pagamento foi (ou deveria ter sido) estornado
    por CPF divergente. Sem documento do pagador, com REQUIRE_PAYER_DOCUMENT
    ativo, o produto fica retido (não libera).
    """
    provider = get_payment_provider()
    try:
        payer_doc = provider.get_payer_document(
            provider_charge_id=payment.provider_charge_id, webhook_payload=webhook_payload
        )
    except AsaasError:
        logger.warning("Nao foi possivel consultar o pagador da cobranca %s", payment.provider_charge_id)
        payer_doc = None

    if not payer_doc:
        payment.payer_document = ""
        payment.payer_cpf_matched = None
        if getattr(settings, "REQUIRE_PAYER_DOCUMENT", True):
            raise AsaasError(
                "Pagamento recebido, aguardando identificação segura do pagador."
            )
        return True

    expected = digits(payment.order.payer_cpf)
    payment.payer_document = payer_doc[:14]
    payment.payer_cpf_matched = bool(expected) and payer_doc == expected
    if payment.payer_cpf_matched:
        return True

    logger.warning(
        "Pedido %s pago por CPF divergente do titular — acionando politica de estorno.",
        payment.order_id,
    )
    if not getattr(settings, "REFUND_ON_PAYER_CPF_MISMATCH", True):
        return True
    try:
        provider.refund_charge(provider_charge_id=payment.provider_charge_id)
    except AsaasError:
        logger.exception("Falha ao estornar a cobranca %s do pedido %s", payment.provider_charge_id, payment.order_id)
    return False
