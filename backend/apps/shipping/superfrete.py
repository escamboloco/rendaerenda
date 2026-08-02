"""
Cliente da API SuperFrete.

Fluxo oficial: cotação -> criação da etiqueta pendente -> pagamento com saldo
-> consulta da etiqueta liberada. Nenhum payload é logado porque contém
endereço, CPF e outros dados pessoais.
"""
from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Any

import requests
from django.conf import settings


class SuperFreteError(Exception):
    pass


class SuperFreteConfigurationError(SuperFreteError):
    pass


@dataclass(frozen=True)
class BoughtLabel:
    order_id: str
    tracking_code: str
    label_url: str


def _base_url() -> str:
    return (
        "https://sandbox.superfrete.com"
        if settings.SUPERFRETE_SANDBOX
        else "https://api.superfrete.com"
    )


def _headers() -> dict[str, str]:
    token = (settings.SUPERFRETE_TOKEN or "").strip()
    if not token:
        raise SuperFreteConfigurationError("SUPERFRETE_TOKEN não configurado.")
    return {
        "Authorization": f"Bearer {token}",
        "Accept": "application/json",
        "Content-Type": "application/json",
        "User-Agent": settings.SUPERFRETE_USER_AGENT,
    }


def _request(method: str, path: str, *, timeout: int = 30, **kwargs) -> requests.Response:
    try:
        response = requests.request(
            method,
            f"{_base_url()}{path}",
            headers=_headers(),
            timeout=timeout,
            **kwargs,
        )
    except requests.RequestException as exc:
        raise SuperFreteError("SuperFrete indisponível no momento.") from exc
    if response.status_code >= 400:
        raise SuperFreteError(
            f"SuperFrete recusou a operação ({response.status_code})."
        )
    return response


def calculate(
    *,
    origin_cep: str,
    destination_cep: str,
    weight_grams: int,
    length_cm: int,
    width_cm: int,
    height_cm: int,
    declared_value,
) -> list[dict[str, Any]]:
    """POST /api/v0/calculator."""
    services = (settings.SUPERFRETE_SERVICES or "1,2,17,3").strip()
    response = _request(
        "POST",
        "/api/v0/calculator",
        timeout=20,
        json={
            "from": {"postal_code": _digits(origin_cep)},
            "to": {"postal_code": _digits(destination_cep)},
            "services": services,
            "options": {
                "own_hand": False,
                "receipt": False,
                "insurance_value": float(declared_value or 0),
                "use_insurance_value": bool(declared_value),
            },
            "package": {
                "weight": max(weight_grams, 50) / 1000,
                "length": max(length_cm, 1),
                "width": max(width_cm, 1),
                "height": max(height_cm, 1),
            },
        },
    )
    data = _json(response)
    if not isinstance(data, list):
        raise SuperFreteError("Resposta inválida na cotação da SuperFrete.")
    return [option for option in data if isinstance(option, dict) and not option.get("error")]


def create_label(
    *,
    service_id: int,
    sender: dict,
    recipient: dict,
    products: list[dict],
    weight_grams: int,
    length_cm: int,
    width_cm: int,
    height_cm: int,
    declared_value,
    order_reference: str,
) -> str:
    """POST /api/v0/cart; cria uma etiqueta pendente de pagamento."""
    from_payload = _address_payload(sender, recipient=False)
    to_payload = _address_payload(recipient, recipient=True)
    if not products:
        raise SuperFreteConfigurationError("Etiqueta sem declaração de conteúdo.")

    response = _request(
        "POST",
        "/api/v0/cart",
        json={
            "from": from_payload,
            "to": to_payload,
            "service": int(service_id),
            "products": [
                {
                    "name": str(item.get("name") or "Vestuário usado")[:50],
                    "quantity": max(int(item.get("quantity") or 1), 1),
                    "unitary_value": float(
                        Decimal(str(item.get("unitary_value") or "0"))
                    ),
                }
                for item in products
            ],
            "volumes": {
                "weight": max(weight_grams, 50) / 1000,
                "length": max(length_cm, 1),
                "width": max(width_cm, 1),
                "height": max(height_cm, 1),
            },
            "options": {
                "insurance_value": float(declared_value or 0),
                "receipt": False,
                "own_hand": False,
                "non_commercial": True,
            },
            "tag": order_reference[:50],
            "url": f"https://{settings.SITE_DOMAIN}",
            "platform": settings.SITE_NAME,
        },
    )
    data = _json(response)
    order_id = str(data.get("id") or "")
    if not order_id:
        raise SuperFreteError("SuperFrete não retornou o ID da etiqueta.")
    return order_id


def finalize_label(order_id: str) -> BoughtLabel:
    """
    Paga uma etiqueta com o saldo SuperFrete e retorna PDF/rastreio.

    Consulta primeiro: se um retry ocorrer depois do pagamento, não tenta
    finalizar novamente a mesma etiqueta.
    """
    detail = track(order_id)
    if detail.get("status") == "pending":
        _request(
            "POST",
            "/api/v1/orders/finalize",
            json={"id": order_id},
        )
        detail = track(order_id)

    label_url = str((detail.get("print") or {}).get("url") or "")
    if not label_url:
        raise SuperFreteError("SuperFrete não retornou o PDF da etiqueta liberada.")
    return BoughtLabel(
        order_id=order_id,
        tracking_code=str(detail.get("tracking") or ""),
        label_url=label_url,
    )


def track(order_id: str) -> dict[str, Any]:
    """GET /api/v0/order/info/{id}."""
    response = _request("GET", f"/api/v0/order/info/{order_id}", timeout=20)
    data = _json(response)
    if not isinstance(data, dict):
        raise SuperFreteError("Resposta inválida no rastreio da SuperFrete.")
    return data


def _address_payload(address: dict, *, recipient: bool) -> dict[str, Any]:
    required = {
        "name": address.get("name"),
        "address": address.get("address"),
        "district": address.get("district"),
        "city": address.get("city"),
        "state_abbr": address.get("state_abbr"),
        "postal_code": _digits(address.get("postal_code", "")),
    }
    missing = [field for field, value in required.items() if not value]
    if missing:
        kind = "destinatário" if recipient else "remetente"
        raise SuperFreteConfigurationError(
            f"Endereço do {kind} incompleto: {', '.join(missing)}."
        )

    payload: dict[str, Any] = {
        "name": _full_name(str(required["name"]))[:50],
        "address": str(required["address"])[:50],
        "complement": str(address.get("complement") or "")[:20],
        "number": str(address.get("number") or "")[:10],
        "district": str(required["district"])[:50],
        "city": str(required["city"])[:50],
        "state_abbr": str(required["state_abbr"]).upper()[:2],
        "postal_code": required["postal_code"],
    }
    document = _digits(address.get("document", ""))
    if document:
        payload["document"] = document
    email = str(address.get("email") or "").strip()
    if email:
        payload["email"] = email
    phone = _digits(address.get("phone", ""))
    if phone:
        payload["phone"] = phone
    return payload


def _full_name(value: str) -> str:
    value = " ".join(value.split())
    return value if " " in value else f"Loja {value}"


def _digits(value: Any) -> str:
    return "".join(character for character in str(value or "") if character.isdigit())


def _json(response: requests.Response) -> Any:
    try:
        return response.json()
    except ValueError as exc:
        raise SuperFreteError("SuperFrete retornou uma resposta inválida.") from exc
