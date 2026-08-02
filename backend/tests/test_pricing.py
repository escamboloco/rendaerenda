from decimal import Decimal

from django.test import TestCase, override_settings

from apps.catalog.models import payout_from_price, price_from_payout
from apps.payments.serializers import cpf_is_valid
from apps.payments.services import detect_pix_key_type

from .factories import make_product


@override_settings(PLATFORM_COMMISSION_PERCENT=20)
class PricingTests(TestCase):
    def test_price_is_payout_plus_commission(self):
        self.assertEqual(price_from_payout(Decimal("100.00")), Decimal("120.00"))

    def test_payout_is_inverse_of_price(self):
        self.assertEqual(payout_from_price(Decimal("120.00")), Decimal("100.00"))

    def test_product_price_is_always_derived_from_payout(self):
        product = make_product(payout=Decimal("50.00"))
        product.price = Decimal("1.00")  # tentativa de forcar preco no cliente
        product.save()
        product.refresh_from_db()
        self.assertEqual(product.price, Decimal("60.00"))

    def test_seller_never_loses_the_commission(self):
        """A comissao entra POR CIMA: o liquido da vendedora nao muda."""
        product = make_product(payout=Decimal("80.00"))
        self.assertEqual(product.payout_amount, Decimal("80.00"))
        self.assertEqual(product.price - product.payout_amount, Decimal("16.00"))


class CpfValidationTests(TestCase):
    def test_accepts_valid_cpf(self):
        self.assertTrue(cpf_is_valid("111.444.777-35"))

    def test_rejects_wrong_check_digits(self):
        self.assertFalse(cpf_is_valid("11144477736"))

    def test_rejects_repeated_digits(self):
        self.assertFalse(cpf_is_valid("11111111111"))


class PixKeyTypeTests(TestCase):
    def test_email_key(self):
        self.assertEqual(detect_pix_key_type("loja@example.com"), "EMAIL")

    def test_cpf_key(self):
        self.assertEqual(detect_pix_key_type("11144477735"), "CPF")

    def test_cnpj_key(self):
        self.assertEqual(detect_pix_key_type("11222333000181"), "CNPJ")

    def test_international_phone_key(self):
        self.assertEqual(detect_pix_key_type("+5511987654321"), "PHONE")

    def test_random_key(self):
        self.assertEqual(detect_pix_key_type("d3b2f1e4-5a6b-7c8d-9e0f-1a2b3c4d5e6f"), "EVP")
