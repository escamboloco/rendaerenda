"""
Custo da embalagem neutra, embutido no frete cobrado do comprador.

Por que existe: a vendedora precisa comprar uma caixa/envelope sem
identificação para postar. Se esse custo não entra no frete, ela paga do
próprio bolso e a "embalagem discreta" vira prejuízo dela.

O valor entra no frete, é repassado junto com ele assim que o pagamento
confirma, e por isso ela consegue postar sem tirar dinheiro do bolso.

ATENÇÃO AOS PREÇOS: a tabela abaixo é um ponto de partida, NÃO uma
cotação oficial dos Correios. Preço de caixa/envelope muda por região,
loja e reajuste anual. Confira os valores atuais e sobrescreva com
NEUTRAL_BOX_PRICES no ambiente antes de vender de verdade — cobrar a
menos sai do bolso da vendedora, cobrar a mais afasta comprador.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from decimal import Decimal

from django.conf import settings

# (chave, rotulo, peso maximo em gramas, soma maxima de dimensoes em cm)
BOX_SPECS = [
    ("envelope", "Envelope de segurança neutro", 300, 70),
    ("p", "Caixa neutra P", 1000, 90),
    ("m", "Caixa neutra M", 3000, 120),
    ("g", "Caixa neutra G", 10000, 160),
]

# Preços de referência (R$). Sobrescreva via NEUTRAL_BOX_PRICES.
DEFAULT_PRICES = {
    "envelope": "2.50",
    "p": "4.50",
    "m": "7.00",
    "g": "11.00",
}


@dataclass(frozen=True)
class NeutralBox:
    key: str
    label: str
    price: Decimal


def _price_table() -> dict:
    """Tabela efetiva: padrão do código sobrescrito pelo ambiente."""
    raw = getattr(settings, "NEUTRAL_BOX_PRICES", "") or ""
    prices = dict(DEFAULT_PRICES)
    if raw:
        try:
            prices.update(json.loads(raw) if isinstance(raw, str) else dict(raw))
        except (ValueError, TypeError):
            pass
    return prices


def neutral_box_for(*, weight_grams: int, length_cm: int, width_cm: int, height_cm: int) -> NeutralBox:
    """
    Escolhe a menor embalagem neutra que comporta o pedido.

    Acima da maior faixa, devolve a maior mesmo assim: é melhor cobrar a
    embalagem grande do que devolver zero e a vendedora descobrir o custo
    só na hora de postar.
    """
    prices = _price_table()
    dimensions_sum = int(length_cm) + int(width_cm) + int(height_cm)
    weight = max(int(weight_grams), 0)

    for key, label, max_weight, max_dimensions in BOX_SPECS:
        if weight <= max_weight and dimensions_sum <= max_dimensions:
            return NeutralBox(key=key, label=label, price=_as_money(prices.get(key)))

    key, label, _, _ = BOX_SPECS[-1]
    return NeutralBox(key=key, label=label, price=_as_money(prices.get(key)))


def _as_money(value) -> Decimal:
    try:
        return Decimal(str(value)).quantize(Decimal("0.01"))
    except Exception:
        return Decimal("0.00")
