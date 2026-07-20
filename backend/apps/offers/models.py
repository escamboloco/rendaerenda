import uuid
from decimal import Decimal

from django.conf import settings
from django.core.validators import MinValueValidator
from django.db import models
from django.utils import timezone


class CustomOrderRequest(models.Model):
    """
    Pedido personalizado de ITEM FISICO: o comprador descreve o item e
    oferece um valor; a vendedora aceita, recusa ou faz contra-proposta.

    LINHA VERMELHA (docs/BASE_JURIDICA.md secao 3): pedido de servico
    (encontro, webcam, "conteudo sob encomenda" nao-fisico) e bloqueado
    na criacao pelos mesmos filtros da moderacao - o texto do pedido
    passa por run_automated_filters antes de chegar a vendedora.

    Fluxo de estados:
      PENDING   -> vendedora aceita  -> ACCEPTED (cria Product privado)
      PENDING   -> vendedora recusa  -> REJECTED
      PENDING   -> contra-proposta   -> COUNTERED
      COUNTERED -> comprador aceita  -> ACCEPTED (cria Product privado)
      COUNTERED / PENDING -> comprador cancela -> CANCELED
    O Product criado e privado (visibility=private) e reservado ao
    comprador (reserved_for) - a compra segue o checkout normal, com
    frete, split e todas as travas de CPF.
    """

    class Status(models.TextChoices):
        PENDING = "pending", "Aguardando resposta"
        COUNTERED = "countered", "Contra-proposta enviada"
        ACCEPTED = "accepted", "Aceito"
        REJECTED = "rejected", "Recusado"
        CANCELED = "canceled", "Cancelado"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    buyer = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="custom_order_requests"
    )
    store = models.ForeignKey("stores.Store", on_delete=models.CASCADE, related_name="custom_order_requests")

    title = models.CharField(max_length=120)
    description = models.TextField(
        max_length=2000, help_text="Descrição do ITEM FÍSICO desejado (cor, tamanho, tempo de uso...)."
    )
    offered_price = models.DecimalField(
        max_digits=8, decimal_places=2, validators=[MinValueValidator(Decimal("1.00"))]
    )

    counter_price = models.DecimalField(max_digits=8, decimal_places=2, null=True, blank=True)
    counter_message = models.CharField(max_length=500, blank=True)

    status = models.CharField(max_length=10, choices=Status.choices, default=Status.PENDING)
    # Product privado criado na aceitacao - e por ele que o comprador paga.
    product = models.OneToOneField(
        "catalog.Product", on_delete=models.SET_NULL, null=True, blank=True, related_name="custom_order_request"
    )
    created_at = models.DateTimeField(auto_now_add=True)
    responded_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        indexes = [
            models.Index(fields=["store", "status"]),
            models.Index(fields=["buyer", "status"]),
        ]
        ordering = ["-created_at"]

    @property
    def final_price(self) -> Decimal:
        return self.counter_price if self.counter_price is not None else self.offered_price

    def mark_responded(self):
        self.responded_at = timezone.now()
