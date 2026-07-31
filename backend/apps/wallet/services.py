from decimal import Decimal
import logging

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone

from apps.payments.models import Order
from apps.payments.services import asaas_uses_split, detect_pix_key_type, get_payment_provider
from apps.stores.models import Store

from .models import WalletEntry, WithdrawalRequest

logger = logging.getLogger(__name__)


def credit_sale(order: Order):
    """
    Registra credito no ledger. Com AUTO_PAYOUT_ON_PAYMENT o valor ja fica
    disponivel (saque imediato no mesmo webhook).
    """
    available_at = timezone.now()
    return WalletEntry.objects.create(
        store=order.store,
        order=order,
        kind=WalletEntry.Kind.SALE_CREDIT,
        amount=order.seller_amount,
        available_at=available_at,
    )


def release_sale(order: Order):
    """Libera credito retido (legado — modelo atual ja libera na hora)."""
    entry = order.wallet_entries.filter(kind=WalletEntry.Kind.SALE_CREDIT).first()
    if entry and entry.available_at > timezone.now():
        entry.available_at = timezone.now()
        entry.save(update_fields=["available_at"])


def credit_and_auto_payout(order: Order):
    """
    Credita a venda e dispara Pix pra vendedora.
    PF: Pix sai da conta Asaas da plataforma (repasse).
    PJ: Pix sai da subconta apos o split.
    """
    credit_sale(order)
    if not getattr(settings, "AUTO_PAYOUT_ON_PAYMENT", True):
        return
    store = order.store
    if not store.pix_key:
        logger.warning("Pedido %s: loja sem chave Pix — valor ficou na conta Asaas da plataforma.", order.id)
        return
    if asaas_uses_split() and not store.psp_subaccount_id:
        logger.warning("Pedido %s: loja sem subconta Asaas (modo PJ).", order.id)
        return
    try:
        request_withdrawal(store, order.seller_amount)
    except Exception:
        logger.exception(
            "Falha no Pix automatico do pedido %s — valor na conta Asaas (repasse manual no painel).",
            order.id,
        )


@transaction.atomic
def request_withdrawal(store: Store, amount: Decimal) -> WithdrawalRequest:
    pix_key = (store.pix_key or "").strip()
    if not pix_key:
        raise ValidationError("Cadastre uma chave Pix na loja antes de sacar.")
    pix_type = (store.pix_key_type or detect_pix_key_type(pix_key)).upper()

    withdrawal = WithdrawalRequest(store=store, amount=amount, pix_key=pix_key)
    withdrawal.full_clean()
    withdrawal.save()

    provider = get_payment_provider()
    try:
        transfer_id = provider.request_seller_withdrawal(
            seller_subaccount_id=store.psp_subaccount_id,
            amount=amount,
            pix_key=pix_key,
            pix_key_type=pix_type,
            api_key=store.psp_api_key or None,
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
