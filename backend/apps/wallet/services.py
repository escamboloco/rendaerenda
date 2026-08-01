"""
Carteira da vendedora: ledger interno + repasse Pix.

O ledger espelha o dinheiro que a vendedora tem a receber. O repasse em si
(Pix de verdade) sai pela conta Asaas — ver apps/payments/services.py.
Tudo aqui e idempotente: o webhook do Asaas repete entrega e o polling da
pagina de pagamento roda em paralelo, entao creditar/repassar duas vezes o
mesmo pedido significaria pagar duas vezes.
"""
from datetime import timedelta
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


def escrow_enabled() -> bool:
    return bool(getattr(settings, "ESCROW_ENABLED", True))


def _hold_until(order: Order):
    """
    Até quando o valor fica retido (custódia) se ninguém confirmar nada.

    Conteúdo digital é entregue na hora, então a janela é curta. Item
    físico segura até o teto de custódia — a liberação normal acontece
    antes disso, quando o comprador confirma o recebimento ou a janela
    pós-entrega vence (apps.shipping.tasks.release_confirmed_deliveries).
    """
    now = timezone.now()
    if not escrow_enabled():
        return now
    if order.is_digital_only:
        return now + timedelta(hours=int(getattr(settings, "DIGITAL_RELEASE_HOURS", 24)))
    return now + timedelta(days=int(getattr(settings, "ESCROW_MAX_HOLD_DAYS", 30)))


def credit_sale(order: Order) -> tuple[WalletEntry, bool]:
    """
    Registra o credito da venda no ledger. Com custódia ligada o valor
    entra RETIDO (available_at no futuro) — a vendedora vê o saldo, mas
    só saca depois da liberação. Retorna (entry, created); created=False
    quando o pedido já tinha sido creditado antes.
    """
    entry, created = WalletEntry.objects.get_or_create(
        order=order,
        kind=WalletEntry.Kind.SALE_CREDIT,
        defaults={
            "store": order.store,
            "amount": order.seller_amount,
            "available_at": _hold_until(order),
        },
    )
    return entry, created


def reverse_sale_credit(order: Order) -> bool:
    """
    Estorna o crédito da venda quando o pedido é reembolsado.

    Sem isso, um reembolso depois da confirmação deixaria o valor na
    carteira da vendedora — ela sacaria um dinheiro que voltou para quem
    comprou. Idempotente: só lança o ajuste uma vez.
    """
    credit = order.wallet_entries.filter(kind=WalletEntry.Kind.SALE_CREDIT).first()
    if not credit:
        return False
    already_reversed = order.wallet_entries.filter(
        kind=WalletEntry.Kind.ADJUSTMENT, amount=-credit.amount
    ).exists()
    if already_reversed:
        return False

    WalletEntry.objects.create(
        store=order.store,
        order=order,
        kind=WalletEntry.Kind.ADJUSTMENT,
        amount=-credit.amount,
        available_at=timezone.now(),
    )
    if order.payout_sent_at:
        # O Pix já saiu: o ajuste deixa o saldo negativo de propósito, para
        # aparecer na conciliação. Recuperar o valor é ação humana.
        logger.error(
            "Pedido %s reembolsado DEPOIS do repasse — saldo da loja %s ficou negativo, "
            "cobrança do valor precisa ser tratada manualmente.",
            order.id,
            order.store_id,
        )
    return True


def release_sale(order: Order) -> bool:
    """
    Tira o pedido da custódia: o saldo vira sacável agora. Idempotente —
    retorna True só na primeira vez.
    """
    entry = order.wallet_entries.filter(kind=WalletEntry.Kind.SALE_CREDIT).first()
    if not entry or entry.available_at <= timezone.now():
        return False
    entry.available_at = timezone.now()
    entry.save(update_fields=["available_at"])
    return True


def release_and_payout(order: Order) -> bool:
    """
    Liberação da custódia + Pix para a vendedora (se AUTO_PAYOUT_ON_RELEASE).
    Chamado quando o comprador confirma o recebimento ou quando a janela
    de contestação vence.
    """
    if not release_sale(order):
        return False
    if getattr(settings, "AUTO_PAYOUT_ON_RELEASE", True):
        _payout(order)
    return True


def credit_and_auto_payout(order: Order):
    """
    Chamado quando o pagamento confirma.

    Com custódia (padrão): só credita retido — a vendedora recebe depois
    da entrega confirmada. Sem custódia: dispara o Pix na hora.
      PF: o Pix sai da conta Asaas da plataforma (repasse).
      PJ: o valor já caiu na subconta pelo split; o Pix é o saque dela.
    """
    _, created = credit_sale(order)
    if not created:
        logger.info("Pedido %s ja havia sido creditado — repasse nao repetido.", order.id)
        return
    if escrow_enabled() or not getattr(settings, "AUTO_PAYOUT_ON_PAYMENT", False):
        return
    _payout(order)


def release_matured_escrow() -> int:
    """
    Repassa o que já saiu da custódia mas ainda não foi pago — cobre o
    conteúdo digital (que não tem entrega para confirmar) e qualquer
    liberação que tenha ficado sem o Pix por falha momentânea.
    Pedido em disputa nunca entra aqui.
    """
    matured = (
        WalletEntry.objects.filter(
            kind=WalletEntry.Kind.SALE_CREDIT,
            available_at__lte=timezone.now(),
            order__isnull=False,
            order__payout_sent_at__isnull=True,
            order__status__in=[Order.Status.PAID, Order.Status.SHIPPED, Order.Status.DELIVERED],
        )
        .select_related("order", "order__store")
    )
    paid = 0
    for entry in matured:
        _payout(entry.order)
        entry.order.refresh_from_db(fields=["payout_sent_at"])
        if entry.order.payout_sent_at:
            paid += 1
    return paid


def _payout(order: Order):
    """
    Pix para a vendedora. Idempotente por Order.payout_sent_at.

    A marca é gravada ANTES de chamar o PSP: se a resposta se perder no
    meio do caminho com o Pix já efetivado, tentar de novo seria pagar
    duas vezes. Falha confirmada volta para saque manual, com o saldo
    intacto na carteira dela (request_withdrawal estorna o débito).
    """
    store = order.store
    if not store.pix_key:
        logger.warning("Pedido %s: loja sem chave Pix — saldo fica na carteira.", order.id)
        return
    if asaas_uses_split() and not store.psp_subaccount_id:
        logger.warning("Pedido %s: loja sem subconta Asaas (modo PJ).", order.id)
        return

    with transaction.atomic():
        locked = Order.objects.select_for_update().get(pk=order.pk)
        if locked.payout_sent_at:
            logger.info("Pedido %s ja repassado — Pix nao repetido.", order.id)
            return
        locked.payout_sent_at = timezone.now()
        locked.save(update_fields=["payout_sent_at"])
    order.payout_sent_at = locked.payout_sent_at

    try:
        request_withdrawal(store, order.seller_amount, reference=f"pedido-{str(order.id)[:8]}")
    except Exception:
        logger.exception(
            "Falha no Pix do pedido %s — saldo continua disponivel para saque manual "
            "no painel da vendedora (repasse automatico nao sera repetido).",
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
