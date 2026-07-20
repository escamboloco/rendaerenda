from datetime import timedelta
from decimal import Decimal

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone

from apps.payments.models import Order
from apps.payments.services import get_payment_provider
from apps.stores.models import Store

from .models import WalletEntry, WithdrawalRequest


# Teto de seguranca: se o rastreio nunca confirmar a entrega (extravio,
# transportadora sem atualizacao), o credito nao fica preso pra sempre -
# libera apos este prazo. Compativel com o maximo de 45 dias da conta
# escrow do Asaas.
RELEASE_SAFETY_CEILING_DAYS = 30


def credit_sale(order: Order):
    """
    Chamado quando o pagamento do pedido e confirmado (webhook do PSP).
    O credito fica RETIDO ate: (a) o comprador confirmar o recebimento,
    ou (b) passar DELIVERY_CONFIRMATION_WINDOW_HOURS da entrega sem
    contestacao - liberacao automatica via Celery beat (ver
    apps.shipping.tasks.release_confirmed_deliveries). docs/checkout.md.
    """
    available_at = timezone.now() + timedelta(days=RELEASE_SAFETY_CEILING_DAYS)
    return WalletEntry.objects.create(
        store=order.store,
        order=order,
        kind=WalletEntry.Kind.SALE_CREDIT,
        amount=order.seller_amount,
        available_at=available_at,
    )


def release_sale(order: Order):
    """Libera o credito da venda para saque imediato (confirmacao do comprador ou fim da janela)."""
    entry = order.wallet_entries.filter(kind=WalletEntry.Kind.SALE_CREDIT).first()
    if entry and entry.available_at > timezone.now():
        entry.available_at = timezone.now()
        entry.save(update_fields=["available_at"])


@transaction.atomic
def request_withdrawal(store: Store, amount: Decimal) -> WithdrawalRequest:
    # Anti-fraude/anti-lavagem: o saque SEMPRE vai para a chave Pix CPF da
    # propria dona da loja - nunca para chave de terceiro, e-mail ou
    # aleatoria. Nao e configuravel de proposito.
    pix_key = store.owner.cpf
    withdrawal = WithdrawalRequest(store=store, amount=amount, pix_key=pix_key)
    withdrawal.full_clean()  # dispara WithdrawalRequest.clean() -> valida saldo disponivel
    withdrawal.save()

    provider = get_payment_provider()
    try:
        transfer_id = provider.request_seller_withdrawal(
            seller_subaccount_id=store.psp_subaccount_id,
            amount=amount,
            pix_key=pix_key,
        )
    except Exception:
        withdrawal.status = WithdrawalRequest.Status.FAILED
        withdrawal.save(update_fields=["status"])
        raise

    withdrawal.provider_transfer_id = transfer_id
    withdrawal.status = WithdrawalRequest.Status.PROCESSING
    withdrawal.save(update_fields=["provider_transfer_id", "status"])

    WalletEntry.objects.create(
        store=store,
        kind=WalletEntry.Kind.WITHDRAWAL_DEBIT,
        amount=-amount,
        available_at=timezone.now(),
    )
    return withdrawal
