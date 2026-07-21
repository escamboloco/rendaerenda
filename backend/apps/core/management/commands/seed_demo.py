"""
Povoamento de DEMONSTRAÇÃO: lojas, vendedoras, produtos (com imagens
placeholder geradas na hora - nenhuma foto real), compradoras, pedidos
entregues, avaliações e pedidos personalizados.

Uso:
    python manage.py seed_demo

Regras:
- SÓ roda com DEBUG=True (aborta em produção - dados e senhas de demo
  jamais podem existir num ambiente real).
- Idempotente: rodar de novo não duplica (get_or_create por chaves fixas).
- As credenciais criadas aqui estão documentadas em login.md (raiz do
  repositório) e são públicas de propósito - NUNCA reutilizar em produção.
"""
import datetime
import io
import random
from decimal import Decimal

from django.conf import settings
from django.core.files.base import ContentFile
from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone
from PIL import Image, ImageDraw

from apps.accounts.models import AgeVerification, SellerKYC, User
from apps.catalog.models import Category, Product, ProductImage
from apps.offers.services import counter_request, create_custom_request
from apps.payments.models import Order, OrderItem
from apps.reviews.models import Review
from apps.reviews.services import create_review
from apps.shipping.models import Shipment
from apps.stores.models import Store
from apps.stores.services import increment_sales_count
from apps.wallet.services import credit_sale, release_sale

PASSWORD = "demo12345"

CATEGORIES = ["Calcinhas", "Sutiãs", "Meias", "Sungas", "Bodys"]

# (username, nome da loja, slug, bio, CEP de origem)
SELLERS = [
    ("luna", "Ateliê da Luna", "atelie-da-luna", "Peças delicadas, embalagem discreta e envio no mesmo dia.", "01310100"),
    ("valentina", "Valentina Secreta", "valentina-secreta", "Uso com carinho e capricho na embalagem. Aceito pedidos personalizados.", "20040030"),
    ("morena", "Morena Misteriosa", "morena-misteriosa", "Itens usados com discrição total. Envio rápido pelo ponto de coleta.", "30130010"),
    ("ruiva", "Ruiva do Sul", "ruiva-do-sul", "Do frio do sul com muito capricho. Peças de renda são minha especialidade.", "90010150"),
    ("gata", "Gata Paulista", "gata-paulista", "Sempre respondo pedidos personalizados em até 24h.", "04538132"),
]

# (título, categoria, payout, gramas)
PRODUCTS = [
    ("Calcinha de renda preta — 3 dias de uso", "Calcinhas", "60.00", 80),
    ("Calcinha fio dental vermelha — 2 dias", "Calcinhas", "55.00", 60),
    ("Conjunto renda vinho — usado 1 vez", "Sutiãs", "95.00", 150),
    ("Sutiã de renda lilás — 2 dias de uso", "Sutiãs", "70.00", 120),
    ("Meia 7/8 preta — usada em ocasião especial", "Meias", "45.00", 90),
    ("Meias soquete brancas — 3 dias", "Meias", "35.00", 70),
    ("Body de renda preto — usado 1 noite", "Bodys", "110.00", 180),
    ("Calcinha de algodão rosa — 4 dias", "Calcinhas", "50.00", 70),
    ("Sunga usada em treino — 2 dias", "Sungas", "48.00", 110),
    ("Meia-calça arrastão — 1 uso", "Meias", "42.00", 85),
]

BUYERS = [
    ("comprador1", "Gato Misterioso"),
    ("comprador2", "Admirador Secreto"),
    ("comprador3", ""),  # sem apelido - testa o identificador neutro
]

REVIEW_COMMENTS = [
    "Chegou super rápido e a embalagem é realmente discreta. Recomendo!",
    "Exatamente como descrito, capricho total.",
    "Vendedora atenciosa, item bem embalado.",
    "Demorou um pouco mais que o previsto, mas veio tudo certo.",
    "Perfeito, já quero comprar de novo.",
    "",
]

# Paleta violeta/vermelho do design system para as imagens placeholder.
GRADIENTS = [
    ((124, 77, 191), (224, 36, 63)),
    ((76, 45, 120), (124, 77, 191)),
    ((224, 36, 63), (113, 16, 34)),
    ((28, 19, 41), (124, 77, 191)),
    ((28, 19, 41), (224, 36, 63)),
]


def make_placeholder_jpeg(seed: int, label: str) -> bytes:
    """Gradiente 600x600 com um marcador d'água textual - nenhuma foto real."""
    top, bottom = GRADIENTS[seed % len(GRADIENTS)]
    img = Image.new("RGB", (600, 600))
    for y in range(600):
        t = y / 599
        color = tuple(int(top[i] + (bottom[i] - top[i]) * t) for i in range(3))
        for x in range(600):
            img.putpixel((x, y), color)
    draw = ImageDraw.Draw(img)
    draw.text((24, 552), label, fill=(255, 255, 255))
    draw.text((24, 24), "foto ilustrativa", fill=(230, 230, 230))
    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=80)
    return buf.getvalue()


class Command(BaseCommand):
    help = "Povoa o banco com dados de demonstração (APENAS em DEBUG)."

    def handle(self, *args, **options):
        if not settings.DEBUG:
            raise CommandError(
                "seed_demo só roda com DJANGO_DEBUG=True - dados de demonstração nunca em produção."
            )

        rng = random.Random(42)  # determinístico: mesmo resultado a cada seed em banco limpo

        # --- admin ---
        if not User.objects.filter(username="admin").exists():
            User.objects.create_superuser(
                username="admin", email="admin@demo.local", password=PASSWORD,
                cpf="00000000000", birth_date=datetime.date(1990, 1, 1),
                is_age_verified=True, is_phone_verified=True,
            )
        self.stdout.write("admin ok")

        # --- categorias ---
        categories = {}
        for name in CATEGORIES:
            slug = name.lower().replace("ã", "a").replace("í", "i")
            categories[name], _ = Category.objects.get_or_create(name=name, defaults={"slug": slug})

        # --- vendedoras + lojas ---
        stores = []
        for index, (username, display_name, slug, bio, cep) in enumerate(SELLERS):
            cpf = f"1{index}122233344"[:11].ljust(11, "0")
            seller, created = User.objects.get_or_create(
                username=username,
                defaults={
                    "email": f"{username}@demo.local", "cpf": cpf,
                    "birth_date": datetime.date(1990 + index, 3, 15),
                    "is_age_verified": True, "is_phone_verified": True,
                    "role": "seller", "public_alias": display_name,
                    "phone_number": f"5511977700{index:02d}",
                },
            )
            if created:
                seller.set_password(PASSWORD)
                seller.save()
            AgeVerification.objects.get_or_create(
                user=seller,
                defaults={"provider": "idwall", "provider_reference_id": f"demo-age-{username}",
                          "status": "approved", "document_validated": True,
                          "validated_birth_date": seller.birth_date},
            )
            SellerKYC.objects.get_or_create(
                user=seller,
                defaults={"document_front": "kyc/documents/demo.jpg",
                          "document_back": "kyc/documents/demo.jpg",
                          "selfie_with_document": "kyc/selfies/demo.jpg",
                          "status": "approved",
                          "majority_and_image_consent_term_signed_at": timezone.now()},
            )
            store, _ = Store.objects.get_or_create(
                owner=seller,
                defaults={"slug": slug, "display_name": display_name, "bio": bio,
                          "status": "active", "plan": None, "plan_expires_at": None,
                          "pix_key": seller.cpf, "origin_cep": cep,
                          "psp_subaccount_id": f"demo-sub-{username}"},
            )
            stores.append(store)
        self.stdout.write(f"{len(stores)} lojas ok")

        # --- produtos com imagens geradas ---
        product_count = 0
        for store_index, store in enumerate(stores):
            # 4 produtos por loja, deslocados pra variar o catálogo entre lojas
            for offset in range(4):
                title, cat_name, payout, grams = PRODUCTS[(store_index * 2 + offset) % len(PRODUCTS)]
                slug = f"{store.slug}-item-{offset + 1}"
                product, created = Product.objects.get_or_create(
                    store=store, slug=slug,
                    defaults={
                        "category": categories[cat_name], "title": title,
                        "description": (
                            "Item físico usado, exatamente como descrito no título. "
                            "Embalagem lacrada e discreta, sem identificação do conteúdo. "
                            "Envio em até 2 dias úteis após a compra."
                        ),
                        "payout_amount": Decimal(payout), "weight_grams": grams,
                        "status": "published", "stock": 1,
                    },
                )
                if created:
                    for image_index in range(2):
                        data = make_placeholder_jpeg(store_index * 4 + offset + image_index, store.display_name)
                        ProductImage.objects.create(
                            product=product,
                            file=ContentFile(data, name=f"{slug}-{image_index}.jpg"),
                            is_cover=(image_index == 0), order=image_index,
                        )
                    product_count += 1
        self.stdout.write(f"{product_count} produtos novos com imagens ok")

        # --- compradores ---
        buyers = []
        for index, (username, alias) in enumerate(BUYERS):
            buyer, created = User.objects.get_or_create(
                username=username,
                defaults={"email": f"{username}@demo.local", "cpf": f"9{index}988877766"[:11].ljust(11, "0"),
                          "birth_date": datetime.date(1995 + index, 7, 20),
                          "is_age_verified": True, "is_phone_verified": True,
                          "role": "buyer", "public_alias": alias},
            )
            if created:
                buyer.set_password(PASSWORD)
                buyer.save()
            buyers.append(buyer)
        self.stdout.write(f"{len(buyers)} compradores ok")

        # --- pedidos entregues + avaliações (alimentam ranking e carteira) ---
        if not Review.objects.exists():
            review_count = 0
            for store_index, store in enumerate(stores):
                # Lojas diferentes recebem volumes diferentes -> ranking com variação real
                orders_for_store = 2 + (store_index % 3) * 2  # 2, 4 ou 6 pedidos
                products = list(store.products.all())
                for order_index in range(orders_for_store):
                    buyer = buyers[(store_index + order_index) % len(buyers)]
                    product = products[order_index % len(products)]
                    order = Order.objects.create(
                        buyer=buyer, store=store, status="delivered",
                        items_total=product.price, shipping_total=Decimal("21.40"),
                        packaging_fee=Decimal("3.90"),
                        shipping_address={"cep": "01001000", "street": "Rua Exemplo",
                                          "number": "100", "neighborhood": "Centro",
                                          "city": "São Paulo", "state": "SP"},
                        paid_at=timezone.now() - datetime.timedelta(days=10 - order_index),
                    )
                    OrderItem.objects.create(
                        order=order, product=product, unit_price=product.price,
                        unit_payout_amount=product.payout_amount, quantity=1,
                    )
                    Shipment.objects.create(
                        order=order, service="me-1", estimated_delivery_days=4,
                        status="delivered",
                        posted_at=timezone.now() - datetime.timedelta(days=8 - order_index),
                        delivered_at=timezone.now() - datetime.timedelta(days=5 - order_index),
                        tracking_code=f"DM{store_index}{order_index:02d}45678BR",
                        buyer_confirmed_at=timezone.now() - datetime.timedelta(days=4),
                    )
                    credit_sale(order)
                    release_sale(order)
                    increment_sales_count(store)

                    rating = rng.choice([5, 5, 5, 4, 4, 3])
                    create_review(buyer=buyer, order=order, rating=rating,
                                  comment=rng.choice(REVIEW_COMMENTS))
                    review_count += 1
            self.stdout.write(f"{review_count} pedidos entregues + avaliações ok")

        # --- pedidos personalizados de exemplo ---
        if not stores[0].custom_order_requests.exists():
            create_custom_request(
                buyer=buyers[0], store=stores[0],
                title="Calcinha de renda vinho, 3 dias de uso",
                description="Tamanho M, com embalagem lacrada. Pode ser com lacinho lateral?",
                offered_price=Decimal("85.00"),
            )
            countered = create_custom_request(
                buyer=buyers[1], store=stores[1],
                title="Meia 7/8 usada em treino",
                description="Par de meias 7/8 pretas, usadas em dois treinos.",
                offered_price=Decimal("60.00"),
            )
            counter_request(countered, counter_price=Decimal("80.00"),
                            counter_message="Consigo por esse valor, com fotos extras do item.")
            self.stdout.write("pedidos personalizados ok")

        self.stdout.write(self.style.SUCCESS(
            "Seed completo. Credenciais de demonstração documentadas em login.md "
            f"(senha padrão: {PASSWORD})"
        ))
