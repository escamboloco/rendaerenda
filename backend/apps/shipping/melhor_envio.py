"""
Integracao com o Melhor Envio (https://docs.melhorenvio.com.br) - o
"gateway de frete" usado por lojas que vendem em Shopee/Mercado Livre
por fora. O que ele resolve pra gente:

  - Cotacao simultanea em Correios + transportadoras privadas (Jadlog,
    Loggi, Buslog...) numa chamada so.
  - Compra da etiqueta via API: a PLATAFORMA compra a etiqueta com o
    valor de frete que o comprador pagou, e a vendedora so imprime o
    PDF e cola na embalagem - e o "sistema automatizado do papel de
    colar na encomenda".
  - +14.000 pontos de postagem parceiros (agencias Jadlog, Loggi Ponto
    etc.) - endpoint de agencias devolve o ponto mais proximo do CEP
    da vendedora.
  - Rastreio unificado via API/webhook independente da transportadora.

Sandbox: conta separada em sandbox.melhorenvio.com.br com saldo fake -
setar MELHOR_ENVIO_SANDBOX=True em dev.
"""
from __future__ import annotations

from dataclasses import dataclass

import requests
from django.conf import settings


class MelhorEnvioError(Exception):
    pass


@dataclass
class BoughtLabel:
    order_id: str
    tracking_code: str
    label_url: str


def _base_url() -> str:
    if settings.MELHOR_ENVIO_SANDBOX:
        return "https://sandbox.melhorenvio.com.br"
    return "https://melhorenvio.com.br"


def _headers() -> dict:
    return {
        "Authorization": f"Bearer {settings.MELHOR_ENVIO_TOKEN}",
        "Accept": "application/json",
        "Content-Type": "application/json",
        # Exigido pela API - identifica a aplicacao integradora.
        "User-Agent": f"{settings.SITE_NAME} (suporte@{settings.SITE_DOMAIN})",
    }


def calculate(
    *, origin_cep: str, destination_cep: str, weight_grams: int,
    length_cm: int, width_cm: int, height_cm: int, declared_value,
) -> list[dict]:
    """POST /api/v2/me/shipment/calculate — cotacao em todas as transportadoras de uma vez."""
    resp = requests.post(
        f"{_base_url()}/api/v2/me/shipment/calculate",
        headers=_headers(),
        json={
            "from": {"postal_code": origin_cep},
            "to": {"postal_code": destination_cep},
            "package": {
                "weight": max(weight_grams, 50) / 1000,  # kg
                "length": length_cm,
                "width": width_cm,
                "height": height_cm,
            },
            "options": {"insurance_value": float(declared_value), "receipt": False, "own_hand": False},
        },
        timeout=20,
    )
    if resp.status_code >= 400:
        raise MelhorEnvioError(f"Falha na cotação: {resp.status_code}")
    # Transportadoras sem cobertura vem com "error" no item - filtrar.
    return [option for option in resp.json() if "error" not in option]


def buy_label(
    *, service_id: int, origin_cep: str, destination_cep: str,
    seller_name: str, seller_document: str,
    buyer_name: str, buyer_document: str, shipping_address: dict,
    weight_grams: int, length_cm: int, width_cm: int, height_cm: int,
    declared_value, order_reference: str,
) -> BoughtLabel:
    """
    Fluxo completo carrinho -> checkout -> generate -> print. Devolve o
    codigo de rastreio e a URL do PDF da etiqueta pronta pra imprimir.
    """
    cart_resp = requests.post(
        f"{_base_url()}/api/v2/me/cart",
        headers=_headers(),
        json={
            "service": service_id,
            "from": {
                "name": seller_name,
                "document": seller_document,
                "postal_code": origin_cep,
            },
            "to": {
                "name": buyer_name,
                "document": buyer_document,
                "postal_code": shipping_address.get("cep", destination_cep),
                "address": shipping_address.get("street", ""),
                "number": shipping_address.get("number", ""),
                "district": shipping_address.get("neighborhood", ""),
                "city": shipping_address.get("city", ""),
                "state_abbr": shipping_address.get("state", ""),
            },
            "volumes": [
                {
                    "weight": max(weight_grams, 50) / 1000,
                    "length": length_cm,
                    "width": width_cm,
                    "height": height_cm,
                }
            ],
            "options": {
                "insurance_value": float(declared_value),
                "receipt": False,
                "own_hand": False,
                "reverse": False,
                "non_commercial": True,  # venda entre pessoas fisicas, sem NF-e de mercadoria
                "tags": [{"tag": order_reference}],
            },
        },
        timeout=20,
    )
    if cart_resp.status_code >= 400:
        raise MelhorEnvioError(f"Falha ao adicionar ao carrinho: {cart_resp.status_code} {cart_resp.text[:200]}")
    me_order_id = cart_resp.json()["id"]

    checkout_resp = requests.post(
        f"{_base_url()}/api/v2/me/shipment/checkout",
        headers=_headers(),
        json={"orders": [me_order_id]},
        timeout=30,
    )
    if checkout_resp.status_code >= 400:
        raise MelhorEnvioError(f"Falha no checkout da etiqueta: {checkout_resp.status_code}")

    generate_resp = requests.post(
        f"{_base_url()}/api/v2/me/shipment/generate",
        headers=_headers(),
        json={"orders": [me_order_id]},
        timeout=30,
    )
    if generate_resp.status_code >= 400:
        raise MelhorEnvioError(f"Falha ao gerar etiqueta: {generate_resp.status_code}")

    print_resp = requests.post(
        f"{_base_url()}/api/v2/me/shipment/print",
        headers=_headers(),
        json={"mode": "private", "orders": [me_order_id]},
        timeout=30,
    )
    if print_resp.status_code >= 400:
        raise MelhorEnvioError(f"Falha ao imprimir etiqueta: {print_resp.status_code}")
    label_url = print_resp.json().get("url", "")

    detail_resp = requests.get(
        f"{_base_url()}/api/v2/me/orders/{me_order_id}",
        headers=_headers(),
        timeout=20,
    )
    tracking = ""
    if detail_resp.status_code < 400:
        tracking = detail_resp.json().get("tracking") or ""

    return BoughtLabel(order_id=me_order_id, tracking_code=tracking, label_url=label_url)


def track(me_order_id: str) -> dict:
    resp = requests.get(
        f"{_base_url()}/api/v2/me/orders/{me_order_id}",
        headers=_headers(),
        timeout=20,
    )
    if resp.status_code >= 400:
        raise MelhorEnvioError(f"Falha no rastreio: {resp.status_code}")
    return resp.json()


def find_dropoff_points(*, cep: str, company_id: int | None = None) -> list[dict]:
    """
    GET /api/v2/me/shipment/agencies — agencias/pontos de postagem
    (Jadlog, Loggi Ponto...) proximos ao CEP da vendedora. E aqui que
    mostramos "o ponto mais proximo" pra ela levar a encomenda.
    """
    params = {"postal_code": cep}
    if company_id:
        params["company"] = company_id
    resp = requests.get(
        f"{_base_url()}/api/v2/me/shipment/agencies",
        headers=_headers(),
        params=params,
        timeout=20,
    )
    if resp.status_code >= 400:
        raise MelhorEnvioError(f"Falha ao buscar pontos de coleta: {resp.status_code}")
    return resp.json()
