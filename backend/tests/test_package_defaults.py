"""Cotação de frete como envelope pequeno (calcinha média)."""
from django.test import SimpleTestCase

from apps.shipping.package_defaults import (
    DEFAULT_HEIGHT_CM,
    DEFAULT_LENGTH_CM,
    DEFAULT_WEIGHT_GRAMS,
    DEFAULT_WIDTH_CM,
    cheapest_option,
    quote_package,
)
from apps.shipping.services import FreightOption


class _FakeProduct:
    def __init__(self, *, id="1", weight_grams=0, length_cm=30, width_cm=20, height_cm=10):
        self.id = id
        self.weight_grams = weight_grams
        self.length_cm = length_cm
        self.width_cm = width_cm
        self.height_cm = height_cm


class PackageDefaultsTests(SimpleTestCase):
    def test_missing_weight_uses_panty_average(self):
        weight, length, width, height = quote_package([_FakeProduct()])
        self.assertEqual(weight, DEFAULT_WEIGHT_GRAMS)
        self.assertEqual((length, width, height), (DEFAULT_LENGTH_CM, DEFAULT_WIDTH_CM, DEFAULT_HEIGHT_CM))

    def test_light_item_normalizes_to_envelope_even_with_large_dims(self):
        product = _FakeProduct(weight_grams=80, length_cm=40, width_cm=30, height_cm=20)
        weight, length, width, height = quote_package([product])
        self.assertEqual(weight, 80)
        self.assertEqual((length, width, height), (16, 11, 2))

    def test_cheapest_option_wins(self):
        options = [
            FreightOption(service="sf-1", label="PAC", price=22.0, deadline_days=5),
            FreightOption(service="sf-17", label="Mini", price=12.5, deadline_days=7),
            FreightOption(service="sf-2", label="SEDEX", price=35.0, deadline_days=2),
        ]
        chosen = cheapest_option(options)
        self.assertEqual(chosen.service, "sf-17")
        self.assertEqual(chosen.price, 12.5)

    def test_quantity_stacks_envelope_height(self):
        product = _FakeProduct(id="a", weight_grams=70)
        weight, _, _, height = quote_package([product], {"a": 3})
        self.assertEqual(weight, 210)
        self.assertEqual(height, 6)  # 2cm * 3, teto do envelope
