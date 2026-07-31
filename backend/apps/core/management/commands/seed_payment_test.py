"""
Cria loja + produtos de TESTE de pagamento (total do item = R$ 5,00).

Uso local (DEBUG=True):
    python manage.py seed_payment_test

Uso em produção (Render Shell):
    python manage.py seed_payment_test --force --pix-key=SUA_CHAVE_PIX

O checkout desses itens usa frete grátis (serviço pac R$ 0) para o
cobrança no Asaas fechar em exatamente R$ 5,00.
"""
from __future__ import annotations

import datetime
from decimal import Decimal
from io import BytesIO

from django.conf import settings
from django.core.files.base import ContentFile
from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone
from PIL import Image, ImageDraw

from apps.accounts.models import AgeVerification, SellerKYC, User
from apps.catalog.models import Category, Product, ProductImage, payout_from_price
from apps.stores.models import Store

STORE_SLUG = "loja-teste-pagamento"
SELLER_USERNAME = "teste_pagamento"
# CPF válido (apenas dígitos) reservado para esta conta de teste.
SELLER_CPF = "39053344705"
PASSWORD = "teste12345"

PRODUCTS = [
    ("teste-pagamento-calcinha", "Calcinhas", "ITEM TESTE — Calcinha R$ 5"),
    ("teste-pagamento-sutia", "Sutiãs", "ITEM TESTE — Sutiã R$ 5"),
    ("teste-pagamento-meia", "Meias", "ITEM TESTE — Meia R$ 5"),
]


def _placeholder_image(label: str) -> bytes:
    img = Image.new("RGB", (800, 800), (236, 228, 232))
    draw = ImageDraw.Draw(img)
    draw.rectangle([40, 40, 760, 760], outline=(120, 80, 110), width=4)
    draw.text((80, 360), "TESTE R$ 5", fill=(90, 50, 80))
    draw.text((80, 420), label[:40], fill=(90, 50, 80))
    buf = BytesIO()
    img.save(buf, format="JPEG", quality=85)
    return buf.getvalue()


class Command(BaseCommand):
    help = "Cria loja e produtos de teste de pagamento a R$ 5,00."

    def add_arguments(self, parser):
        parser.add_argument(
            "--force",
            action="store_true",
            help="Permite rodar com DEBUG=False (produção).",
        )
        parser.add_argument(
            "--pix-key",
            default="",
            help="Chave Pix da loja teste (CPF/e-mail/telefone/EVP). Sem isso o checkout bloqueia.",
        )
        parser.add_argument(
            "--price",
            default="5.00",
            help="Preço público do item (padrão 5.00).",
        )

    def handle(self, *args, **options):
        if not settings.DEBUG and not options["force"]:
            raise CommandError(
                "Em produção rode com --force. Ex.: "
                "python manage.py seed_payment_test --force --pix-key=SEU_PIX"
            )

        target_price = Decimal(options["price"]).quantize(Decimal("0.01"))
        if target_price < Decimal("1.00"):
            raise CommandError("Preço mínimo é R$ 1,00.")

        pix_key = (
            (options["pix_key"] or "").strip()
            or (getattr(settings, "PIX_TEST_KEY", "") or "").strip()
            or SELLER_CPF
        )
        payout = payout_from_price(target_price)

        seller, created = User.objects.get_or_create(
            username=SELLER_USERNAME,
            defaults={
                "email": "teste.pagamento@rendaerenda.local",
                "cpf": SELLER_CPF,
                "birth_date": datetime.date(1992, 5, 10),
                "is_age_verified": True,
                "is_phone_verified": True,
                "role": User.Role.SELLER,
                "public_alias": "Loja Teste",
                "phone_number": "5511999990001",
            },
        )
        if created:
            seller.set_password(PASSWORD)
            seller.save()
        else:
            seller.is_age_verified = True
            seller.is_phone_verified = True
            seller.role = User.Role.SELLER
            seller.is_active = True
            seller.is_banned = False
            seller.save()

        AgeVerification.objects.update_or_create(
            user=seller,
            defaults={
                "provider": "manual-test",
                "provider_reference_id": "seed-payment-test-age",
                "status": AgeVerification.Status.APPROVED,
                "document_validated": True,
                "validated_birth_date": seller.birth_date,
            },
        )
        SellerKYC.objects.update_or_create(
            user=seller,
            defaults={
                "document_front": "kyc/documents/teste.jpg",
                "document_back": "kyc/documents/teste.jpg",
                "selfie_with_document": "kyc/selfies/teste.jpg",
                "status": SellerKYC.Status.APPROVED,
                "majority_and_image_consent_term_signed_at": timezone.now(),
            },
        )

        store, _ = Store.objects.update_or_create(
            owner=seller,
            defaults={
                "slug": STORE_SLUG,
                "display_name": "Loja Teste Pagamento",
                "bio": "Loja só para testar checkout/Pix. Itens fictícios a R$ 5.",
                "status": Store.Status.ACTIVE,
                "plan": None,
                "plan_expires_at": None,
                "pix_key": pix_key,
                "pix_key_type": "CPF" if pix_key.isdigit() and len(pix_key) == 11 else "EVP",
                "origin_cep": "01310100",
            },
        )

        categories = {}
        for name in {cat for _, cat, _ in PRODUCTS}:
            slug = (
                name.lower()
                .replace("ã", "a")
                .replace("í", "i")
                .replace("á", "a")
            )
            categories[name], _ = Category.objects.get_or_create(
                name=name, defaults={"slug": slug}
            )

        created_products = []
        for slug, cat_name, title in PRODUCTS:
            product, was_created = Product.objects.update_or_create(
                store=store,
                slug=slug,
                defaults={
                    "category": categories[cat_name],
                    "title": title,
                    "description": (
                        "Produto fictício para teste de pagamento. "
                        f"Valor público R$ {target_price}. Frete grátis no checkout de teste."
                    ),
                    "payout_amount": payout,
                    "weight_grams": 80,
                    "status": Product.Status.PUBLISHED,
                    "visibility": Product.Visibility.PUBLIC,
                    "stock": 20,
                },
            )
            # Garante preço público exatamente igual ao pedido (evita arredondamento 4.99/5.01).
            Product.objects.filter(pk=product.pk).update(price=target_price)
            product.refresh_from_db()

            if was_created or not product.images.exists():
                product.images.all().delete()
                ProductImage.objects.create(
                    product=product,
                    file=ContentFile(
                        _placeholder_image(title),
                        name=f"{slug}.jpg",
                    ),
                    is_cover=True,
                    order=0,
                )
            created_products.append(product)

        self.stdout.write(self.style.SUCCESS("Loja teste pronta."))
        self.stdout.write(f"  URL loja: /loja/{store.slug}/")
        self.stdout.write(f"  Login vendedora: {SELLER_USERNAME} / {PASSWORD}")
        self.stdout.write(f"  Pix da loja: {store.pix_key}")
        self.stdout.write(f"  Preço dos itens: R$ {target_price}")
        for p in created_products:
            self.stdout.write(
                f"  - {p.title} -> /loja/{store.slug}/item/{p.slug}/  (id={p.id})"
            )
        self.stdout.write(
            "No checkout, escolha o frete 'Frete teste (grátis)' para cobrar só R$ 5,00."
        )
