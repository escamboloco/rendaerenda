"""
Integração com a API oficial dos Correios via CWS (autenticação por
token). Cálculo de frete e rastreio exigem contrato comercial ativo
para os endpoints completos (pré-postagem, rastreio oficial) - ver
docs/correios: https://www.correios.com.br/atendimento/developers
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta

import requests
from django.conf import settings
from django.utils import timezone

from .models import CORREIOS_SERVICE_CODES, Shipment, ShippingQuote, ShippingService

CWS_AUTH_URL = "https://api.correios.com.br/token/v1/autentica/cartaopostagem"
PRICE_API_URL = "https://api.correios.com.br/preco/v1/nacional"
TRACKING_API_URL = "https://api.correios.com.br/srorastro/v1/objetos"


@dataclass
class FreightOption:
    service: str
    label: str
    price: float
    deadline_days: int
    company: str = "Correios"


class CorreiosAuthError(Exception):
    pass


def products_are_payment_test(products) -> bool:
    """Itens do seed_payment_test (slug começa com teste-pagamento)."""
    products = list(products)
    return bool(products) and all(
        getattr(p, "slug", "").startswith("teste-pagamento") for p in products
    )


def test_free_freight_option() -> FreightOption:
    """Frete R$ 0 para fechar cobrança de teste em R$ 5,00."""
    return FreightOption(
        service="pac",
        label="Frete teste (grátis)",
        price=0.0,
        deadline_days=1,
        company="Teste",
    )


def _get_cws_token() -> str:
    resp = requests.post(
        CWS_AUTH_URL,
        auth=(settings.CORREIOS_CWS_USER, settings.CORREIOS_CWS_PASSWORD),
        json={"numero": settings.CORREIOS_CONTRACT_NUMBER, "cartaoPostagem": settings.CORREIOS_CARD_NUMBER},
        timeout=10,
    )
    if resp.status_code != 200:
        raise CorreiosAuthError(f"Falha na autenticação CWS: {resp.status_code}")
    return resp.json()["token"]


def calculate_freight_options(
    destination_cep: str,
    weight_grams: int,
    length_cm: int,
    width_cm: int,
    height_cm: int,
    origin_cep: str = "",
    declared_value=0,
) -> list[FreightOption]:
    """
    Cotação para o checkout, sempre a partir do CEP da REMETENTE
    (Store.origin_cep - fallback no CEP global da plataforma). Com
    SHIPPING_PROVIDER=melhor_envio, cota Correios + transportadoras
    privadas (Jadlog, Loggi...) de uma vez, com pontos de coleta.
    Resultado deve ser cacheado (ShippingQuote) por até 24h.
    """
    origin = origin_cep or settings.CORREIOS_ORIGIN_CEP

    if settings.SHIPPING_PROVIDER == "melhor_envio":
        from . import melhor_envio

        raw_options = melhor_envio.calculate(
            origin_cep=origin,
            destination_cep=destination_cep,
            weight_grams=weight_grams,
            length_cm=length_cm,
            width_cm=width_cm,
            height_cm=height_cm,
            declared_value=declared_value,
        )
        return [
            FreightOption(
                service=f"me-{option['id']}",
                label=f"{option['company']['name']} {option['name']}",
                price=float(option["price"]),
                deadline_days=int(option["delivery_time"]),
                company=option["company"]["name"],
            )
            for option in raw_options
        ]

    token = _get_cws_token()
    options = []
    for service, label in [(ShippingService.PAC, "PAC"), (ShippingService.SEDEX, "SEDEX")]:
        resp = requests.get(
            PRICE_API_URL,
            headers={"Authorization": f"Bearer {token}"},
            params={
                "coProduto": CORREIOS_SERVICE_CODES[service],
                "cepOrigem": origin,
                "cepDestino": destination_cep,
                "peso": max(weight_grams, 100) / 1000,  # kg, mínimo 100g
                "comprimento": length_cm,
                "largura": width_cm,
                "altura": height_cm,
            },
            timeout=15,
        )
        resp.raise_for_status()
        data = resp.json()
        options.append(
            FreightOption(
                service=service,
                label=label,
                price=float(data["precoFinal"]),
                deadline_days=int(data["prazoEntrega"]),
            )
        )
    return options


def save_quote(destination_cep: str, weight_grams: int, option: FreightOption) -> ShippingQuote:
    return ShippingQuote.objects.create(
        origin_cep=settings.CORREIOS_ORIGIN_CEP,
        destination_cep=destination_cep,
        weight_grams=weight_grams,
        service=option.service,
        price=option.price,
        deadline_days=option.deadline_days,
    )


def get_cached_quote(destination_cep: str, weight_grams: int, service: str) -> ShippingQuote | None:
    cutoff = timezone.now() - timedelta(hours=24)
    return (
        ShippingQuote.objects.filter(
            destination_cep=destination_cep,
            weight_grams=weight_grams,
            service=service,
            quoted_at__gte=cutoff,
        )
        .order_by("-quoted_at")
        .first()
    )


def track_shipment(shipment: Shipment) -> dict:
    """Consulta o status atual do objeto (API Rastro - restrita ao contrato do remetente)."""
    token = _get_cws_token()
    resp = requests.get(
        f"{TRACKING_API_URL}/{shipment.tracking_code}",
        headers={"Authorization": f"Bearer {token}"},
        timeout=15,
    )
    resp.raise_for_status()
    data = resp.json()
    latest_event = data["objetos"][0]["eventos"][0]
    shipment.last_tracking_event = latest_event["descricao"]
    shipment.last_tracking_check_at = timezone.now()

    if latest_event.get("codigo") == "BDE":  # objeto entregue
        mark_delivered(shipment)
    else:
        shipment.save()
    return data


def mark_delivered(shipment: Shipment):
    """
    Marca a entrega SEM liberar o saldo: a liberacao acontece quando o
    comprador confirmar o recebimento ou apos a janela de
    DELIVERY_CONFIRMATION_WINDOW_HOURS sem contestacao (Celery beat -
    release_confirmed_deliveries). docs/checkout.md.
    """
    from apps.payments.models import Order

    if shipment.status != Shipment.Status.DELIVERED:
        shipment.status = Shipment.Status.DELIVERED
        shipment.delivered_at = timezone.now()
        shipment.save()
        shipment.order.status = Order.Status.DELIVERED
        shipment.order.save(update_fields=["status"])
