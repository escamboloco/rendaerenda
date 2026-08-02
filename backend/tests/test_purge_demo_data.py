from datetime import date
from decimal import Decimal
from io import BytesIO

from django.core.files.uploadedfile import SimpleUploadedFile
from django.core.management import call_command
from django.test import TestCase, override_settings
from PIL import Image

from apps.accounts.models import User
from apps.catalog.models import Category, Product
from apps.stores.models import Store


def _jpeg(name: str = "p.jpg") -> SimpleUploadedFile:
    buffer = BytesIO()
    Image.new("RGB", (32, 32), color=(180, 100, 120)).save(buffer, format="JPEG")
    return SimpleUploadedFile(name, buffer.getvalue(), content_type="image/jpeg")


@override_settings(DEBUG=True)
class PurgeDemoAndTestDataTests(TestCase):
    def test_purge_removes_payment_test_store_and_keeps_real_store(self):
        category = Category.objects.create(name="Calcinhas", slug="calcinhas")

        test_seller = User.objects.create_user(
            username="teste_pagamento",
            email="teste.pagamento@rendaerenda.local",
            password="Senha-Forte-123!",
            cpf="39053344705",
            birth_date=date(1992, 5, 10),
        )
        test_store = Store.objects.create(
            owner=test_seller,
            slug="loja-teste-pagamento",
            display_name="Loja Teste Pagamento",
            bio="Loja só para testar checkout/Pix. Itens fictícios a R$ 5.",
            status=Store.Status.ACTIVE,
        )
        Product.objects.create(
            store=test_store,
            category=category,
            title="ITEM TESTE — Calcinha R$ 5",
            slug="teste-pagamento-calcinha",
            description="Produto fictício para teste de pagamento.",
            payout_amount=Decimal("4.00"),
            price=Decimal("5.00"),
            status=Product.Status.PUBLISHED,
            stock=5,
        )

        demo_seller = User.objects.create_user(
            username="luna",
            email="luna@demo.local",
            password="Senha-Forte-123!",
            cpf="11144477735",
            birth_date=date(1990, 1, 1),
        )
        Store.objects.create(
            owner=demo_seller,
            slug="atelie-da-luna",
            display_name="Ateliê da Luna",
            status=Store.Status.ACTIVE,
        )

        real_seller = User.objects.create_user(
            username="real@example.com",
            email="real@example.com",
            password="Senha-Forte-123!",
            cpf="52998224725",
            birth_date=date(1991, 3, 3),
        )
        real_store = Store.objects.create(
            owner=real_seller,
            slug="loja-real",
            display_name="Loja Real",
            status=Store.Status.ACTIVE,
        )
        Product.objects.create(
            store=real_store,
            category=category,
            title="Peça real",
            slug="peca-real",
            description="Anúncio legítimo",
            payout_amount=Decimal("80.00"),
            price=Decimal("100.00"),
            status=Product.Status.PUBLISHED,
            stock=1,
        )

        call_command("purge_demo_and_test_data")

        self.assertFalse(Store.objects.filter(slug="loja-teste-pagamento").exists())
        self.assertFalse(Store.objects.filter(slug="atelie-da-luna").exists())
        self.assertFalse(Product.objects.filter(slug__startswith="teste-pagamento").exists())
        self.assertFalse(User.objects.filter(email__iendswith="@demo.local").exists())
        self.assertFalse(User.objects.filter(username="teste_pagamento").exists())

        self.assertTrue(Store.objects.filter(slug="loja-real").exists())
        self.assertTrue(Product.objects.filter(slug="peca-real").exists())
        self.assertTrue(User.objects.filter(email="real@example.com").exists())

    def test_dry_run_does_not_delete(self):
        seller = User.objects.create_user(
            username="teste_pagamento",
            email="teste.pagamento@rendaerenda.local",
            password="Senha-Forte-123!",
            cpf="39053344705",
            birth_date=date(1992, 5, 10),
        )
        Store.objects.create(
            owner=seller,
            slug="loja-teste-pagamento",
            display_name="Loja Teste Pagamento",
            status=Store.Status.ACTIVE,
        )
        call_command("purge_demo_and_test_data", dry_run=True)
        self.assertTrue(Store.objects.filter(slug="loja-teste-pagamento").exists())
