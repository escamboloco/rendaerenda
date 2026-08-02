"""
Povoamento de DEMONSTRAÇÃO: 20+ lojas, 50+ produtos com fotos públicas
(Unsplash — licença gratuita), compradoras, pedidos e avaliações.

Uso:
    python manage.py seed_demo

Regras:
- SÓ roda com DEBUG=True.
- Idempotente (get_or_create por chaves fixas).
- Credenciais em login.md — NUNCA reutilizar em produção.
"""
import datetime
import io
import random
import secrets
import urllib.error
import urllib.request
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
from apps.stores.models import Store, StoreFollow
from apps.stores.services import increment_sales_count
from apps.wallet.services import credit_sale, release_sale

PASSWORD = "demo12345"

CATEGORIES = ["Calcinhas", "Sutiãs", "Meias", "Sungas", "Bodys", "Packs"]

# Fotos públicas Unsplash (moda íntima / lingerie / meias) — licença Unsplash.
# Fallback automático para JPEG gerado se a rede falhar.
PHOTO_POOL = {
    "Calcinhas": [
        "https://images.unsplash.com/photo-1594633312681-425c7b97ccd1?auto=format&fit=crop&w=900&q=80",
        "https://images.unsplash.com/photo-1566174053879-31528523f8ae?auto=format&fit=crop&w=900&q=80",
        "https://images.unsplash.com/photo-1571513722275-4b41940f54b8?auto=format&fit=crop&w=900&q=80",
        "https://images.unsplash.com/photo-1617922001439-4a2e6562f328?auto=format&fit=crop&w=900&q=80",
        "https://images.unsplash.com/photo-1581044777550-4cfa60707c03?auto=format&fit=crop&w=900&q=80",
    ],
    "Sutiãs": [
        "https://images.unsplash.com/photo-1618354691373-d851c5c3a990?auto=format&fit=crop&w=900&q=80",
        "https://images.unsplash.com/photo-1596755094514-f87e34085b2c?auto=format&fit=crop&w=900&q=80",
        "https://images.unsplash.com/photo-1483985988355-763728e1935b?auto=format&fit=crop&w=900&q=80",
        "https://images.unsplash.com/photo-1469334031218-e382a71b716b?auto=format&fit=crop&w=900&q=80",
    ],
    "Meias": [
        "https://images.unsplash.com/photo-1586350977771-b3b0abd50c82?auto=format&fit=crop&w=900&q=80",
        "https://images.unsplash.com/photo-1515886657613-9f3515b0c78f?auto=format&fit=crop&w=900&q=80",
        "https://images.unsplash.com/photo-1525507119028-ed4c629a60a3?auto=format&fit=crop&w=900&q=80",
        "https://images.unsplash.com/photo-1543163521-1bf539c55dd2?auto=format&fit=crop&w=900&q=80",
    ],
    "Sungas": [
        "https://images.unsplash.com/photo-1507525428034-b723cf961d3e?auto=format&fit=crop&w=900&q=80",
        "https://images.unsplash.com/photo-1519046904884-53103b34b206?auto=format&fit=crop&w=900&q=80",
        "https://images.unsplash.com/photo-1505118380757-91f5f5632de0?auto=format&fit=crop&w=900&q=80",
    ],
    "Bodys": [
        "https://images.unsplash.com/photo-1515372039744-b8f1729e5bb1?auto=format&fit=crop&w=900&q=80",
        "https://images.unsplash.com/photo-1496747611176-843222e1e57c?auto=format&fit=crop&w=900&q=80",
        "https://images.unsplash.com/photo-1509631179647-0177331693ae?auto=format&fit=crop&w=900&q=80",
    ],
    "Packs": [
        "https://images.unsplash.com/photo-1516035069371-29a1b244cc32?auto=format&fit=crop&w=900&q=80",
        "https://images.unsplash.com/photo-1492691527719-9d1e07e534b4?auto=format&fit=crop&w=900&q=80",
        "https://images.unsplash.com/photo-1452587925148-ce544e77e70d?auto=format&fit=crop&w=900&q=80",
        "https://images.unsplash.com/photo-1542038784456-1ea8e935640e?auto=format&fit=crop&w=900&q=80",
    ],
}

SELLERS = [
    ("luna", "Ateliê da Luna", "atelie-da-luna", "Peças delicadas, embalagem discreta e envio no mesmo dia.", "01310100"),
    ("valentina", "Valentina Secreta", "valentina-secreta", "Uso com carinho e capricho na embalagem. Aceito pedidos personalizados.", "20040030"),
    ("morena", "Morena Misteriosa", "morena-misteriosa", "Itens usados com discrição total. Envio rápido pelo ponto de coleta.", "30130010"),
    ("ruiva", "Ruiva do Sul", "ruiva-do-sul", "Do frio do sul com muito capricho. Peças de renda são minha especialidade.", "90010150"),
    ("gata", "Gata Paulista", "gata-paulista", "Sempre respondo pedidos personalizados em até 24h.", "04538132"),
    ("bella", "Bella Íntima", "bella-intima", "Lingerie usada com perfume suave. Embalagem lacrada.", "01415000"),
    ("nina", "Nina da Noite", "nina-da-noite", "Packs e peças físicas. Comunicação só pela plataforma.", "22041080"),
    ("clara", "Clara Sedução", "clara-seducao", "Calcinhas e meias com dias de uso à escolha.", "80010000"),
    ("maya", "Maya Velvet", "maya-velvet", "Toque aveludado, fotos reais do item, envio rastreado.", "60160150"),
    ("sofia", "Sofia Lace", "sofia-lace", "Renda belga e algodão. Pedidos sob medida bem-vindos.", "70040902"),
    ("iara", "Iara do Centro", "iara-do-centro", "Entrega rápida em SP. Embalagem 100% neutra.", "01001000"),
    ("priscila", "Priscila Pink", "priscila-pink", "Tons rosa e vinho. Packs digitais também.", "13010000"),
    ("helena", "Helena Silk", "helena-silk", "Seda e cetim usados com carinho.", "40020000"),
    ("bruna", "Bruna Fitness", "bruna-fitness", "Meias e sungas pós-treino. Cheiro real de academia.", "29010000"),
    ("camila", "Camila Closet", "camila-closet", "Desapego íntimo semanal. Estoque rotativo.", "50010000"),
    ("duda", "Duda Secret", "duda-secret", "Peças únicas — quando acaba, acaba.", "69005040"),
    ("fernanda", "Fernanda Rouge", "fernanda-rouge", "Vermelho e preto clássicos. Avaliação 5 estrelas é minha meta.", "88010000"),
    ("giovana", "Giovana Soft", "giovana-soft", "Conforto e sensualidade. Respondo perguntas no anúncio.", "64000030"),
    ("isabela", "Isabela Night", "isabela-night", "Bodys e packs. Conteúdo digital libera na hora do Pix.", "69020000"),
    ("juliana", "Juliana Bloom", "juliana-bloom", "Flores e renda. Loja ativa todos os dias.", "74003010"),
    ("karina", "Karina Heat", "karina-heat", "Meia 7/8 e arrastão. Aceito encomendas.", "65010000"),
    ("lara", "Lara Privê", "lara-prive", "Packs exclusivos e peças físicas sob encomenda.", "49010000"),
]

PRODUCT_TEMPLATES = [
    ("Calcinha de renda preta — {days} dias de uso", "Calcinhas", "physical", "58.00", 80),
    ("Calcinha fio dental vermelha — {days} dias", "Calcinhas", "physical", "52.00", 60),
    ("Calcinha de algodão rosa — {days} dias", "Calcinhas", "physical", "45.00", 70),
    ("Calcinha cintura alta nude — {days} dias", "Calcinhas", "physical", "62.00", 85),
    ("Conjunto renda vinho — usado 1 vez", "Sutiãs", "physical", "98.00", 150),
    ("Sutiã de renda lilás — {days} dias de uso", "Sutiãs", "physical", "72.00", 120),
    ("Sutiã push-up preto — 1 uso", "Sutiãs", "physical", "80.00", 130),
    ("Meia 7/8 preta — ocasião especial", "Meias", "physical", "48.00", 90),
    ("Meias soquete brancas — {days} dias", "Meias", "physical", "32.00", 70),
    ("Meia-calça arrastão — 1 uso", "Meias", "physical", "44.00", 85),
    ("Meia 3/4 vinho — 2 treinos", "Meias", "physical", "38.00", 75),
    ("Sunga usada em treino — {days} dias", "Sungas", "physical", "49.00", 110),
    ("Sunga slim preta — 1 uso", "Sungas", "physical", "55.00", 100),
    ("Body de renda preto — 1 noite", "Bodys", "physical", "115.00", 180),
    ("Body tule vermelho — usado 1 vez", "Bodys", "physical", "108.00", 170),
    ("Pack fotos íntimas — 12 fotos", "Packs", "digital", "35.00", 0),
    ("Pack premium — 25 fotos + vídeo curto", "Packs", "digital", "79.00", 0),
    ("Pack meias — 8 fotos do kit", "Packs", "digital", "29.00", 0),
    ("Pack lingerie — 15 fotos", "Packs", "digital", "49.00", 0),
]

BUYERS = [
    ("comprador1", "Gato Misterioso"),
    ("comprador2", "Admirador Secreto"),
    ("comprador3", ""),
    ("comprador4", "Colecionador Quiet"),
    ("comprador5", "Fã Discreto"),
]

REVIEW_COMMENTS = [
    "Chegou super rápido e a embalagem é realmente discreta. Recomendo!",
    "Exatamente como descrito, capricho total.",
    "Vendedora atenciosa, item bem embalado.",
    "Demorou um pouco mais que o previsto, mas veio tudo certo.",
    "Perfeito, já quero comprar de novo.",
    "Pack liberou na hora do Pix. Top.",
    "",
]

FABRIC = {
    "Calcinhas": ["renda", "algodão", "microfibra", "cetim"],
    "Sutiãs": ["renda", "cetim", "microfibra"],
    "Meias": ["algodão", "fio de seda", "poliamida"],
    "Sungas": ["poliéster", "microfibra"],
    "Bodys": ["renda", "tule", "cetim"],
    "Packs": ["arquivo digital"],
}
SIZES = ["PP", "P", "M", "G"]

_IMAGE_CACHE: dict[str, bytes] = {}


def build_description(title: str, category: str, idx: int, kind: str) -> str:
    if kind == "digital":
        return (
            f"{title}. Arquivos digitais liberados na página do pedido assim que o Pix confirmar. "
            "Sem frete. Conteúdo produzido por adulta verificada; uso pessoal do comprador. "
            "Toda a conversa fica dentro da plataforma."
        )
    fabrics = FABRIC.get(category, ["tecido macio"])
    fabric = fabrics[idx % len(fabrics)]
    size = SIZES[idx % len(SIZES)]
    days = [1, 2, 3, 4][idx % 4]
    base_name = title.split("—")[0].strip()
    return (
        f"{base_name} em {fabric}, tamanho {size}. "
        f"Usada com carinho por {days} dia(s), em ótimo estado. "
        "Embalagem lacrada e discreta, sem identificação do conteúdo por fora. "
        "Postagem em até 2 dias úteis após a confirmação do pagamento. "
        "Toda a negociação e o contato acontecem dentro da plataforma."
    )


def _fallback_jpeg(category: str, title: str, variant: int) -> bytes:
    """JPEG fotográfico sintético (não desenho de silhueta) se Unsplash falhar."""
    w = 900
    rng = random.Random(hash((category, title, variant)) & 0xFFFFFFFF)
    base = {
        "Calcinhas": (42, 28, 38),
        "Sutiãs": (48, 32, 44),
        "Meias": (36, 34, 42),
        "Sungas": (28, 40, 48),
        "Bodys": (40, 30, 46),
        "Packs": (30, 30, 36),
    }.get(category, (40, 30, 40))
    img = Image.new("RGB", (w, w), base)
    d = ImageDraw.Draw(img)
    for _ in range(40):
        x0, y0 = rng.randint(0, w), rng.randint(0, w)
        x1, y1 = x0 + rng.randint(40, 220), y0 + rng.randint(40, 220)
        color = (
            min(255, base[0] + rng.randint(20, 90)),
            min(255, base[1] + rng.randint(10, 70)),
            min(255, base[2] + rng.randint(20, 90)),
        )
        d.ellipse([x0, y0, x1, y1], fill=color)
    # vinheta leve
    overlay = Image.new("RGB", (w, w), (10, 6, 8))
    img = Image.blend(img, overlay, 0.18)
    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=88)
    return buf.getvalue()


def fetch_photo(url: str, category: str, title: str, variant: int) -> bytes:
    if url in _IMAGE_CACHE:
        return _IMAGE_CACHE[url]
    try:
        req = urllib.request.Request(
            url,
            headers={"User-Agent": "RendaRendaSeed/1.0 (demo; +https://rendaerenda.com.br)"},
        )
        with urllib.request.urlopen(req, timeout=20) as resp:
            data = resp.read()
        # Garante JPEG/PNG válido
        Image.open(io.BytesIO(data)).verify()
        _IMAGE_CACHE[url] = data
        return data
    except (urllib.error.URLError, urllib.error.HTTPError, OSError, ValueError):
        data = _fallback_jpeg(category, title, variant)
        _IMAGE_CACHE[url] = data
        return data


def pick_photos(category: str, idx: int, count: int = 2) -> list[str]:
    pool = PHOTO_POOL.get(category) or PHOTO_POOL["Calcinhas"]
    return [pool[(idx + i) % len(pool)] for i in range(count)]


class Command(BaseCommand):
    help = "Povoa o banco com dados de demonstração (APENAS em DEBUG)."

    def handle(self, *args, **options):
        if not settings.DEBUG:
            raise CommandError(
                "seed_demo só roda com DJANGO_DEBUG=True - dados de demonstração nunca em produção."
            )

        rng = random.Random(42)

        if not User.objects.filter(username="admin").exists():
            User.objects.create_superuser(
                username="admin", email="admin@demo.local", password=PASSWORD,
                cpf="00000000000", birth_date=datetime.date(1990, 1, 1),
                is_age_verified=True, is_phone_verified=True,
            )
        self.stdout.write("admin ok")

        categories = {}
        for name in CATEGORIES:
            slug = (
                name.lower()
                .replace("ã", "a")
                .replace("í", "i")
                .replace("á", "a")
            )
            categories[name], _ = Category.objects.get_or_create(name=name, defaults={"slug": slug})

        stores = []
        for index, (username, display_name, slug, bio, cep) in enumerate(SELLERS):
            cpf = f"{(index + 1):02d}1222333{(index % 10)}"[:11].ljust(11, str(index % 10))
            # CPFs únicos e com 11 dígitos
            cpf = f"1{index:02d}{1000000 + index * 137:07d}"[:11]
            seller, created = User.objects.get_or_create(
                username=username,
                defaults={
                    "email": f"{username}@demo.local",
                    "cpf": cpf,
                    "birth_date": datetime.date(1988 + (index % 10), 3, 15),
                    "is_age_verified": True,
                    "is_phone_verified": True,
                    "role": "seller",
                    "public_alias": display_name,
                    "phone_number": f"55119777{index:04d}",
                },
            )
            if created:
                seller.set_password(PASSWORD)
                seller.save()
            AgeVerification.objects.get_or_create(
                user=seller,
                defaults={
                    "provider": "idwall",
                    "provider_reference_id": f"demo-age-{username}",
                    "status": "approved",
                    "document_validated": True,
                    "validated_birth_date": seller.birth_date,
                },
            )
            SellerKYC.objects.get_or_create(
                user=seller,
                defaults={
                    "document_front": "kyc/documents/demo.jpg",
                    "document_back": "kyc/documents/demo.jpg",
                    "selfie_with_document": "kyc/selfies/demo.jpg",
                    "status": "approved",
                    "majority_and_image_consent_term_signed_at": timezone.now(),
                },
            )
            store, _ = Store.objects.get_or_create(
                owner=seller,
                defaults={
                    "slug": slug,
                    "display_name": display_name,
                    "bio": bio,
                    "status": "active",
                    "plan": None,
                    "plan_expires_at": None,
                    "pix_key": seller.cpf,
                    "origin_cep": cep,
                    "psp_subaccount_id": f"demo-sub-{username}",
                },
            )
            stores.append(store)
        self.stdout.write(f"{len(stores)} lojas ok")

        product_count = 0
        photo_ok = 0
        # ~3 produtos por loja => 66+ itens; preços variam por loja
        for store_index, store in enumerate(stores):
            for offset in range(3):
                template = PRODUCT_TEMPLATES[(store_index * 3 + offset) % len(PRODUCT_TEMPLATES)]
                title_tpl, cat_name, kind, payout_base, grams = template
                days = 1 + ((store_index + offset) % 4)
                title = title_tpl.format(days=days)
                # Variação de preço por loja (±30%)
                payout = (Decimal(payout_base) * Decimal(str(0.85 + (store_index % 7) * 0.05))).quantize(
                    Decimal("0.01")
                )
                slug = f"{store.slug}-item-{offset + 1}"
                idx = store_index * 3 + offset
                defaults = {
                    "category": categories[cat_name],
                    "title": title,
                    "description": build_description(title, cat_name, idx, kind),
                    "payout_amount": payout,
                    "weight_grams": grams,
                    "status": "published",
                    "stock": 5 if kind == "digital" else 1,
                    "kind": kind,
                }
                product, created = Product.objects.get_or_create(
                    store=store, slug=slug, defaults=defaults,
                )
                if created:
                    urls = pick_photos(cat_name, idx, 2)
                    for image_index, url in enumerate(urls):
                        data = fetch_photo(url, cat_name, title, image_index)
                        if url in _IMAGE_CACHE and not data.startswith(b"\xff\xd8"):
                            pass  # fallback ok
                        else:
                            photo_ok += 1
                        ext = "jpg"
                        ProductImage.objects.create(
                            product=product,
                            file=ContentFile(data, name=f"{slug}-{image_index}.{ext}"),
                            is_cover=(image_index == 0),
                            order=image_index,
                        )
                    product_count += 1
        self.stdout.write(f"{product_count} produtos novos · {photo_ok} fotos baixadas/geradas ok")

        buyers = []
        for index, (username, alias) in enumerate(BUYERS):
            buyer, created = User.objects.get_or_create(
                username=username,
                defaults={
                    "email": f"{username}@demo.local",
                    "cpf": f"9{index:02d}{8000000 + index * 91:07d}"[:11],
                    "birth_date": datetime.date(1992 + index, 7, 20),
                    "is_age_verified": True,
                    "is_phone_verified": True,
                    "role": "buyer",
                    "public_alias": alias,
                },
            )
            if created:
                buyer.set_password(PASSWORD)
                buyer.save()
            buyers.append(buyer)
        self.stdout.write(f"{len(buyers)} compradores ok")

        # Seguidores de loja (interação)
        follows = 0
        for bi, buyer in enumerate(buyers):
            for store in stores[bi : bi + 4]:
                _, created = StoreFollow.objects.get_or_create(store=store, user=buyer)
                if created:
                    follows += 1
        self.stdout.write(f"{follows} follows novos ok")

        if not Review.objects.exists():
            review_count = 0
            for store_index, store in enumerate(stores[:12]):
                orders_for_store = 2 + (store_index % 3)
                products = list(store.products.filter(status="published"))
                if not products:
                    continue
                for order_index in range(orders_for_store):
                    buyer = buyers[(store_index + order_index) % len(buyers)]
                    product = products[order_index % len(products)]
                    order = Order.objects.create(
                        buyer=buyer,
                        store=store,
                        status="delivered",
                        items_total=product.price,
                        shipping_total=Decimal("0.00") if product.kind == "digital" else Decimal("21.40"),
                        packaging_fee=Decimal("0.00") if product.kind == "digital" else Decimal("3.90"),
                        shipping_address={
                            "cep": "01001000",
                            "street": "Rua Exemplo",
                            "number": "100",
                            "neighborhood": "Centro",
                            "city": "São Paulo",
                            "state": "SP",
                        },
                        paid_at=timezone.now() - datetime.timedelta(days=10 - order_index),
                        access_token=secrets.token_urlsafe(32),
                    )
                    OrderItem.objects.create(
                        order=order,
                        product=product,
                        unit_price=product.price,
                        unit_payout_amount=product.payout_amount,
                        quantity=1,
                    )
                    if product.kind != "digital":
                        Shipment.objects.create(
                            order=order,
                            service="me-1",
                            estimated_delivery_days=4,
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
                    create_review(
                        buyer=buyer,
                        order=order,
                        rating=rating,
                        comment=rng.choice(REVIEW_COMMENTS),
                    )
                    review_count += 1
            self.stdout.write(f"{review_count} pedidos entregues + avaliações ok")

        if stores and buyers and not stores[0].custom_order_requests.exists():
            create_custom_request(
                buyer=buyers[0],
                store=stores[0],
                title="Calcinha de renda vinho, 3 dias de uso",
                description="Tamanho M, com embalagem lacrada. Pode ser com lacinho lateral?",
                offered_price=Decimal("85.00"),
            )
            countered = create_custom_request(
                buyer=buyers[1],
                store=stores[1],
                title="Meia 7/8 usada em treino",
                description="Par de meias 7/8 pretas, usadas em dois treinos.",
                offered_price=Decimal("60.00"),
            )
            counter_request(
                countered,
                counter_price=Decimal("80.00"),
                counter_message="Consigo por esse valor, com fotos extras do item.",
            )
            self.stdout.write("pedidos personalizados ok")

        total_products = Product.objects.filter(status="published").count()
        self.stdout.write(
            self.style.SUCCESS(
                f"Seed completo: {len(stores)} lojas, {total_products} produtos publicados. "
                f"Senha padrão: {PASSWORD} (ver login.md)"
            )
        )
