"""Cotação de frete na sacola: resposta com options + frete por peça."""
from decimal import Decimal
from unittest import mock

from django.test import override_settings
from django.urls import reverse

from apps.shipping.services import FreightOption

from .base import ApiTestCase
from .factories import make_product


@override_settings(CHECKOUT_FREE_SHIPPING=False, SUPERFRETE_TOKEN="")
class FreightQuoteApiTests(ApiTestCase):
    def setUp(self):
        super().setUp()
        self.product = make_product(
            payout=Decimal("50.00"),
            freight_declared_value=Decimal("35.00"),
        )
        self.url = reverse("shipping:quote")

    @mock.patch("apps.shipping.views.calculate_freight_options")
    def test_quote_returns_options_and_per_item(self, calculate):
        calculate.return_value = [
            FreightOption(
                service="sf-17",
                label="Mini Envios",
                price=9.9,
                deadline_days=6,
                company="Correios",
            ),
            FreightOption(
                service="sf-1",
                label="PAC",
                price=18.5,
                deadline_days=8,
                company="Correios",
            ),
        ]
        response = self.client.post(
            self.url,
            {
                "destination_cep": "20040020",
                "product_ids": [str(self.product.id)],
                "quantities": {str(self.product.id): 1},
            },
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 200, response.content)
        body = response.json()
        self.assertIn("options", body)
        self.assertEqual(body["options"][0]["service"], "sf-17")
        self.assertEqual(body["options"][0]["price"], 9.9)
        self.assertEqual(len(body["items"]), 1)
        self.assertEqual(body["items"][0]["declared_value"], "35.00")
        self.assertEqual(body["origin_city"], "São Paulo")

        # Valor declarado da vendedora entra na cotação (não o preço cheio).
        declared_args = [call.kwargs.get("declared_value") for call in calculate.call_args_list]
        self.assertTrue(any(float(v) == 35.0 for v in declared_args))
