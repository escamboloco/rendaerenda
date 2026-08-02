"""
Povoamento de catálogo demo: 20+ lojas, 70+ produtos, CEPs distintos
e fotos públicas (Unsplash/Pexels).

Uso local:
    python manage.py seed_demo

Produção (Render):
    python manage.py seed_demo --force

Credenciais em login.md — NÃO reutilizar em contas reais.
"""
from __future__ import annotations

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
PRODUCTS_PER_STORE = 4  # 22 lojas × 4 = 88 produtos (≥ 70)

CATEGORIES = ["Calcinhas", "Sutiãs", "Meias", "Sungas", "Bodys", "Packs"]

# Fotos públicas (Unsplash / Pexels) — uso editorial/demo, licenças permissivas.
PHOTO_POOL = {
    "Calcinhas": [
        "https://images.unsplash.com/photo-1594633312681-425c7b97ccd1?auto=format&fit=crop&w=720&q=75",
        "https://images.unsplash.com/photo-1566174053879-31528523f8ae?auto=format&fit=crop&w=720&q=75",
        "https://images.unsplash.com/photo-1571513722275-4b41940f54b8?auto=format&fit=crop&w=720&q=75",
        "https://images.unsplash.com/photo-1617922001439-4a2e6562f328?auto=format&fit=crop&w=720&q=75",
        "https://images.unsplash.com/photo-1581044777550-4cfa60707c03?auto=format&fit=crop&w=720&q=75",
        "https://images.pexels.com/photos/1536619/pexels-photo-1536619.jpeg?auto=compress&cs=tinysrgb&w=720",
        "https://images.pexels.com/photos/1375736/pexels-photo-1375736.jpeg?auto=compress&cs=tinysrgb&w=720",
    ],
    "Sutiãs": [
        "https://images.unsplash.com/photo-1618354691373-d851c5c3a990?auto=format&fit=crop&w=720&q=75",
        "https://images.unsplash.com/photo-1596755094514-f87e34085b2c?auto=format&fit=crop&w=720&q=75",
        "https://images.unsplash.com/photo-1483985988355-763728e1935b?auto=format&fit=crop&w=720&q=75",
        "https://images.unsplash.com/photo-1469334031218-e382a71b716b?auto=format&fit=crop&w=720&q=75",
        "https://images.pexels.com/photos/7679720/pexels-photo-7679720.jpeg?auto=compress&cs=tinysrgb&w=720",
        "https://images.pexels.com/photos/6311392/pexels-photo-6311392.jpeg?auto=compress&cs=tinysrgb&w=720",
    ],
    "Meias": [
        "https://images.unsplash.com/photo-1586350977771-b3b0abd50c82?auto=format&fit=crop&w=720&q=75",
        "https://images.unsplash.com/photo-1515886657613-9f3515b0c78f?auto=format&fit=crop&w=720&q=75",
        "https://images.unsplash.com/photo-1525507119028-ed4c629a60a3?auto=format&fit=crop&w=720&q=75",
        "https://images.unsplash.com/photo-1543163521-1bf539c55dd2?auto=format&fit=crop&w=720&q=75",
        "https://images.pexels.com/photos/1478442/pexels-photo-1478442.jpeg?auto=compress&cs=tinysrgb&w=720",
    ],
    "Sungas": [
        "https://images.unsplash.com/photo-1507525428034-b723cf961d3e?auto=format&fit=crop&w=720&q=75",
        "https://images.unsplash.com/photo-1519046904884-53103b34b206?auto=format&fit=crop&w=720&q=75",
        "https://images.unsplash.com/photo-1505118380757-91f5f5632de0?auto=format&fit=crop&w=720&q=75",
        "https://images.pexels.com/photos/1450363/pexels-photo-1450363.jpeg?auto=compress&cs=tinysrgb&w=720",
    ],
    "Bodys": [
        "https://images.unsplash.com/photo-1515372039744-b8f1729e5bb1?auto=format&fit=crop&w=720&q=75",
        "https://images.unsplash.com/photo-1496747611176-843222e1e57c?auto=format&fit=crop&w=720&q=75",
        "https://images.unsplash.com/photo-1509631179647-0177331693ae?auto=format&fit=crop&w=720&q=75",
        "https://images.pexels.com/photos/985635/pexels-photo-985635.jpeg?auto=compress&cs=tinysrgb&w=720",
    ],
    "Packs": [
        "https://images.unsplash.com/photo-1516035069371-29a1b244cc32?auto=format&fit=crop&w=720&q=75",
        "https://images.unsplash.com/photo-1492691527719-9d1e07e534b4?auto=format&fit=crop&w=720&q=75",
        "https://images.unsplash.com/photo-1452587925148-ce544e77e70d?auto=format&fit=crop&w=720&q=75",
        "https://images.unsplash.com/photo-1542038784456-1ea8e935640e?auto=format&fit=crop&w=720&q=75",
        "https://images.pexels.com/photos/3062541/pexels-photo-3062541.jpeg?auto=compress&cs=tinysrgb&w=720",
    ],
}

# username, display, slug, bio, cep, street, number, district, city, state
SELLERS = [
    ("luna", "Ateliê da Luna", "atelie-da-luna", "Peças delicadas, embalagem discreta e envio no mesmo dia.", "01310100", "Avenida Paulista", "1000", "Bela Vista", "São Paulo", "SP"),
    ("valentina", "Valentina Secreta", "valentina-secreta", "Uso com carinho e capricho na embalagem. Aceito pedidos personalizados.", "20040020", "Avenida Rio Branco", "156", "Centro", "Rio de Janeiro", "RJ"),
    ("morena", "Morena Misteriosa", "morena-misteriosa", "Itens usados com discrição total. Envio rápido pelo ponto de coleta.", "30130010", "Avenida Afonso Pena", "1500", "Centro", "Belo Horizonte", "MG"),
    ("ruiva", "Ruiva do Sul", "ruiva-do-sul", "Do frio do sul com muito capricho. Peças de renda são minha especialidade.", "90010150", "Rua dos Andradas", "1001", "Centro Histórico", "Porto Alegre", "RS"),
    ("gata", "Gata Paulista", "gata-paulista", "Sempre respondo pedidos personalizados em até 24h.", "04538132", "Avenida Brigadeiro Faria Lima", "3477", "Itaim Bibi", "São Paulo", "SP"),
    ("bella", "Bella Íntima", "bella-intima", "Lingerie usada com perfume suave. Embalagem lacrada.", "01415000", "Rua Augusta", "2690", "Cerqueira César", "São Paulo", "SP"),
    ("nina", "Nina da Noite", "nina-da-noite", "Packs e peças físicas. Comunicação só pela plataforma.", "22041080", "Avenida Nossa Senhora de Copacabana", "540", "Copacabana", "Rio de Janeiro", "RJ"),
    ("clara", "Clara Sedução", "clara-seducao", "Calcinhas e meias com dias de uso à escolha.", "80010000", "Rua XV de Novembro", "700", "Centro", "Curitiba", "PR"),
    ("maya", "Maya Velvet", "maya-velvet", "Toque aveludado, fotos reais do item, envio rastreado.", "60160150", "Avenida Beira Mar", "4260", "Meireles", "Fortaleza", "CE"),
    ("sofia", "Sofia Lace", "sofia-lace", "Renda belga e algodão. Pedidos sob medida bem-vindos.", "70040902", "SBN Quadra 1", "100", "Asa Norte", "Brasília", "DF"),
    ("iara", "Iara do Centro", "iara-do-centro", "Entrega rápida em SP. Embalagem 100% neutra.", "01001000", "Praça da Sé", "100", "Sé", "São Paulo", "SP"),
    ("priscila", "Priscila Pink", "priscila-pink", "Tons rosa e vinho. Packs digitais também.", "13010000", "Avenida Francisco Glicério", "900", "Centro", "Campinas", "SP"),
    ("helena", "Helena Silk", "helena-silk", "Seda e cetim usados com carinho.", "40020000", "Avenida Sete de Setembro", "1800", "Centro", "Salvador", "BA"),
    ("bruna", "Bruna Fitness", "bruna-fitness", "Meias e sungas pós-treino. Cheiro real de academia.", "29010020", "Avenida Jerônimo Monteiro", "200", "Centro", "Vitória", "ES"),
    ("camila", "Camila Closet", "camila-closet", "Desapego íntimo semanal. Estoque rotativo.", "50010000", "Avenida Guararapes", "250", "Santo Antônio", "Recife", "PE"),
    ("duda", "Duda Secret", "duda-secret", "Peças únicas — quando acaba, acaba.", "69005040", "Avenida Eduardo Ribeiro", "520", "Centro", "Manaus", "AM"),
    ("fernanda", "Fernanda Rouge", "fernanda-rouge", "Vermelho e preto clássicos. Avaliação 5 estrelas é minha meta.", "88015100", "Rua Felipe Schmidt", "390", "Centro", "Florianópolis", "SC"),
    ("giovana", "Giovana Soft", "giovana-soft", "Conforto e sensualidade. Respondo perguntas no anúncio.", "64000030", "Avenida Frei Serafim", "2100", "Centro", "Teresina", "PI"),
    ("isabela", "Isabela Night", "isabela-night", "Bodys e packs. Conteúdo digital libera na hora do Pix.", "66010000", "Avenida Presidente Vargas", "800", "Campina", "Belém", "PA"),
    ("juliana", "Juliana Bloom", "juliana-bloom", "Flores e renda. Loja ativa todos os dias.", "74003010", "Avenida Goiás", "200", "Centro", "Goiânia", "GO"),
    ("karina", "Karina Heat", "karina-heat", "Meia 7/8 e arrastão. Aceito encomendas.", "65010000", "Avenida São Luís Rei de França", "15", "Turú", "São Luís", "MA"),
    ("lara", "Lara Privê", "lara-prive", "Packs exclusivos e peças físicas sob encomenda.", "49010000", "Avenida Ivo do Prado", "350", "Centro", "Aracaju", "SE"),
]

PRODUCT_TEMPLATES = [
    ("Calcinha de renda preta — {days} dias de uso", "Calcinhas", "physical", "58.00", 80),
    ("Calcinha fio dental vermelha — {days} dias", "Calcinhas", "physical", "52.00", 60),
    ("Calcinha de algodão rosa — {days} dias", "Calcinhas", "physical", "45.00", 70),
    ("Calcinha cintura alta nude — {days} dias", "Calcinhas", "physical", "62.00", 85),
    ("Calcinha lacinho branco — {days} dias", "Calcinhas", "physical", "39.00", 65),
    ("Conjunto renda vinho — usado 1 vez", "Sutiãs", "physical", "98.00", 150),
    ("Sutiã de renda lilás — {days} dias de uso", "Sutiãs", "physical", "72.00", 120),
    ("Sutiã push-up preto — 1 uso", "Sutiãs", "physical", "80.00", 130),
    ("Sutiã esportivo cinza — 2 treinos", "Sutiãs", "physical", "54.00", 140),
    ("Meia 7/8 preta — ocasião especial", "Meias", "physical", "48.00", 90),
    ("Meias soquete brancas — {days} dias", "Meias", "physical", "32.00", 70),
    ("Meia-calça arrastão — 1 uso", "Meias", "physical", "44.00", 85),
    ("Meia 3/4 vinho — 2 treinos", "Meias", "physical", "38.00", 75),
    ("Meia arrastão com liga — 1 noite", "Meias", "physical", "69.00", 95),
    ("Sunga usada em treino — {days} dias", "Sungas", "physical", "49.00", 110),
    ("Sunga slim preta — 1 uso", "Sungas", "physical", "55.00", 100),
    ("Sunga navy pós-praia — 1 uso", "Sungas", "physical", "61.00", 105),
    ("Body de renda preto — 1 noite", "Bodys", "physical", "115.00", 180),
    ("Body tule vermelho — usado 1 vez", "Bodys", "physical", "108.00", 170),
    ("Body cetim champagne — 1 uso", "Bodys", "physical", "129.00", 190),
    ("Pack fotos íntimas — 12 fotos", "Packs", "digital", "35.00", 0),
    ("Pack premium — 25 fotos + vídeo curto", "Packs", "digital", "79.00", 0),
    ("Pack meias — 8 fotos do kit", "Packs", "digital", "29.00", 0),
    ("Pack lingerie — 15 fotos", "Packs", "digital", "49.00", 0),
    ("Pack exclusivo da semana — 20 fotos", "Packs", "digital", "89.00", 0),
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
_REMOTE_OK: set[str] = set()


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
    """Último recurso se a CDN falhar — ainda assim JPEG fotográfico sintético."""
    w = 720
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
    for _ in range(28):
        x0, y0 = rng.randint(0, w), rng.randint(0, w)
        x1, y1 = x0 + rng.randint(40, 220), y0 + rng.randint(40, 220)
        color = (
            min(255, base[0] + rng.randint(20, 90)),
            min(255, base[1] + rng.randint(10, 70)),
            min(255, base[2] + rng.randint(20, 90)),
        )
        d.ellipse([x0, y0, x1, y1], fill=color)
    overlay = Image.new("RGB", (w, w), (10, 6, 8))
    img = Image.blend(img, overlay, 0.18)
    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=82, optimize=True)
    return buf.getvalue()


def fetch_photo(url: str, category: str, title: str, variant: int) -> tuple[bytes, bool]:
    """Retorna (bytes, is_remote_photo)."""
    if url in _IMAGE_CACHE:
        return _IMAGE_CACHE[url], url in _REMOTE_OK
    try:
        req = urllib.request.Request(
            url,
            headers={"User-Agent": "RendaRendaSeed/1.0 (demo; +https://rendaerenda.com.br)"},
        )
        with urllib.request.urlopen(req, timeout=25) as resp:
            data = resp.read()
        with Image.open(io.BytesIO(data)) as img:
            img.verify()
        _IMAGE_CACHE[url] = data
        _REMOTE_OK.add(url)
        return data, True
    except (urllib.error.URLError, urllib.error.HTTPError, OSError, ValueError):
        data = _fallback_jpeg(category, title, variant)
        _IMAGE_CACHE[url] = data
        return data, False


def pick_photos(category: str, idx: int, count: int = 2) -> list[str]:
    pool = PHOTO_POOL.get(category) or PHOTO_POOL["Calcinhas"]
    return [pool[(idx + i) % len(pool)] for i in range(count)]


def _attach_photos(product: Product, category: str, title: str, idx: int, *, refresh: bool) -> tuple[int, int]:
    """Garante fotos no produto. Retorna (remotas, fallbacks)."""
    if product.images.exists() and not refresh:
        return 0, 0
    product.images.all().delete()
    remote = fallback = 0
    for image_index, url in enumerate(pick_photos(category, idx, 2)):
        data, ok = fetch_photo(url, category, title, image_index)
        if ok:
            remote += 1
        else:
            fallback += 1
        ProductImage.objects.create(
            product=product,
            file=ContentFile(data, name=f"{product.slug}-{image_index}.jpg"),
            is_cover=(image_index == 0),
            order=image_index,
        )
    return remote, fallback


class Command(BaseCommand):
    help = "Povoa o banco com 20+ lojas, 70+ produtos, CEPs distintos e fotos públicas."

    def add_arguments(self, parser):
        parser.add_argument(
            "--force",
            action="store_true",
            help="Permite rodar com DEBUG=False (produção / Render).",
        )
        parser.add_argument(
            "--refresh-images",
            action="store_true",
            help="Recria fotos mesmo se o produto já tiver imagem.",
        )
        parser.add_argument(
            "--skip-social",
            action="store_true",
            help="Não cria pedidos, avaliações nem follows (seed mais rápido).",
        )

    def handle(self, *args, **options):
        if not settings.DEBUG and not options["force"]:
            raise CommandError(
                "Em produção rode com --force. Ex.: python manage.py seed_demo --force"
            )
        if not settings.DEBUG and options["force"]:
            self.stdout.write(
                self.style.WARNING(
                    "ATENÇÃO: seed_demo em DEBUG=False. Desligue SEED_PAYMENT_TEST e "
                    "rode purge_demo_and_test_data antes de abrir ao público amplo."
                )
            )

        rng = random.Random(42)
        refresh_images = options["refresh_images"]

        # Substitui o antigo smoke test de 3 itens a R$ 5.
        smoke = Store.objects.filter(slug="loja-teste-pagamento").select_related("owner").first()
        if smoke:
            owner = smoke.owner
            Product.objects.filter(store=smoke).delete()
            smoke.delete()
            if owner and (
                owner.username == "teste_pagamento"
                or (owner.email or "").endswith("@rendaerenda.local")
            ):
                AgeVerification.objects.filter(user=owner).delete()
                SellerKYC.objects.filter(user=owner).delete()
                owner.delete()
            self.stdout.write("loja-teste-pagamento removida (substituída pelo catálogo demo)")

        if settings.DEBUG and not User.objects.filter(username="admin").exists():
            User.objects.create_superuser(
                username="admin",
                email="admin@demo.local",
                password=PASSWORD,
                cpf="39053344705",
                birth_date=datetime.date(1990, 1, 1),
                is_age_verified=True,
                is_phone_verified=True,
            )
            self.stdout.write("admin demo ok")

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
        for index, row in enumerate(SELLERS):
            (
                username,
                display_name,
                slug,
                bio,
                cep,
                street,
                number,
                district,
                city,
                state,
            ) = row
            cpf = f"1{index:02d}{1000000 + index * 137:07d}"[:11]
            seller, created = User.objects.get_or_create(
                username=username,
                defaults={
                    "email": f"{username}@demo.local",
                    "cpf": cpf,
                    "birth_date": datetime.date(1988 + (index % 10), 3, 15),
                    "is_age_verified": True,
                    "is_phone_verified": True,
                    "role": User.Role.SELLER,
                    "public_alias": display_name,
                    "phone_number": f"55119777{index:04d}",
                },
            )
            if created:
                seller.set_password(PASSWORD)
                seller.save()
            else:
                seller.role = User.Role.SELLER
                seller.is_active = True
                seller.is_banned = False
                seller.is_age_verified = True
                seller.save(
                    update_fields=["role", "is_active", "is_banned", "is_age_verified"]
                )

            AgeVerification.objects.update_or_create(
                user=seller,
                defaults={
                    "provider": "manual-demo",
                    "provider_reference_id": f"demo-age-{username}",
                    "status": AgeVerification.Status.APPROVED,
                    "document_validated": True,
                    "validated_birth_date": seller.birth_date,
                },
            )
            SellerKYC.objects.update_or_create(
                user=seller,
                defaults={
                    "document_front": "kyc/documents/demo.jpg",
                    "document_back": "kyc/documents/demo.jpg",
                    "selfie_with_document": "kyc/selfies/demo.jpg",
                    "status": SellerKYC.Status.APPROVED,
                    "majority_and_image_consent_term_signed_at": timezone.now(),
                },
            )
            store, _ = Store.objects.update_or_create(
                owner=seller,
                defaults={
                    "slug": slug,
                    "display_name": display_name,
                    "bio": bio,
                    "status": Store.Status.ACTIVE,
                    "plan": None,
                    "plan_expires_at": None,
                    "pix_key": seller.cpf or cpf,
                    "pix_key_type": "CPF",
                    "origin_cep": cep,
                    "origin_street": street,
                    "origin_number": number,
                    "origin_district": district,
                    "origin_city": city,
                    "origin_state": state,
                    "psp_subaccount_id": f"demo-sub-{username}",
                },
            )
            stores.append(store)
        self.stdout.write(f"{len(stores)} lojas ok (CEPs distintos por cidade)")

        product_count = 0
        remote_photos = 0
        fallback_photos = 0
        for store_index, store in enumerate(stores):
            for offset in range(PRODUCTS_PER_STORE):
                template = PRODUCT_TEMPLATES[
                    (store_index * PRODUCTS_PER_STORE + offset) % len(PRODUCT_TEMPLATES)
                ]
                title_tpl, cat_name, kind, payout_base, grams = template
                days = 1 + ((store_index + offset) % 4)
                title = title_tpl.format(days=days)
                # Preços bem variados entre lojas e itens (± e degraus).
                factor = Decimal(str(0.70 + (store_index % 9) * 0.07 + (offset % 3) * 0.04))
                payout = (Decimal(payout_base) * factor).quantize(Decimal("0.01"))
                if payout < Decimal("1.00"):
                    payout = Decimal("1.00")
                slug = f"{store.slug}-item-{offset + 1}"
                idx = store_index * PRODUCTS_PER_STORE + offset
                defaults = {
                    "category": categories[cat_name],
                    "title": title,
                    "description": build_description(title, cat_name, idx, kind),
                    "payout_amount": payout,
                    "weight_grams": grams,
                    "status": Product.Status.PUBLISHED,
                    "visibility": Product.Visibility.PUBLIC,
                    "stock": 8 if kind == "digital" else 2,
                    "kind": kind,
                }
                product, created = Product.objects.update_or_create(
                    store=store,
                    slug=slug,
                    defaults=defaults,
                )
                product_count += 1
                rem, fal = _attach_photos(
                    product,
                    cat_name,
                    title,
                    idx,
                    refresh=refresh_images or created or not product.images.exists(),
                )
                remote_photos += rem
                fallback_photos += fal

        self.stdout.write(
            f"{product_count} produtos · fotos remotas={remote_photos} fallback={fallback_photos}"
        )

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
                    "role": User.Role.BUYER,
                    "public_alias": alias,
                },
            )
            if created:
                buyer.set_password(PASSWORD)
                buyer.save()
            buyers.append(buyer)
        self.stdout.write(f"{len(buyers)} compradores ok")

        if not options["skip_social"]:
            follows = 0
            for bi, buyer in enumerate(buyers):
                for store in stores[bi : bi + 4]:
                    _, created = StoreFollow.objects.get_or_create(store=store, user=buyer)
                    if created:
                        follows += 1
            self.stdout.write(f"{follows} follows novos ok")

            if not Review.objects.filter(store__slug__in=[s.slug for s in stores]).exists():
                review_count = 0
                for store_index, store in enumerate(stores[:12]):
                    orders_for_store = 2 + (store_index % 3)
                    products = list(store.products.filter(status=Product.Status.PUBLISHED))
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
                            shipping_total=(
                                Decimal("0.00")
                                if product.kind == Product.Kind.DIGITAL
                                else Decimal("21.40")
                            ),
                            packaging_fee=(
                                Decimal("0.00")
                                if product.kind == Product.Kind.DIGITAL
                                else Decimal("3.90")
                            ),
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
                        if product.kind != Product.Kind.DIGITAL:
                            Shipment.objects.create(
                                order=order,
                                service="sf-1",
                                estimated_delivery_days=4,
                                status="delivered",
                                posted_at=timezone.now() - datetime.timedelta(days=8 - order_index),
                                delivered_at=timezone.now()
                                - datetime.timedelta(days=5 - order_index),
                                tracking_code=f"DM{store_index}{order_index:02d}45678BR",
                                buyer_confirmed_at=timezone.now()
                                - datetime.timedelta(days=4),
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

        total_products = Product.objects.filter(
            status=Product.Status.PUBLISHED,
            store__slug__in=[s.slug for s in stores],
        ).count()
        distinct_ceps = Store.objects.filter(slug__in=[s.slug for s in stores]).values(
            "origin_cep"
        ).distinct().count()
        self.stdout.write(
            self.style.SUCCESS(
                f"Seed completo: {len(stores)} lojas, {total_products} produtos, "
                f"{distinct_ceps} CEPs de origem. Senha: {PASSWORD} (login.md)"
            )
        )
        if total_products < 70:
            raise CommandError(
                f"Esperado ≥ 70 produtos publicados; veio {total_products}."
            )
        if distinct_ceps < 20:
            raise CommandError(
                f"Esperado ≥ 20 CEPs distintos; veio {distinct_ceps}."
            )
