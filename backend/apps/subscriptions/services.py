from datetime import timedelta
from decimal import Decimal

from django.utils import timezone

from apps.payments.services import ChargeResult, get_payment_provider

from .models import BuyerSubscription, SubscriptionPlan

PERIOD_DAYS = {
    SubscriptionPlan.Period.MONTHLY: 30,
    SubscriptionPlan.Period.QUARTERLY: 90,
    SubscriptionPlan.Period.YEARLY: 365,
}


def start_or_renew_subscription(user, plan: SubscriptionPlan, method: str) -> ChargeResult:
    """
    Dispara a cobranca (sem split - 100% plataforma) do plano escolhido.
    A assinatura so vira ACTIVE quando o webhook do PSP confirmar o
    pagamento (ver activate_subscription), pois Pix/boleto nao confirmam
    na hora.
    """
    provider = get_payment_provider()
    charge = provider.create_charge(
        reference_id=f"subscription:{user.id}",
        method=method,
        amount=plan.price,
        customer_cpf=user.cpf,
        customer_name=user.get_full_name() or user.username,
        customer_email=user.email,
    )
    BuyerSubscription.objects.update_or_create(
        user=user,
        defaults={
            "plan": plan,
            "status": BuyerSubscription.Status.PAST_DUE,
            "current_period_end": timezone.now(),
            "psp_subscription_id": charge.provider_charge_id,
        },
    )
    return charge


def activate_subscription(psp_subscription_id: str) -> BuyerSubscription | None:
    try:
        subscription = BuyerSubscription.objects.select_related("plan").get(
            psp_subscription_id=psp_subscription_id
        )
    except BuyerSubscription.DoesNotExist:
        return None

    # Idempotente: webhook duplicado (RECEIVED + CONFIRMED) não estende o prazo.
    if (
        subscription.status == BuyerSubscription.Status.ACTIVE
        and subscription.current_period_end
        and subscription.current_period_end > timezone.now()
    ):
        return subscription

    days = PERIOD_DAYS[subscription.plan.period]
    subscription.status = BuyerSubscription.Status.ACTIVE
    subscription.current_period_end = timezone.now() + timedelta(days=days)
    subscription.save(update_fields=["status", "current_period_end"])

    # NFS-e do servico de assinatura + e-mail com o link (assincrono).
    from apps.payments.tasks import emit_invoice_for_subscription

    emit_invoice_for_subscription.delay(
        str(subscription.user_id), str(subscription.plan.price), psp_subscription_id
    )
    return subscription


def cancel_subscription(subscription: BuyerSubscription) -> None:
    subscription.status = BuyerSubscription.Status.CANCELED
    subscription.canceled_at = timezone.now()
    subscription.save(update_fields=["status", "canceled_at"])
