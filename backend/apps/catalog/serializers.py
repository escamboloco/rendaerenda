from decimal import Decimal

from rest_framework import serializers

from .models import Category, Product, price_from_payout

MAX_VIDEO_SIZE_BYTES = 50 * 1024 * 1024  # 50MB
MAX_IMAGE_SIZE_BYTES = 8 * 1024 * 1024  # 8MB
MAX_ASSET_SIZE_BYTES = 200 * 1024 * 1024  # 200MB por arquivo digital


def validate_video_file(file):
    """
    Checa a assinatura real do arquivo (magic bytes), não só a extensão/
    content-type declarado pelo navegador - mesmo padrão de segurança
    usado no restante do projeto para uploads.
    """
    head = file.read(12)
    file.seek(0)
    is_mp4_or_mov = head[4:8] == b"ftyp"
    is_webm_or_mkv = head[:4] == b"\x1a\x45\xdf\xa3"
    if not (is_mp4_or_mov or is_webm_or_mkv):
        raise serializers.ValidationError("Arquivo não parece ser um vídeo válido (use MP4, MOV ou WEBM).")
    if file.size > MAX_VIDEO_SIZE_BYTES:
        raise serializers.ValidationError("Vídeo muito grande (máximo 50MB).")


def validate_image_file(file):
    """Magic bytes de JPEG/PNG/WebP/GIF + limite de tamanho (não confiar no MIME do browser)."""
    head = file.read(12)
    file.seek(0)
    is_jpeg = head[:3] == b"\xff\xd8\xff"
    is_png = head[:8] == b"\x89PNG\r\n\x1a\n"
    is_webp = head[:4] == b"RIFF" and head[8:12] == b"WEBP"
    is_gif = head[:6] in (b"GIF87a", b"GIF89a")
    if not (is_jpeg or is_png or is_webp or is_gif):
        raise serializers.ValidationError(
            "Arquivo não parece ser uma imagem válida (use JPEG, PNG, WebP ou GIF)."
        )
    if file.size > MAX_IMAGE_SIZE_BYTES:
        raise serializers.ValidationError("Imagem muito grande (máximo 8MB).")


def validate_asset_file(file):
    if file.size > MAX_ASSET_SIZE_BYTES:
        raise serializers.ValidationError("Arquivo muito grande (máximo 200MB).")


class AddonInputSerializer(serializers.Serializer):
    """Adicional pago do anúncio, informado pela vendedora no formulário."""

    title = serializers.CharField(max_length=80)
    description = serializers.CharField(max_length=200, required=False, allow_blank=True, default="")
    payout_amount = serializers.DecimalField(max_digits=8, decimal_places=2, min_value=Decimal("1.00"))


class ProductCreateSerializer(serializers.Serializer):
    """
    A vendedora informa o payout_amount (quanto ELA quer receber). O
    preco publico e derivado no servidor (payout + comissao) - o front
    so mostra a previa, nunca manda o preco final.

    `kind` decide o resto do formulario: item fisico exige peso (tem
    frete e rastreio); conteudo digital exige pelo menos um arquivo e
    ignora peso/dimensoes.
    """

    title = serializers.CharField(max_length=120)
    description = serializers.CharField(max_length=2000)
    category_id = serializers.PrimaryKeyRelatedField(queryset=Category.objects.all())
    kind = serializers.ChoiceField(choices=Product.Kind.choices, default=Product.Kind.PHYSICAL)
    payout_amount = serializers.DecimalField(max_digits=8, decimal_places=2, min_value=Decimal("1.00"))
    weight_grams = serializers.IntegerField(min_value=0, max_value=30000, required=False, default=0)
    length_cm = serializers.IntegerField(min_value=1, max_value=100, default=16)
    width_cm = serializers.IntegerField(min_value=1, max_value=100, default=11)
    height_cm = serializers.IntegerField(min_value=1, max_value=100, default=5)
    production_days = serializers.IntegerField(min_value=0, max_value=90, required=False, default=0)
    stock = serializers.IntegerField(min_value=1, max_value=1000, default=1)
    images = serializers.ListField(
        child=serializers.ImageField(validators=[validate_image_file]),
        min_length=1,
        max_length=5,
        write_only=True,
    )
    # Vídeo do PRODUTO (mostrando/descrevendo o item, sem nudez/sexual) -
    # opcional, no máximo 2 por anúncio.
    videos = serializers.ListField(
        child=serializers.FileField(validators=[validate_video_file]),
        min_length=0, max_length=2, required=False, default=list, write_only=True,
    )
    # Arquivos entregues ao comprador em anúncio de conteúdo digital.
    assets = serializers.ListField(
        child=serializers.FileField(validators=[validate_asset_file]),
        min_length=0, max_length=10, required=False, default=list, write_only=True,
    )
    addons = AddonInputSerializer(many=True, required=False, default=list)

    def validate(self, attrs):
        kind = attrs.get("kind", Product.Kind.PHYSICAL)
        if kind == Product.Kind.PHYSICAL:
            if not attrs.get("weight_grams"):
                raise serializers.ValidationError(
                    {"weight_grams": "Informe o peso — é o que calcula o frete."}
                )
            if attrs["weight_grams"] < 10:
                raise serializers.ValidationError({"weight_grams": "Peso mínimo de 10g."})
        else:
            # Conteúdo digital não viaja: peso e dimensão não existem.
            attrs["weight_grams"] = 0
        if kind == Product.Kind.DIGITAL and not attrs.get("assets"):
            raise serializers.ValidationError(
                {"assets": "Anexe pelo menos um arquivo — é ele que o comprador recebe."}
            )
        return attrs


class ProductUpdateSerializer(serializers.Serializer):
    """
    Edição do anúncio pela vendedora.

    `kind` fica de fora de propósito: trocar item físico por digital muda
    frete, entrega e o que já foi combinado em pedidos abertos. Para isso,
    o caminho é criar outro anúncio.
    """

    title = serializers.CharField(max_length=120, required=False)
    description = serializers.CharField(max_length=2000, required=False)
    category_id = serializers.PrimaryKeyRelatedField(queryset=Category.objects.all(), required=False)
    payout_amount = serializers.DecimalField(
        max_digits=8, decimal_places=2, min_value=Decimal("1.00"), required=False
    )
    stock = serializers.IntegerField(min_value=0, max_value=1000, required=False)
    weight_grams = serializers.IntegerField(min_value=0, max_value=30000, required=False)
    production_days = serializers.IntegerField(min_value=0, max_value=90, required=False)

    def validate(self, attrs):
        if not attrs:
            raise serializers.ValidationError("Nada para alterar.")
        return attrs


class ProductPreviewSerializer(serializers.Serializer):
    payout_amount = serializers.DecimalField(max_digits=8, decimal_places=2, min_value=Decimal("1.00"))

    def to_representation(self, instance):
        payout = instance["payout_amount"]
        price = price_from_payout(payout)
        return {
            "payout_amount": str(payout),
            "buyer_price": str(price),
            "platform_commission": str(price - payout),
        }
