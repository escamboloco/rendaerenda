"""Fabricas simples para os testes (sem dependencia de factory_boy)."""
import itertools
from datetime import date
from decimal import Decimal

from django.contrib.auth import get_user_model

from apps.catalog.models import Category, Product
from apps.payments.services import ChargeResult
from apps.stores.models import Store

User = get_user_model()

# CPFs validos (digitos verificadores corretos) usados nos testes.
CPF_SELLER = "39053344705"
CPF_BUYER = "11144477735"
CPF_OTHER = "52998224725"


_sequence = itertools.count(1)


def _next() -> int:
    return next(_sequence)


def _fake_cpf(seed: int) -> str:
    """CPF sintetico com digitos verificadores validos."""
    base = f"{seed:09d}"
    for _ in range(2):
        weight = len(base) + 1
        total = sum(int(digit) * (weight - i) for i, digit in enumerate(base))
        base += str((total * 10) % 11 % 10)
    return base


def make_user(*, email=None, cpf=None, role="seller", **extra):
    index = _next()
    email = email or f"vendedora{index}@example.com"
    return User.objects.create_user(
        username=email,
        email=email,
        password="senha-bem-forte-123",
        cpf=cpf or _fake_cpf(index),
        birth_date=date(1995, 5, 20),
        role=role,
        **extra,
    )


def make_store(owner=None, *, slug=None, pix_key=CPF_SELLER, **extra):
    owner = owner or make_user()
    return Store.objects.create(
        owner=owner,
        slug=slug or f"loja-teste-{_next()}",
        display_name="Loja Teste",
        status=Store.Status.ACTIVE,
        pix_key=pix_key,
        pix_key_type="CPF",
        origin_cep="01310100",
        origin_street="Avenida Paulista",
        origin_number="1000",
        origin_district="Bela Vista",
        origin_city="São Paulo",
        origin_state="SP",
        **extra,
    )


def make_product(store=None, *, payout=Decimal("100.00"), stock=1, slug="calcinha-renda", **extra):
    store = store or make_store()
    category, _ = Category.objects.get_or_create(name="Calcinhas", defaults={"slug": "calcinhas"})
    return Product.objects.create(
        store=store,
        category=category,
        title="Calcinha de renda",
        slug=slug,
        description="Item de teste.",
        payout_amount=payout,
        weight_grams=150,
        stock=stock,
        status=Product.Status.PUBLISHED,
        **extra,
    )


def checkout_payload(product, *, quantity=1, cpf=CPF_BUYER):
    return {
        "items": [{"product_id": str(product.id), "quantity": quantity}],
        "shipping_address": {
            "cep": "01310-100",
            "street": "Av. Paulista",
            "number": "1000",
            "neighborhood": "Bela Vista",
            "city": "São Paulo",
            "state": "SP",
        },
        "payment_method": "pix",
        "guest_name": "Maria da Silva",
        "guest_email": "maria@example.com",
        "guest_cpf": cpf,
        "guest_birth_date": "1990-01-01",
    }


class FakeProvider:
    """
    Dublê do Asaas. Registra as chamadas para os testes conferirem que o
    repasse não sai duas vezes para o mesmo pedido.
    """

    def __init__(self, *, paid=False, payer_document=None, fail_charge=False):
        self.paid = paid
        self.payer_document = payer_document
        self.fail_charge = fail_charge
        self.charges = []
        self.withdrawals = []
        self.refunds = []

    def create_split_charge(self, **kwargs):
        if self.fail_charge:
            from apps.payments.asaas import AsaasError

            raise AsaasError("Cobrança recusada pelo Asaas.")
        self.charges.append(kwargs)
        return ChargeResult(
            provider_charge_id=f"pay_{len(self.charges)}",
            payment_url="https://asaas.test/i/pay_1",
            pix_qr_code="data:image/png;base64,AAAA",
            pix_copy_paste="00020126BR.GOV.BCB.PIX",
            status="RECEIVED" if self.paid else "PENDING",
            is_paid=self.paid,
        )

    def create_charge(self, **kwargs):
        return self.create_split_charge(**kwargs)

    def get_charge(self, provider_charge_id):
        return ChargeResult(
            provider_charge_id=provider_charge_id,
            payment_url="https://asaas.test/i/pay_1",
            pix_qr_code="data:image/png;base64,AAAA",
            pix_copy_paste="00020126BR.GOV.BCB.PIX",
            status="RECEIVED" if self.paid else "PENDING",
            is_paid=self.paid,
        )

    def get_payer_document(self, *, provider_charge_id, webhook_payload=None):
        return self.payer_document

    def refund_charge(self, *, provider_charge_id):
        self.refunds.append(provider_charge_id)

    def request_seller_withdrawal(self, **kwargs):
        self.withdrawals.append(kwargs)
        return f"transfer_{len(self.withdrawals)}"

    def create_seller_subaccount(self, **kwargs):
        from apps.payments.services import SubaccountResult

        return SubaccountResult(provider_subaccount_id="", pix_key=None, api_key="")
