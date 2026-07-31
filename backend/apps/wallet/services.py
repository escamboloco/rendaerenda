"""
Carteira da vendedora: ledger interno + repasse Pix.

O ledger espelha o dinheiro que a vendedora tem a receber. O repasse em si
(Pix de verdade) sai pela conta Asaas — ver apps/payments/services.py.
Tudo aqui e idempotente: o webhook do Asaas repete entrega e o polling da
pagina de pagamento roda em paralelo, entao creditar/repassar duas vezes o
mesmo pedido significaria pagar duas vezes.
"""
from decimal import Decimal
import logging

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone

from apps.payments.models import Order
from apps.payments import services as payment_services
from apps.payments.services import asaas_uses_split, detect_pix_key_type
from apps.stores.models import Store

from .models import WalletEntry, WithdrawalRequest

logger = logging.getLogger(__name__)


def credit_sale(order: Order) -> tuple[WalletEntry, bool]:
    """
    Registra o credito da venda no ledger. Retorna (entry, created) —
    created=False quando o pedido ja tinha sido creditado antes.
    """
    entry, created = WalletEntry.objects.get_or_create(
        order=order,
        kind=WalletEntry.Kind.SALE_CREDIT,
        defaults={
            "store": order.store,
            "amount": order.seller_amount,
            "available_at": timezone.now(),
        },
    )
    return entry, created


def release_sale(order: Order):
    """Libera credito retido (legado — no modelo atual o credito ja nasce liberado)."""
    entry = order.wallet_entries.filter(kind=WalletEntry.Kind.SALE_CREDIT).first()
    if entry and entry.available_at > timezone.now():
        entry.available_at = timezone.now()
        entry.save(update_fields=["available_at"])


def credit_and_auto_payout(order: Order):
    """
    Credita a venda e, se AUTO_PAYOUT_ON_PAYMENT, dispara o Pix para a
    vendedora na hora.
      PF: o Pix sai da conta Asaas da plataforma (repasse).
      PJ: o valor ja caiu na subconta pelo split; o Pix e o saque dela.
    """
    _, created = credit_sale(order)
    if not created:
        logger.info("Pedido %s ja havia sido creditado — repasse nao repetido.", order.id)
        return
    if not getattr(settings, "AUTO_PAYOUT_ON_PAYMENT", True):
        return

    store = order.store
    if not store.pix_key:
        logger.warning("Pedido %s: loja sem chave Pix — valor retido na conta Asaas.", order.id)
        return
    if asaas_uses_split() and not store.psp_subaccount_id:
        logger.warning("Pedido %s: loja sem subconta Asaas (modo PJ).", order.id)
        return

    try:
        request_withdrawal(store, order.seller_amount, reference=f"pedido-{str(order.id)[:8]}")
    except Exception:
        logger.exception(
            "Falha no Pix automatico do pedido %s — saldo fica na carteira para saque manual.",
            order.id,
        )


def _create_withdrawal_record(store: Store, amount: Decimal, pix_key: str) -> WithdrawalRequest:
    """Transacao curta: valida saldo e ja reserva o valor com o debito no ledger."""
    with transaction.atomic():
        withdrawal = WithdrawalRequest(store=store, amount=amount, pix_key=pix_key)
        withdrawal.full_clean()
        withdrawal.save()
        # Debito lancado junto com a criacao: sem isso, dois saques
        # simultaneos passariam os dois pela checagem de saldo.
        WalletEntry.objects.create(
            store=store,
            kind=WalletEntry.Kind.WITHDRAWAL_DEBIT,
            amount=-amount,
            available_at=timezone.now(),
        )
        return withdrawal


def request_withdrawal(store: Store, amount: Decimal, *, reference: str = "") -> WithdrawalRequest:
    """
    Saque Pix. O registro e o debito no ledger sao gravados primeiro; a
    chamada ao PSP acontece depois, fora da transacao (nunca segurar lock
    de banco esperando rede). Se o Pix falhar, o debito e estornado.
    """
    pix_key = (store.pix_key or "").strip()
    if not pix_key:
        raise ValidationError("Cadastre uma chave Pix na loja antes de sacar.")
    pix_type = (store.pix_key_type or detect_pix_key_type(pix_key)).upper()

    withdrawal = _create_withdrawal_record(store, amount, pix_key)

    provider = payment_services.get_payment_provider()
    try:
        transfer_id = provider.request_seller_withdrawal(
            seller_subaccount_id=store.psp_subaccount_id,
            amount=amount,
            pix_key=pix_key,
            pix_key_type=pix_type,
            api_key=store.psp_api_key or None,
            reference=reference,
        )
    except Exception as exc:
        with transaction.atomic():
            withdrawal.status = WithdrawalRequest.Status.FAILED
            withdrawal.save(update_fields=["status"])
            # Estorna o debito — o dinheiro nao saiu da conta.
            WalletEntry.objects.create(
                store=store,
                kind=WalletEntry.Kind.ADJUSTMENT,
                amount=amount,
                available_at=timezone.now(),
            )
        logger.error(
            "Saque %s falhou: %s",
            withdrawal.id,
            getattr(exc, "user_message", None) or exc.__class__.__name__,
        )
        raise

    withdrawal.provider_transfer_id = transfer_id
    withdrawal.status = WithdrawalRequest.Status.PROCESSING
    withdrawal.save(update_fields=["provider_transfer_id", "status"])
    return withdrawal
