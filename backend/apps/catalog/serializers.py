from decimal import Decimal

from rest_framework import serializers

from .models import Category, Product, ProductImage, ProductVideo, price_from_payout

MAX_VIDEO_SIZE_BYTES = 50 * 1024 * 1024  # 50MB


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


class ProductCreateSerializer(serializers.Serializer):
    """
    A vendedora informa o payout_amount (quanto ELA quer receber). O
    preco publico e derivado no servidor (payout + comissao) - o front
    so mostra a previa, nunca manda o preco final.
    """

    title = serializers.CharField(max_length=120)
    description = serializers.CharField(max_length=2000)
    category_id = serializers.PrimaryKeyRelatedField(queryset=Category.objects.all())
    payout_amount = serializers.DecimalField(max_digits=8, decimal_places=2, min_value=Decimal("1.00"))
    weight_grams = serializers.IntegerField(min_value=10, max_value=30000)
    length_cm = serializers.IntegerField(min_value=1, max_value=100, default=16)
    width_cm = serializers.IntegerField(min_value=1, max_value=100, default=11)
    height_cm = serializers.IntegerField(min_value=1, max_value=100, default=5)
    stock = serializers.IntegerField(min_value=1, max_value=100, default=1)
    images = serializers.ListField(
        child=serializers.ImageField(), min_length=1, max_length=5, write_only=True
    )
    # Vídeo do PRODUTO (mostrando/descrevendo o item, sem nudez/sexual) -
    # opcional, no máximo 2 por anúncio.
    videos = serializers.ListField(
        child=serializers.FileField(validators=[validate_video_file]),
        min_length=0, max_length=2, required=False, default=list, write_only=True,
    )


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
