"""
Cliente HTTP do Asaas — camada mais baixa da integracao de pagamento.

Aqui nao existe regra de negocio: so requisicao, timeout, retry, log sem
dado sensivel e traducao de erro do Asaas para uma excecao com mensagem
em portugues que pode ser mostrada ao usuario (AsaasError.user_message).

A regra de negocio (quem recebe o que, quando o pedido vira pago) fica em
apps/payments/services.py e apps/payments/checkout.py.

Docs: https://docs.asaas.com/reference
"""
from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from datetime import timedelta
from decimal import Decimal

import requests
from django.conf import settings
from django.utils import timezone

logger = logging.getLogger(__name__)

# Timeout (conectar, ler). O checkout do comprador espera essa resposta —
# nao pode pendurar o worker do gunicorn.
DEFAULT_TIMEOUT = (5, 20)

# Status do Asaas que significam "dinheiro entrou".
PAID_STATUSES = frozenset({"RECEIVED", "CONFIRMED", "RECEIVED_IN_CASH"})
# Status que significam "essa cobranca nao vai mais ser paga".
DEAD_STATUSES = frozenset({"REFUNDED", "REFUND_REQUESTED", "CHARGEBACK_REQUESTED", "DELETED"})

GENERIC_ERROR = "Não foi possível falar com o sistema de pagamento agora. Tente de novo em instantes."


class AsaasError(Exception):
    """Erro do Asaas ja traduzido para mensagem exibivel."""

    def __init__(self, user_message: str, *, status_code: int | None = None, payload=None):
        super().__init__(user_message)
        self.user_message = user_message
        self.status_code = status_code
        self.payload = payload


def digits(value: str | None) -> str:
    return re.sub(r"\D", "", value or "")


@dataclass
class AsaasPayment:
    """Resposta normalizada de uma cobranca."""

    id: str
    status: str
    value: Decimal
    invoice_url: str | None = None
    pix_qr_code_image: str | None = None
    pix_copy_paste: str | None = None
    pix_expires_at: str | None = None
    payer_document: str = ""
    raw: dict = field(default_factory=dict)

    @property
    def is_paid(self) -> bool:
        return self.status in PAID_STATUSES

    @property
    def is_dead(self) -> bool:
        return self.status in DEAD_STATUSES


class AsaasClient:
    def __init__(self, api_key: str | None = None, base_url: str | None = None):
        self.api_key = (api_key if api_key is not None else getattr(settings, "ASAAS_API_KEY", "")) or ""
        self.base_url = (base_url or getattr(settings, "ASAAS_API_URL", "") or "https://api.asaas.com/v3").rstrip("/")
        self._session = requests.Session()

    # ------------------------------------------------------------------ infra

    @property
    def is_configured(self) -> bool:
        return bool(self.api_key.strip())

    def _headers(self, api_key: str | None = None) -> dict:
        return {
            "access_token": api_key or self.api_key,
            "Content-Type": "application/json",
            "User-Agent": f"{getattr(settings, 'SITE_NAME', 'app')}/1.0",
        }

    @staticmethod
    def _extract_message(response: requests.Response) -> str:
        try:
            data = response.json()
        except ValueError:
            return GENERIC_ERROR
        errors = data.get("errors") if isinstance(data, dict) else None
        if isinstance(errors, list) and errors:
            description = (errors[0] or {}).get("description")
            if description:
                return str(description)
        return GENERIC_ERROR

    def _request(self, method: str, path: str, *, api_key: str | None = None, **kwargs) -> dict:
        if not self.is_configured and not api_key:
            raise AsaasError(
                "Pagamento indisponível: a chave da API do Asaas não está configurada no servidor.",
                status_code=503,
            )
        url = f"{self.base_url}{path}"
        kwargs.setdefault("timeout", DEFAULT_TIMEOUT)
        try:
            response = self._session.request(method, url, headers=self._headers(api_key), **kwargs)
        except requests.Timeout as exc:
            logger.warning("Asaas timeout em %s %s", method, path)
            raise AsaasError("O sistema de pagamento demorou para responder. Tente de novo.") from exc
        except requests.RequestException as exc:
            logger.warning("Asaas falha de conexao em %s %s: %s", method, path, exc.__class__.__name__)
            raise AsaasError(GENERIC_ERROR) from exc

        if response.status_code >= 400:
            message = self._extract_message(response)
            # Nunca logar o corpo inteiro: pode conter CPF/nome do pagador.
            logger.error("Asaas %s %s -> HTTP %s (%s)", method, path, response.status_code, message)
            raise AsaasError(message, status_code=response.status_code)

        if not response.content:
            return {}
        try:
            return response.json()
        except ValueError as exc:
            raise AsaasError(GENERIC_ERROR) from exc

    # -------------------------------------------------------------- customers

    def get_or_create_customer(self, *, cpf_cnpj: str, name: str, email: str) -> str:
        cpf_cnpj = digits(cpf_cnpj)
        found = self._request("GET", "/customers", params={"cpfCnpj": cpf_cnpj, "limit": 1})
        data = found.get("data") or []
        if data:
            return data[0]["id"]
        created = self._request(
            "POST",
            "/customers",
            json={
                "name": (name or "").strip() or f"Cliente {cpf_cnpj[-4:]}",
                "cpfCnpj": cpf_cnpj,
                "email": (email or "").strip() or None,
                "notificationDisabled": True,
            },
        )
        return created["id"]

    # --------------------------------------------------------------- payments

    @staticmethod
    def due_date(days: int | None = None) -> str:
        """
        Asaas exige dueDate em toda cobranca, inclusive Pix. Com dueDate de
        hoje o QR vence a meia-noite — o comprador que abre o checkout as
        23h50 nao consegue pagar. Damos alguns dias de folga.
        """
        if days is None:
            days = int(getattr(settings, "PIX_DUE_DAYS", 3))
        return (timezone.localdate() + timedelta(days=max(days, 0))).isoformat()

    def create_payment(
        self,
        *,
        customer_id: str,
        billing_type: str,
        value: Decimal,
        external_reference: str,
        description: str = "",
        split: list[dict] | None = None,
        due_days: int | None = None,
    ) -> AsaasPayment:
        body: dict = {
            "customer": customer_id,
            "billingType": billing_type,
            "value": float(value),
            "dueDate": self.due_date(due_days),
            "externalReference": external_reference,
        }
        if description:
            body["description"] = description[:500]
        if split:
            body["split"] = split
        data = self._request("POST", "/payments", json=body)
        payment = self._to_payment(data)
        if billing_type == "PIX" and not payment.pix_copy_paste:
            self.attach_pix(payment)
        return payment

    def get_payment(self, payment_id: str) -> AsaasPayment:
        return self._to_payment(self._request("GET", f"/payments/{payment_id}"))

    def attach_pix(self, payment: AsaasPayment) -> AsaasPayment:
        """Busca QR code + copia-e-cola da cobranca (endpoint separado no Asaas)."""
        try:
            data = self._request("GET", f"/payments/{payment.id}/pixQrCode")
        except AsaasError:
            # QR indisponivel nao derruba o checkout: o invoiceUrl do Asaas
            # continua sendo um caminho valido de pagamento.
            logger.warning("Asaas: QR Pix indisponivel para a cobranca %s", payment.id)
            return payment
        encoded = data.get("encodedImage")
        if encoded:
            payment.pix_qr_code_image = f"data:image/png;base64,{encoded}"
        payload = data.get("payload")
        if payload and not str(payload).startswith("data:image"):
            payment.pix_copy_paste = str(payload)
        payment.pix_expires_at = data.get("expirationDate")
        return payment

    def refund_payment(self, payment_id: str, *, value: Decimal | None = None) -> dict:
        body = {"value": float(value)} if value is not None else {}
        return self._request("POST", f"/payments/{payment_id}/refund", json=body)

    def get_payer_document(self, payment_id: str) -> str:
        """CPF/CNPJ de quem efetivamente pagou o Pix (vazio se o Asaas nao informou)."""
        try:
            data = self._request("GET", f"/payments/{payment_id}/pixTransaction")
        except AsaasError:
            return ""
        return _payer_from_pix_transaction(data)

    # -------------------------------------------------------------- transfers

    def transfer_pix(
        self,
        *,
        value: Decimal,
        pix_key: str,
        pix_key_type: str,
        description: str = "",
        api_key: str | None = None,
        wallet_id: str | None = None,
        external_reference: str | None = None,
    ) -> dict:
        body: dict = {
            "value": float(value),
            "pixAddressKey": pix_key,
            "pixAddressKeyType": pix_key_type.upper(),
            "operationType": "PIX",
        }
        if description:
            body["description"] = description[:120]
        if wallet_id:
            body["walletId"] = wallet_id
        if external_reference:
            body["externalReference"] = external_reference
        return self._request("POST", "/transfers", json=body, api_key=api_key)

    # ------------------------------------------------------------- subaccount

    def create_account(self, *, name: str, cpf_cnpj: str, email: str, mobile_phone: str = "") -> dict:
        body = {"name": name, "cpfCnpj": digits(cpf_cnpj), "email": email}
        if mobile_phone:
            body["mobilePhone"] = digits(mobile_phone)
        return self._request("POST", "/accounts", json=body)

    # ---------------------------------------------------------------- helpers

    @staticmethod
    def _to_payment(data: dict) -> AsaasPayment:
        qr = data.get("pixQrCode")
        image = qr if isinstance(qr, str) and qr.startswith("data:image") else None
        copy_paste = data.get("pixCopiaECola") or data.get("payload")
        if isinstance(copy_paste, str) and copy_paste.startswith("data:image"):
            copy_paste = None
        return AsaasPayment(
            id=data["id"],
            status=str(data.get("status") or "PENDING"),
            value=Decimal(str(data.get("value") or "0")),
            invoice_url=data.get("invoiceUrl"),
            pix_qr_code_image=image,
            pix_copy_paste=copy_paste,
            payer_document=_payer_from_payment_payload(data),
            raw=data,
        )


def _payer_from_payment_payload(payment: dict) -> str:
    """CPF/CNPJ do pagador dentro de um payload de cobranca/webhook."""
    if not isinstance(payment, dict):
        return ""
    for key in ("pixTransactionOriginCpfCnpj", "payerCpfCnpj"):
        doc = digits(payment.get(key))
        if doc:
            return doc
    return _payer_from_pix_transaction(payment.get("pixTransaction"))


def _payer_from_pix_transaction(transaction) -> str:
    if not isinstance(transaction, dict):
        return ""
    doc = digits(transaction.get("payerCpfCnpj"))
    if doc:
        return doc
    for key in ("originName", "payer", "originAccount"):
        node = transaction.get(key)
        if isinstance(node, dict):
            doc = digits(node.get("cpfCnpj"))
            if doc:
                return doc
    return ""


def payer_document_from_webhook(payload: dict) -> str:
    """Extrai o CPF do pagador do corpo do webhook, sem chamada extra ao Asaas."""
    if not isinstance(payload, dict):
        return ""
    return _payer_from_payment_payload(payload.get("payment") or {})
