import uuid

from django.db import models

from apps.payments.models import Order


class ShippingService(models.TextChoices):
    PAC = "pac", "PAC"
    SEDEX = "sedex", "SEDEX"
    SEDEX_10 = "sedex_10", "SEDEX 10"
    SEDEX_12 = "sedex_12", "SEDEX 12"


# Códigos de serviço da API dos Correios (contrato).
CORREIOS_SERVICE_CODES = {
    ShippingService.PAC: "03298",
    ShippingService.SEDEX: "03220",
    ShippingService.SEDEX_10: "03158",
    ShippingService.SEDEX_12: "03140",
}


class ShippingQuote(models.Model):
    """Cotação exibida no checkout - cacheada por 24h para não estourar limite da API."""

    origin_cep = models.CharField(max_length=8)
    destination_cep = models.CharField(max_length=8)
    weight_grams = models.PositiveIntegerField()
    service = models.CharField(max_length=10, choices=ShippingService.choices)
    price = models.DecimalField(max_digits=8, decimal_places=2)
    deadline_days = models.PositiveSmallIntegerField()
    quoted_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        indexes = [models.Index(fields=["origin_cep", "destination_cep", "weight_grams"])]


class Shipment(models.Model):
    class Status(models.TextChoices):
        AWAITING_POSTING = "awaiting_posting", "Aguardando postagem"
        POSTED = "posted", "Postado"
        IN_TRANSIT = "in_transit", "Em trânsito"
        DELIVERED = "delivered", "Entregue"
        RETURNED = "returned", "Devolvido"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    order = models.OneToOneField(Order, on_delete=models.CASCADE, related_name="shipment")
    # "pac"/"sedex" (Correios direto) ou "sf-<id>" (serviço cotado via
    # SuperFrete - Correios, Jadlog, Loggi etc.).
    service = models.CharField(max_length=20)
    tracking_code = models.CharField(max_length=40, blank=True)
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.AWAITING_POSTING)
    estimated_delivery_days = models.PositiveSmallIntegerField()
    posted_at = models.DateTimeField(null=True, blank=True)
    delivered_at = models.DateTimeField(null=True, blank=True)
    last_tracking_event = models.CharField(max_length=200, blank=True)
    last_tracking_check_at = models.DateTimeField(null=True, blank=True)

    # Identificador da etiqueta no integrador logístico. O provider separado
    # impede que registros antigos sejam consultados no integrador errado.
    shipping_provider = models.CharField(max_length=20, blank=True)
    provider_order_id = models.CharField(max_length=64, blank=True)
    label_url = models.URLField(max_length=500, blank=True)

    # Confirmacao de recebimento pelo comprador (docs/checkout.md): apos a
    # entrega ele tem DELIVERY_CONFIRMATION_WINDOW_HOURS para confirmar ou
    # contestar; sem acao, o saldo libera automaticamente (Celery beat).
    buyer_confirmed_at = models.DateTimeField(null=True, blank=True)
    buyer_disputed_at = models.DateTimeField(null=True, blank=True)
