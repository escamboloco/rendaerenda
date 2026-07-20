"""
Emissao de NFS-e (nota fiscal de servico) da PLATAFORMA via provider
(padrao: Focus NFe - https://focusnfe.com.br/doc/#nfse). Importante
entender O QUE a plataforma pode legalmente notafiscalizar:

  - A plataforma NAO vende o item - a venda e da vendedora (pessoa
    fisica), direto ao comprador (docs/BASE_JURIDICA.md secao 1). Por
    isso NUNCA emitimos NF do item.
  - A plataforma presta SERVICO de intermediacao/assinatura. E sobre
    isso que a NFS-e e emitida: comissao do pedido, assinatura do
    comprador, plano de loja e boost.

A discricao da fatura vale aqui tambem: a descricao do servico e neutra
("intermediacao de anuncios classificados"), sem mencao ao nicho.
"""
from __future__ import annotations

from dataclasses import dataclass

import requests
from django.conf import settings


class InvoiceProviderError(Exception):
    pass


@dataclass
class IssuedInvoice:
    provider_invoice_id: str
    pdf_url: str


def issue_service_invoice(
    *, reference_id: str, recipient_name: str, recipient_cpf: str,
    recipient_email: str, amount, description: str,
) -> IssuedInvoice:
    api_url = settings.NFSE_PROVIDER_URL
    api_key = settings.NFSE_PROVIDER_API_KEY
    if not api_url or not api_key:
        if settings.DEBUG:
            # Em dev, "emite" uma NF fake para o fluxo completo ser testavel.
            return IssuedInvoice(provider_invoice_id=f"dev-{reference_id}", pdf_url="")
        raise InvoiceProviderError("Provider de NFS-e não configurado.")

    resp = requests.post(
        f"{api_url}?ref={reference_id}",
        auth=(api_key, ""),  # Focus NFe usa basic auth com token no user
        json={
            "prestador": {
                "cnpj": settings.PLATFORM_CNPJ,
                "codigo_municipio": None,  # inferido do cadastro no provider
            },
            "tomador": {
                "cpf": recipient_cpf,
                "razao_social": recipient_name,
                "email": recipient_email,
            },
            "servico": {
                "valor_servicos": str(amount),
                "item_lista_servico": settings.PLATFORM_MUNICIPAL_SERVICE_CODE,
                # Descricao NEUTRA de proposito - cobranca discreta.
                "discriminacao": description,
            },
        },
        timeout=30,
    )
    if resp.status_code >= 400:
        raise InvoiceProviderError(f"Falha na emissão da NFS-e: {resp.status_code}")
    data = resp.json()
    return IssuedInvoice(
        provider_invoice_id=data.get("ref", reference_id),
        pdf_url=data.get("url_danfse", data.get("caminho_danfse", "")),
    )
