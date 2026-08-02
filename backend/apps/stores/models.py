import uuid
from decimal import Decimal

from django.conf import settings
from django.db import models
from django.utils import timezone

# Peso minimo de "confianca" na media bayesiana (apps.reviews.services) -
# quanto maior, mais avaliacoes uma loja precisa pra nota dela pesar tanto
# quanto a media global. Evita que 1 avaliacao 5 estrelas dispare uma loja
# nova pro topo do ranking.
RATING_BAYESIAN_MIN_VOTES = 5


class StorePlan(models.Model):
    """
    Plano PAGO opcional (ex.: destaque permanente, limite maior de
    anúncios). Abrir e manter a loja é GRATUITO por padrão - Store.plan
    fica null enquanto a vendedora não assina nenhum plano pago (ver
    docs/checkout.md, mudança de modelo de negócio).
    """

    name = models.CharField(max_length=50)
    price = models.DecimalField(max_digits=8, decimal_places=2)
    duration_days = models.PositiveIntegerField(default=30)
    is_active = models.BooleanField(default=True)

    def __str__(self):
        return f"{self.name} - R${self.price}"


class Store(models.Model):
    class Status(models.TextChoices):
        PENDING_MODERATION = "pending", "Aguardando moderação"
        ACTIVE = "active", "Ativa"
        SUSPENDED = "suspended", "Suspensa"
        BANNED = "banned", "Banida"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    owner = models.OneToOneField(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="store")
    slug = models.SlugField(max_length=60, unique=True)
    display_name = models.CharField(max_length=80)
    bio = models.TextField(max_length=500, blank=True)
    status = models.CharField(max_length=10, choices=Status.choices, default=Status.PENDING_MODERATION)
    # null = loja no plano gratuito (padrão) - anunciar não custa nada.
    plan = models.ForeignKey(StorePlan, on_delete=models.PROTECT, related_name="stores", null=True, blank=True)
    plan_expires_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    # Subconta Asaas (walletId) que recebe o split de cada venda.
    psp_subaccount_id = models.CharField(max_length=100, blank=True)
    # apiKey da subconta (retornada na criacao) — usada pro Pix automatico.
    psp_api_key = models.CharField(max_length=200, blank=True)
    # Chave Pix cadastrada pela vendedora (CPF, e-mail, telefone ou aleatoria).
    pix_key = models.CharField(max_length=140, blank=True)
    pix_key_type = models.CharField(
        max_length=10,
        blank=True,
        default="CPF",
        help_text="CPF, CNPJ, EMAIL, PHONE ou EVP (chave aleatoria).",
    )
    # CEP de onde a vendedora posta os itens - usado como origem em TODA
    # cotacao de frete (o comprador ve preco/prazo reais a partir daqui) e
    # para achar o ponto de coleta mais proximo dela.
    origin_cep = models.CharField(max_length=8, blank=True)
    # Endereço de postagem privado. É usado como endereço de retorno na
    # etiqueta; nunca aparece na vitrine pública.
    origin_street = models.CharField(max_length=120, blank=True)
    origin_number = models.CharField(max_length=20, blank=True)
    origin_complement = models.CharField(max_length=60, blank=True)
    origin_district = models.CharField(max_length=80, blank=True)
    origin_city = models.CharField(max_length=80, blank=True)
    origin_state = models.CharField(max_length=2, blank=True)

    # Metricas cacheadas (apps.reviews.services.recompute_store_rating /
    # apps.stores.services.increment_sales_count) - evita recalcular
    # agregados de todas as lojas a cada carregamento do ranking.
    avg_rating = models.DecimalField(max_digits=3, decimal_places=2, default=Decimal("0.00"))
    review_count = models.PositiveIntegerField(default=0)
    # Nota ajustada pelo volume de avaliacoes (media bayesiana) - e o
    # criterio principal do ranking, pra loja com poucas avaliacoes nao
    # furar na frente de lojas consolidadas.
    bayesian_rating = models.DecimalField(max_digits=3, decimal_places=2, default=Decimal("0.00"))
    sales_count = models.PositiveIntegerField(default=0)

    class Meta:
        indexes = [models.Index(fields=["status"])]

    def is_plan_active(self) -> bool:
        # Sem plano = gratuita, sempre ativa. Com plano pago, precisa estar
        # dentro da validade.
        if self.plan_id is None:
            return True
        return self.plan_expires_at is not None and self.plan_expires_at > timezone.now()

    def is_public(self) -> bool:
        # So aparece publicamente se ativa, moderada e com plano em dia.
        return self.status == self.Status.ACTIVE and self.is_plan_active()


class BoostPackage(models.Model):
    name = models.CharField(max_length=50)
    price = models.DecimalField(max_digits=8, decimal_places=2)
    duration_hours = models.PositiveIntegerField(default=24)

    def __str__(self):
        return f"{self.name} ({self.duration_hours}h) - R${self.price}"


class StoreBoost(models.Model):
    store = models.ForeignKey(Store, on_delete=models.CASCADE, related_name="boosts")
    package = models.ForeignKey(BoostPackage, on_delete=models.PROTECT)
    starts_at = models.DateTimeField(default=timezone.now)
    ends_at = models.DateTimeField()
    paid = models.BooleanField(default=False)

    class Meta:
        indexes = [models.Index(fields=["ends_at"])]

    @property
    def is_active(self) -> bool:
        return self.paid and self.starts_at <= timezone.now() <= self.ends_at


class StoreFollow(models.Model):
    """
    Comprador segue a loja para voltar nela (novidades / vitrine).
    Não envia e-mail sozinho — serve de base para digest futuro.
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    store = models.ForeignKey(Store, on_delete=models.CASCADE, related_name="followers")
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="followed_stores"
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["store", "user"], name="store_follow_unique"),
        ]
        indexes = [models.Index(fields=["-created_at"])]
