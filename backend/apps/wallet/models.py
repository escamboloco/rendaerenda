import uuid
from decimal import Decimal

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models
from django.db.models import Sum
from django.utils import timezone

from apps.payments.models import Order


class WalletBalanceManager(models.Manager):
    def available_balance(self, store) -> Decimal:
        now = timezone.now()
        total = self.filter(store=store, available_at__lte=now).aggregate(total=Sum("amount"))["total"]
        return total or Decimal("0.00")

    def pending_balance(self, store) -> Decimal:
        now = timezone.now()
        total = self.filter(store=store, available_at__gt=now, kind=WalletEntry.Kind.SALE_CREDIT).aggregate(
            total=Sum("amount")
        )["total"]
        return total or Decimal("0.00")


class WalletEntry(models.Model):
    """
    Ledger interno (espelha o saldo real que ja esta na subconta da
    vendedora no PSP - nao e o dinheiro em si). Criada quando o
    pagamento e confirmado, mas so fica "disponivel para saque"
    (available_at) apos a entrega confirmada ou N dias apos o envio -
    ver settings.WALLET_RELEASE_DAYS_AFTER_SHIPPING. Isso reduz risco
    de calote/estorno sem tirar da vendedora o poder de sacar quando
    quiser depois de liberado.
    """

    class Kind(models.TextChoices):
        SALE_CREDIT = "sale_credit", "Crédito de venda"
        WITHDRAWAL_DEBIT = "withdrawal_debit", "Débito de saque"
        ADJUSTMENT = "adjustment", "Ajuste"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    store = models.ForeignKey("stores.Store", on_delete=models.PROTECT, related_name="wallet_entries")
    order = models.ForeignKey(Order, on_delete=models.SET_NULL, null=True, blank=True, related_name="wallet_entries")
    kind = models.CharField(max_length=20, choices=Kind.choices)
    amount = models.DecimalField(max_digits=10, decimal_places=2)  # positivo = credito, negativo = debito
    available_at = models.DateTimeField(help_text="A partir de quando pode ser sacado.")
    created_at = models.DateTimeField(auto_now_add=True)

    objects = WalletBalanceManager()

    class Meta:
        indexes = [models.Index(fields=["store", "available_at"])]
        constraints = [
            # Trava de dinheiro: um pedido so pode gerar UM credito de venda,
            # mesmo com webhook duplicado do PSP + polling rodando junto.
            models.UniqueConstraint(
                fields=["order", "kind"],
                condition=models.Q(kind="sale_credit"),
                name="wallet_unique_sale_credit_per_order",
            )
        ]


class WithdrawalRequest(models.Model):
    """Saque Pix a qualquer momento, qualquer valor <= saldo disponível."""

    class Status(models.TextChoices):
        PENDING = "pending", "Pendente"
        PROCESSING = "processing", "Processando"
        PAID = "paid", "Pago"
        FAILED = "failed", "Falhou"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    store = models.ForeignKey("stores.Store", on_delete=models.PROTECT, related_name="withdrawal_requests")
    amount = models.DecimalField(max_digits=10, decimal_places=2)
    pix_key = models.CharField(max_length=140)
    status = models.CharField(max_length=12, choices=Status.choices, default=Status.PENDING)
    provider_transfer_id = models.CharField(max_length=100, blank=True)
    requested_at = models.DateTimeField(auto_now_add=True)
    paid_at = models.DateTimeField(null=True, blank=True)

    def clean(self):
        available = WalletEntry.objects.available_balance(self.store)
        if self.amount <= 0:
            raise ValidationError("Valor de saque deve ser positivo.")
        if self.amount > available:
            raise ValidationError(f"Saldo disponível insuficiente (disponível: R${available}).")
