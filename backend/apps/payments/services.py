"""
Camada de integracao com a Instituicao de Pagamento (PSP / Asaas).

Dois modos (settings.ASAAS_ACCOUNT_TYPE):

  pf — Conta pessoa fisica. Sem subconta/split (bloqueado pelo Bacen).
       Cobra 100% na sua conta; no webhook repassa a parte da vendedora
       via Pix (POST /transfers). Voce custodia o valor por alguns
       segundos/minutos ate o Pix sair.

  pj — Conta CNPJ. Subconta por vendedora + split na cobranca (preferido).

Regra CPF do pagador: customer Asaas amarrado ao CPF; Pix divergente
gera estorno (verify_payer_cpf).
"""
from __future__ import annotations

import logging
import re
from abc import ABC, abstractmethod
from dataclasses import dataclass
from decimal import Decimal

import requests
from django.conf import settings
from django.utils import timezone

logger = logging.getLogger(__name__)


def _asaas_due_date() -> str:
    """Asaas exige dueDate (YYYY-MM-DD) em toda cobrança, inclusive Pix."""
    return timezone.localdate().isoformat()


def asaas_uses_split() -> bool:
    """True so com conta PJ (subcontas + split nativo)."""
    return getattr(settings, "ASAAS_ACCOUNT_TYPE", "pf") == "pj"


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


def _digits(value: str | None) -> str:
    return re.sub(r"\D", "", value or "")


def detect_pix_key_type(pix_key: str) -> str:
    """Infere o tipo da chave Pix pro Asaas (CPF/CNPJ/EMAIL/PHONE/EVP)."""
    key = (pix_key or "").strip()
    if "@" in key:
        return "EMAIL"
    digits = _digits(key)
    if len(digits) == 14:
        return "CNPJ"
    if len(digits) == 11:
        # Telefone BR costuma comecar com DDD + 9; CPF e so digitos sem +.
        if key.startswith("+") or key.startswith("55") or (len(key) >= 12 and not key.isdigit()):
            return "PHONE"
        return "CPF"
    if len(digits) == 10 or len(digits) == 12 or len(digits) == 13:
        return "PHONE"
    return "EVP"


def _adult_from_birth(birth_date) -> bool:
    from datetime import date

    today = date.today()
    years = today.year - birth_date.year - (
        (today.month, today.day) < (birth_date.month, birth_date.day)
    )
    return years >= 18


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
    ) -> str: ...

    @abstractmethod
    def create_charge(
        self, *, reference_id: str, method: str, amount: Decimal,
        customer_cpf: str, customer_name: str = "", customer_email: str = "",
    ) -> ChargeResult:
        """Cobranca 100% para a plataforma, sem split (assinatura de compradora, plano de loja, boost)."""
        ...

    @abstractmethod
    def get_payer_document(self, *, provider_charge_id: str, webhook_payload: dict | None = None) -> str | None:
        """CPF/CNPJ de quem efetivamente pagou (Pix). None se o PSP ainda nao informou."""
        ...

    @abstractmethod
    def refund_charge(self, *, provider_charge_id: str) -> None: ...


class AsaasProvider(PaymentProvider):
    """
    Conta Asaas (PF ou PJ). Nicho: vestuario intimo usado entre particulares
    — NAO pornografia. Pedir aceite por escrito.
    """

    BILLING_TYPES = {"pix": "PIX", "credit_card": "CREDIT_CARD", "debit_card": "DEBIT_CARD", "boleto": "BOLETO"}

    def __init__(self, api_key: str | None = None):
        self.base_url = getattr(settings, "ASAAS_API_URL", "") or "https://api.asaas.com/v3"
        self.api_key = api_key or getattr(settings, "ASAAS_API_KEY", "")

    def _headers(self):
        return {"access_token": self.api_key, "Content-Type": "application/json"}

    def _fetch_pix(self, payment_id: str) -> tuple[str | None, str | None]:
        """Retorna (imagem data-URL ou None, copia-e-cola Pix)."""
        resp = requests.get(
            f"{self.base_url}/payments/{payment_id}/pixQrCode",
            headers=self._headers(),
            timeout=15,
        )
        if resp.status_code >= 400:
            return None, None
        data = resp.json()
        encoded = data.get("encodedImage")
        image = f"data:image/png;base64,{encoded}" if encoded else None
        payload = data.get("payload") or data.get("pixCopiaECola") or data.get("pixQrCode")
        if payload and str(payload).startswith("data:image"):
            return payload, None
        return image, payload

    def _charge_result(self, data: dict, method: str) -> ChargeResult:
        payment_id = data["id"]
        qr = data.get("pixQrCode")
        copy_paste = data.get("pixCopiaECola") or data.get("payload")
        if method == "pix" and (not qr or not str(qr).startswith("data:image")):
            image, payload = self._fetch_pix(payment_id)
            if image:
                qr = image
            elif payload and not qr:
                qr = None
            if payload:
                copy_paste = payload
        return ChargeResult(
            provider_charge_id=payment_id,
            payment_url=data.get("invoiceUrl"),
            pix_qr_code=qr if qr and str(qr).startswith("data:image") else (qr if qr and str(qr).startswith("http") else None),
            pix_copy_paste=copy_paste if copy_paste and not str(copy_paste).startswith("data:image") else None,
        )

    def _get_or_create_customer(self, *, cpf: str, name: str, email: str) -> str:
        resp = requests.get(
            f"{self.base_url}/customers",
            headers=self._headers(),
            params={"cpfCnpj": cpf, "limit": 1},
            timeout=15,
        )
        resp.raise_for_status()
        data = resp.json().get("data", [])
        if data:
            return data[0]["id"]

        resp = requests.post(
            f"{self.base_url}/customers",
            headers=self._headers(),
            json={"name": name or f"Cliente {cpf[-4:]}", "cpfCnpj": cpf, "email": email},
            timeout=15,
        )
        resp.raise_for_status()
        return resp.json()["id"]

    def create_seller_subaccount(self, *, seller_name: str, cpf: str, email: str) -> SubaccountResult:
        """
        PJ: cria subconta Asaas (walletId).
        PF: no-op — Bacen nao permite subconta em conta fisica.
        """
        if not asaas_uses_split():
            logger.info("Asaas PF: pulando subconta para %s (%s)", seller_name, cpf[-4:])
            return SubaccountResult(provider_subaccount_id="", pix_key=None, api_key="")

        resp = requests.post(
            f"{self.base_url}/accounts",
            headers=self._headers(),
            json={"name": seller_name, "cpfCnpj": cpf, "email": email, "mobilePhone": ""},
            timeout=15,
        )
        resp.raise_for_status()
        data = resp.json()
        wallet_id = data.get("walletId") or data["id"]
        return SubaccountResult(
            provider_subaccount_id=wallet_id,
            pix_key=None,
            api_key=data.get("apiKey") or "",
        )

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
    ) -> ChargeResult:
        """
        PJ: cobranca com split (seller_amount na wallet da vendedora).
        PF: cobranca integral na sua conta; repasse Pix depois no webhook.
        """
        _ = platform_amount
        customer_id = self._get_or_create_customer(cpf=customer_cpf, name=customer_name, email=customer_email)
        body: dict = {
            "customer": customer_id,
            "billingType": self.BILLING_TYPES[method],
            "value": float(total_amount),
            "dueDate": _asaas_due_date(),
            "externalReference": order_id,
        }
        if asaas_uses_split() and seller_subaccount_id:
            body["split"] = [
                {
                    "walletId": seller_subaccount_id,
                    "fixedValue": float(seller_amount),
                }
            ]
        else:
            # Guarda o valor devido a vendedora na descricao (auditoria).
            body["description"] = f"Pedido {order_id} | repasse vendedora R$ {seller_amount}"

        resp = requests.post(
            f"{self.base_url}/payments",
            headers=self._headers(),
            json=body,
            timeout=15,
        )
        resp.raise_for_status()
        return self._charge_result(resp.json(), method)

    def request_seller_withdrawal(
        self,
        *,
        seller_subaccount_id: str,
        amount: Decimal,
        pix_key: str,
        pix_key_type: str = "CPF",
        api_key: str | None = None,
    ) -> str:
        """
        PJ + apiKey da subconta: saque do saldo dela.
        PF (padrao agora): Pix saindo da SUA conta Asaas para a chave dela.
        """
        key_type = (pix_key_type or detect_pix_key_type(pix_key)).upper()
        payload = {
            "value": float(amount),
            "pixAddressKey": pix_key,
            "pixAddressKeyType": key_type,
            "operationType": "PIX",
        }

        if asaas_uses_split() and api_key:
            headers = {"access_token": api_key, "Content-Type": "application/json"}
        else:
            # Conta PF/master: transferencias Pix saem do saldo da propria conta.
            headers = self._headers()
            if asaas_uses_split() and seller_subaccount_id and not api_key:
                payload["walletId"] = seller_subaccount_id

        resp = requests.post(
            f"{self.base_url}/transfers",
            headers=headers,
            json=payload,
            timeout=15,
        )
        if resp.status_code >= 400:
            logger.error("Asaas transfer falhou: %s %s", resp.status_code, resp.text)
        resp.raise_for_status()
        return resp.json()["id"]

    def create_charge(
        self, *, reference_id: str, method: str, amount: Decimal,
        customer_cpf: str, customer_name: str = "", customer_email: str = "",
    ) -> ChargeResult:
        customer_id = self._get_or_create_customer(cpf=customer_cpf, name=customer_name, email=customer_email)
        resp = requests.post(
            f"{self.base_url}/payments",
            headers=self._headers(),
            json={
                "customer": customer_id,
                "billingType": self.BILLING_TYPES[method],
                "value": float(amount),
                "dueDate": _asaas_due_date(),
                "externalReference": reference_id,
            },
            timeout=15,
        )
        resp.raise_for_status()
        return self._charge_result(resp.json(), method)

    def get_payer_document(self, *, provider_charge_id: str, webhook_payload: dict | None = None) -> str | None:
        # 1) Tenta extrair do proprio payload do webhook (menos uma chamada).
        if webhook_payload:
            payment = webhook_payload.get("payment", {})
            for key in ("pixTransactionOriginCpfCnpj", "payerCpfCnpj"):
                doc = _digits(payment.get(key))
                if doc:
                    return doc
            pix = payment.get("pixTransaction") or {}
            doc = _digits((pix.get("originName") or {}).get("cpfCnpj") if isinstance(pix, dict) else None)
            if doc:
                return doc
        # 2) Consulta a transacao Pix da cobranca no Asaas.
        resp = requests.get(
            f"{self.base_url}/payments/{provider_charge_id}/pixQrCode",
            headers=self._headers(),
            timeout=15,
        )
        if resp.status_code >= 400:
            return None
        return _digits(resp.json().get("payerCpfCnpj")) or None

    def refund_charge(self, *, provider_charge_id: str) -> None:
        resp = requests.post(
            f"{self.base_url}/payments/{provider_charge_id}/refund",
            headers=self._headers(),
            json={},
            timeout=15,
        )
        resp.raise_for_status()


def get_payment_provider() -> PaymentProvider:
    if settings.PAYMENT_PROVIDER == "asaas":
        return AsaasProvider()
    raise NotImplementedError(f"Provider {settings.PAYMENT_PROVIDER} não implementado ainda (ex.: Iugu).")


def verify_payer_cpf(payment, webhook_payload: dict | None) -> bool:
    """
    Confere se quem pagou e o CPF do pedido (buyer ou guest). Cartao ja
    e travado pelo customer do PSP; aqui cobrimos principalmente Pix pago
    de banco de terceiro. CPF divergente -> estorno automatico.
    """
    provider = get_payment_provider()
    payer_doc = provider.get_payer_document(
        provider_charge_id=payment.provider_charge_id, webhook_payload=webhook_payload
    )
    if not payer_doc:
        payment.payer_document = ""
        payment.payer_cpf_matched = None
        return True

    expected = payment.order.payer_cpf
    payment.payer_document = payer_doc
    payment.payer_cpf_matched = payer_doc == expected
    if payment.payer_cpf_matched:
        return True

    provider.refund_charge(provider_charge_id=payment.provider_charge_id)
    return False
