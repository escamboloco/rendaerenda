import uuid
from decimal import Decimal, ROUND_HALF_UP

from django.conf import settings
from django.core.validators import MinValueValidator
from django.db import models

from apps.stores.models import Store


def _commission_multiplier() -> Decimal:
    return Decimal("1") + (Decimal(settings.PLATFORM_COMMISSION_PERCENT) / Decimal("100"))


def price_from_payout(payout_amount: Decimal) -> Decimal:
    """
    Preço exibido ao comprador = valor que a vendedora quer receber + comissão
    da plataforma (settings.PLATFORM_COMMISSION_PERCENT, 20% por padrão) por
    cima. A vendedora declara o LÍQUIDO que quer; o preço público é sempre
    derivado disso no servidor - nunca aceito direto do cliente.
    """
    return (payout_amount * _commission_multiplier()).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def payout_from_price(total_price: Decimal) -> Decimal:
    """Inverso de price_from_payout - usado quando o valor negociado (pedido personalizado) é o total que o comprador paga."""
    return (total_price / _commission_multiplier()).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


class Category(models.Model):
    name = models.CharField(max_length=60, unique=True)
    slug = models.SlugField(unique=True)

    class Meta:
        verbose_name_plural = "categories"

    def __str__(self):
        return self.name


class Product(models.Model):
    """
    Anuncio de item fisico usado. Nunca representa servico (encontro,
    programa, webcam) - so produto + midia do produto, conforme
    docs/BASE_JURIDICA.md secao 3. A fila de moderacao (apps.moderation)
    e obrigatoria antes de is_published virar True.
    """

    class Status(models.TextChoices):
        DRAFT = "draft", "Rascunho"
        PENDING_MODERATION = "pending", "Aguardando moderação"
        PUBLISHED = "published", "Publicado"
        REJECTED = "rejected", "Rejeitado"
        SOLD = "sold", "Vendido"
        REMOVED = "removed", "Removido"

    class Visibility(models.TextChoices):
        PUBLIC = "public", "Público"
        # Item criado a partir de um pedido personalizado aceito - nao
        # aparece na vitrine, so quem tem o link (o comprador que pediu).
        PRIVATE = "private", "Privado (pedido personalizado)"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    store = models.ForeignKey(Store, on_delete=models.CASCADE, related_name="products")
    category = models.ForeignKey(Category, on_delete=models.PROTECT, related_name="products")
    title = models.CharField(max_length=120)
    slug = models.SlugField(max_length=140)
    description = models.TextField(max_length=2000)
    # Valor LÍQUIDO que a vendedora quer receber - e o que ela digita ao
    # anunciar. `price` (o que o comprador ve e paga) e sempre recalculado
    # a partir daqui em save() - nunca editar `price` diretamente.
    payout_amount = models.DecimalField(
        max_digits=8, decimal_places=2, default=Decimal("1.00"),
        validators=[MinValueValidator(Decimal("1.00"))],
        help_text="Quanto você quer receber por este item (sem a comissão da plataforma).",
    )
    price = models.DecimalField(max_digits=8, decimal_places=2, validators=[MinValueValidator(Decimal("1.00"))])
    weight_grams = models.PositiveIntegerField(help_text="Necessário para cálculo de frete.")
    length_cm = models.PositiveSmallIntegerField(default=16)
    width_cm = models.PositiveSmallIntegerField(default=11)
    height_cm = models.PositiveSmallIntegerField(default=2)
    status = models.CharField(max_length=10, choices=Status.choices, default=Status.DRAFT)
    visibility = models.CharField(max_length=10, choices=Visibility.choices, default=Visibility.PUBLIC)
    # Quando o item nasce de um pedido personalizado, so este comprador
    # pode compra-lo (validado no checkout - apps.payments.serializers).
    reserved_for = models.ForeignKey(
        "accounts.User", on_delete=models.SET_NULL, null=True, blank=True, related_name="reserved_products"
    )
    stock = models.PositiveIntegerField(default=1)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = ("store", "slug")
        indexes = [models.Index(fields=["status"])]

    def save(self, *args, **kwargs):
        self.price = price_from_payout(self.payout_amount)
        super().save(*args, **kwargs)

    def is_available(self) -> bool:
        return self.status == self.Status.PUBLISHED and self.stock > 0 and self.store.is_public()


class ProductImage(models.Model):
    """
    Midia armazenada em bucket privado (S3-compativel), servida via URL
    assinada de curta duracao. Nunca link publico direto.
    """

    product = models.ForeignKey(Product, on_delete=models.CASCADE, related_name="images")
    file = models.ImageField(upload_to="products/%Y/%m/")
    is_cover = models.BooleanField(default=False)
    order = models.PositiveSmallIntegerField(default=0)

    class Meta:
        ordering = ["order"]


class ProductVideo(models.Model):
    """
    Vídeo OPCIONAL da vendedora mostrando/descrevendo o item - nunca
    conteúdo pornográfico ou sexual (é vídeo de PRODUTO, mesma linha
    vermelha de docs/BASE_JURIDICA.md § 3). Passa pela mesma fila de
    moderação humana que as fotos antes de ficar visível - a moderação
    automática de texto não analisa vídeo, então a revisão manual aqui
    é obrigatória (ver apps.moderation).
    """

    product = models.ForeignKey(Product, on_delete=models.CASCADE, related_name="videos")
    file = models.FileField(upload_to="products/videos/%Y/%m/")
    order = models.PositiveSmallIntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["order"]
