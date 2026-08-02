"""
Dimensões e peso padrão para cotação de frete no nicho (lingerie).

A maioria dos envios é uma calcinha/peça pequena em envelope de segurança.
Usar caixa grande ou peso alto na cotação deixa o frete artificialmente caro.
"""
from __future__ import annotations

# Peso médio de uma calcinha + envelope leve.
DEFAULT_WEIGHT_GRAMS = 80
DEFAULT_LENGTH_CM = 16
DEFAULT_WIDTH_CM = 11
DEFAULT_HEIGHT_CM = 2

# Abaixo deste peso total, a cotação usa dims de envelope (não de caixa).
ENVELOPE_MAX_WEIGHT_GRAMS = 500


def quote_package(products, quantities: dict | None = None) -> tuple[int, int, int, int]:
    """
    Retorna (peso_g, comprimento_cm, largura_cm, altura_cm) para cotar frete.

    Peso vem do anúncio (fallback: calcinha média). Dimensões de peças leves
    são normalizadas para envelope pequeno — evita cotação de caixa por
    altura/largura mal preenchida no cadastro.
    """
    quantities = quantities or {}
    weight = 0
    units = 0
    for product in products:
        qty = max(int(quantities.get(str(product.id), 1)), 1)
        units += qty
        per_unit = int(getattr(product, "weight_grams", 0) or 0) or DEFAULT_WEIGHT_GRAMS
        weight += per_unit * qty

    if weight <= 0:
        weight = DEFAULT_WEIGHT_GRAMS

    if weight <= ENVELOPE_MAX_WEIGHT_GRAMS:
        # Empilha só a altura do envelope por unidade (teto prático do nicho).
        height = min(DEFAULT_HEIGHT_CM * max(units, 1), 6)
        return weight, DEFAULT_LENGTH_CM, DEFAULT_WIDTH_CM, height

    length = max((int(p.length_cm or DEFAULT_LENGTH_CM) for p in products), default=DEFAULT_LENGTH_CM)
    width = max((int(p.width_cm or DEFAULT_WIDTH_CM) for p in products), default=DEFAULT_WIDTH_CM)
    height = sum(
        int(p.height_cm or DEFAULT_HEIGHT_CM) * max(int(quantities.get(str(p.id), 1)), 1)
        for p in products
    )
    return weight, max(length, 1), max(width, 1), max(height, 1)


def cheapest_option(options):
    """Escolhe a opção de menor preço (Mini Envios etc. quando disponível)."""
    if not options:
        return None
    return min(options, key=lambda o: (float(o.price), int(o.deadline_days or 99)))
