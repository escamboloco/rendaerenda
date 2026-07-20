from django.conf import settings
from django.db import models
from django.utils import timezone


class SubscriptionPlan(models.Model):
    class Period(models.TextChoices):
        MONTHLY = "monthly", "Mensal"
        QUARTERLY = "quarterly", "Trimestral"
        YEARLY = "yearly", "Anual"

    name = models.CharField(max_length=50)
    period = models.CharField(max_length=10, choices=Period.choices)
    price = models.DecimalField(max_digits=8, decimal_places=2)
    is_featured = models.BooleanField(default=False)  # "mais popular"
    is_active = models.BooleanField(default=True)

    def __str__(self):
        return f"{self.name} ({self.get_period_display()})"


class BuyerSubscription(models.Model):
    """
    Assinatura mensal obrigatoria para o comprador desbloquear compra/
    contato com vendedoras. Renovada via Pix Automatico ou cobranca
    recorrente de cartao no PSP (apps.payments).
    """

    class Status(models.TextChoices):
        ACTIVE = "active", "Ativa"
        PAST_DUE = "past_due", "Em atraso"
        CANCELED = "canceled", "Cancelada"

    user = models.OneToOneField(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="subscription")
    plan = models.ForeignKey(SubscriptionPlan, on_delete=models.PROTECT, related_name="subscriptions")
    status = models.CharField(max_length=10, choices=Status.choices, default=Status.ACTIVE)
    current_period_end = models.DateTimeField()
    psp_subscription_id = models.CharField(max_length=100, blank=True)
    canceled_at = models.DateTimeField(null=True, blank=True)

    def can_purchase(self) -> bool:
        return self.status == self.Status.ACTIVE and self.current_period_end > timezone.now()
