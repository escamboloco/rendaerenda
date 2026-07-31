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


@dataclass
class ChargeResult:
    provider_charge_id: str
    payment_url: str | None
    pix_qr_code: str | None


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
    def request_seller_withdrawal(self, *, seller_subaccount_id: str, amount: Decimal, pix_key: str) -> str: ...

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


def _digits(value: str | None) -> str:
    return re.sub(r"\D", "", value or "")


class AsaasProvider(PaymentProvider):
    """
    Requer conta Asaas aprovada por escrito para o nicho (vestuario
    intimo usado entre particulares - NAO conteudo adulto digital).
    Docs: https://docs.asaas.com/docs/split-de-pagamentos
    """

    BILLING_TYPES = {"pix": "PIX", "credit_card": "CREDIT_CARD", "debit_card": "DEBIT_CARD", "boleto": "BOLETO"}

    def __init__(self):
        self.base_url = settings.ASAAS_API_URL if hasattr(settings, "ASAAS_API_URL") else "https://api.asaas.com/v3"
        self.api_key = getattr(settings, "ASAAS_API_KEY", "")

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
        return SubaccountResult(provider_subaccount_id=wallet_id, pix_key=None)

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
        # Split: so a parte da vendedora vai no array. O restante liquido
        # (comissao + frete/embalagem - taxas Asaas) fica AUTOMATICO na
        # conta master da plataforma - nao se inclui o proprio walletId.
        # platform_amount e calculado no Order e usado so no ledger interno.
        _ = platform_amount
        customer_id = self._get_or_create_customer(cpf=customer_cpf, name=customer_name, email=customer_email)
        resp = requests.post(
            f"{self.base_url}/payments",
            headers=self._headers(),
            json={
                "customer": customer_id,
                "billingType": self.BILLING_TYPES[method],
                "value": str(total_amount),
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

    def request_seller_withdrawal(self, *, seller_subaccount_id: str, amount: Decimal, pix_key: str) -> str:
        resp = requests.post(
            f"{self.base_url}/transfers",
            headers=self._headers(),
            json={
                "walletId": seller_subaccount_id,
                "value": str(amount),
                "pixAddressKey": pix_key,
                "pixAddressKeyType": "CPF",  # saque exclusivamente para chave Pix do CPF da vendedora
            },
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
                "value": str(amount),
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
    Confere se quem pagou e o titular da conta (Order.buyer.cpf). Cartao ja
    e travado pelo customer do PSP; aqui cobrimos principalmente Pix pago
    de banco de terceiro. CPF divergente -> estorno automatico. Se o PSP
    nao informar o documento do pagador, seguimos (matched=None) - o
    customer da cobranca ja e o do titular.
    """
    provider = get_payment_provider()
    payer_doc = provider.get_payer_document(
        provider_charge_id=payment.provider_charge_id, webhook_payload=webhook_payload
    )
    if not payer_doc:
        payment.payer_document = ""
        payment.payer_cpf_matched = None
        return True

    payment.payer_document = payer_doc
    payment.payer_cpf_matched = payer_doc == payment.order.buyer.cpf
    if payment.payer_cpf_matched:
        return True

    provider.refund_charge(provider_charge_id=payment.provider_charge_id)
    return False
