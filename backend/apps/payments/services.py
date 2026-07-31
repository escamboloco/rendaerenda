"""
Camada de integracao com a Instituicao de Pagamento (PSP). O principio
de arquitetura aqui e o que resolve o problema juridico descrito em
docs/BASE_JURIDICA.md: A PLATAFORMA NUNCA CUSTODIA DINHEIRO. Quem
recebe, retem e libera o dinheiro e o PSP (Asaas ou Iugu), atraves de:

  1. Uma subconta por vendedora (criada no onboarding da loja).
  2. Split automatico configurado por cobranca: X% cai direto na
     subconta da vendedora, o resto na conta master da plataforma.
  3. Saque via Pix feito pela propria vendedora dentro da conta dela
     no PSP (nos so espelhamos o saldo aqui - ver apps.wallet).

Regra "pagamento so pelo CPF do titular": toda cobranca e criada em um
customer do PSP amarrado ao CPF da conta (get_or_create por cpfCnpj);
no cartao o Asaas valida titularidade, e no Pix o CPF de quem pagou
chega no webhook/consulta - qualquer divergencia gera estorno
automatico (ver apps.payments.views.asaas_webhook + verify_payer_cpf).

Trocar de provider = trocar a classe usada em `get_payment_provider()`.
Nao ha dependencia direta de Asaas/Iugu fora deste arquivo.
"""
from __future__ import annotations

import re
from abc import ABC, abstractmethod
from dataclasses import dataclass
from decimal import Decimal

import requests
from django.conf import settings


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
    Requer conta Asaas aprovada por escrito para o nicho (vestuario
    intimo usado entre particulares - NAO conteudo adulto digital).
    Docs: https://docs.asaas.com/docs/split-de-pagamentos
    """

    BILLING_TYPES = {"pix": "PIX", "credit_card": "CREDIT_CARD", "debit_card": "DEBIT_CARD", "boleto": "BOLETO"}

    def __init__(self, api_key: str | None = None):
        self.base_url = getattr(settings, "ASAAS_API_URL", "") or "https://api.asaas.com/v3"
        self.api_key = api_key or getattr(settings, "ASAAS_API_KEY", "")

    def _headers(self):
        return {"access_token": self.api_key, "Content-Type": "application/json"}

    def _get_or_create_customer(self, *, cpf: str, name: str, email: str) -> str:
        """
        Um customer Asaas por CPF da conta. E o que amarra TODA cobranca ao
        titular: cartao de credito com CPF de titular diferente do customer
        e recusado pelo proprio PSP quando `creditCardHolderInfo.cpfCnpj`
        diverge, e o Pix e conferido por nos no webhook.
        """
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
        Cria subconta Asaas da vendedora. Guardamos o walletId (nao o
        account id): e o walletId que o endpoint de split exige.
        Docs: https://docs.asaas.com/docs/split-de-pagamentos
        """
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
        # Split: parte da vendedora (item + frete). O restante liquido
        # (comissao 30% - taxas Asaas) fica AUTOMATICO na conta master.
        _ = platform_amount
        customer_id = self._get_or_create_customer(cpf=customer_cpf, name=customer_name, email=customer_email)
        resp = requests.post(
            f"{self.base_url}/payments",
            headers=self._headers(),
            json={
                "customer": customer_id,
                "billingType": self.BILLING_TYPES[method],
                "value": float(total_amount),
                "externalReference": order_id,
                "split": [
                    {
                        "walletId": seller_subaccount_id,
                        "fixedValue": float(seller_amount),
                    }
                ],
            },
            timeout=15,
        )
        resp.raise_for_status()
        data = resp.json()
        return ChargeResult(
            provider_charge_id=data["id"],
            payment_url=data.get("invoiceUrl"),
            pix_qr_code=data.get("pixQrCode"),
        )

    def request_seller_withdrawal(
        self,
        *,
        seller_subaccount_id: str,
        amount: Decimal,
        pix_key: str,
        pix_key_type: str = "CPF",
        api_key: str | None = None,
    ) -> str:
        # Preferir apiKey da subconta (saque do saldo dela). Fallback: conta master.
        headers = {"access_token": api_key or self.api_key, "Content-Type": "application/json"}
        key_type = (pix_key_type or detect_pix_key_type(pix_key)).upper()
        payload = {
            "value": float(amount),
            "pixAddressKey": pix_key,
            "pixAddressKeyType": key_type,
        }
        # Com apiKey da subconta o saque e da propria carteira; sem ela,
        # tentamos via walletId na conta master (nem sempre suportado).
        if not api_key:
            payload["walletId"] = seller_subaccount_id
        resp = requests.post(
            f"{self.base_url}/transfers",
            headers=headers,
            json=payload,
            timeout=15,
        )
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
                "externalReference": reference_id,
            },
            timeout=15,
        )
        resp.raise_for_status()
        data = resp.json()
        return ChargeResult(
            provider_charge_id=data["id"],
            payment_url=data.get("invoiceUrl"),
            pix_qr_code=data.get("pixQrCode"),
        )

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
