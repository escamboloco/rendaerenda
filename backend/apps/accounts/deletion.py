"""Exclusão de conta a pedido da titular (LGPD)."""
from __future__ import annotations

import hashlib
import logging

from django.contrib.auth import logout
from django.db import transaction
from django.utils import timezone

from apps.payments.models import Order
from apps.stores.models import Store

from .models import User

logger = logging.getLogger(__name__)

OPEN_ORDER_STATUSES = (
    Order.Status.AWAITING_PAYMENT,
    Order.Status.PAID,
    Order.Status.SHIPPED,
    Order.Status.DISPUTED,
)


class AccountDeletionError(Exception):
    """Erro de negócio ao excluir conta (senha, pedidos abertos…)."""


def account_has_open_orders(user: User) -> bool:
    as_buyer = Order.objects.filter(buyer=user, status__in=OPEN_ORDER_STATUSES).exists()
    if as_buyer:
        return True
    store = getattr(user, "store", None)
    if store:
        return Order.objects.filter(store=store, status__in=OPEN_ORDER_STATUSES).exists()
    return False


def _anon_cpf(user_id) -> str:
    digest = hashlib.sha256(f"deleted:{user_id}".encode()).hexdigest()
    digits = "".join(ch for ch in digest if ch.isdigit())
    return (digits + "00000000000")[:11]


@transaction.atomic
def delete_user_account(user: User, *, password: str, request=None) -> None:
    """
    Anonimiza a conta e desativa o login. Pedidos/NF históricos ficam
    com referência civil mínima para obrigação fiscal (CPF vira hash).
    """
    if not user.check_password(password):
        raise AccountDeletionError("Senha incorreta.")
    if account_has_open_orders(user):
        raise AccountDeletionError(
            "Há pedidos em andamento (pagamento, envio ou disputa). "
            "Conclua ou cancele antes de excluir a conta."
        )

    uid = str(user.id).replace("-", "")[:16]
    store = getattr(user, "store", None)
    if store and store.status not in {Store.Status.BANNED, Store.Status.SUSPENDED}:
        store.status = Store.Status.SUSPENDED
        store.pix_key = ""
        store.save(update_fields=["status", "pix_key"])

    user.email = f"deleted-{uid}@deleted.local"
    user.username = f"deleted-{uid}"
    user.public_alias = ""
    user.phone_number = ""
    user.is_phone_verified = False
    user.first_name = ""
    user.last_name = ""
    user.cpf = _anon_cpf(user.id)
    user.is_active = False
    user.is_banned = True
    user.banned_reason = "Conta excluída a pedido da titular (LGPD)."
    user.banned_at = timezone.now()
    user.set_unusable_password()
    user.save()

    logger.info("Conta %s anonimizada a pedido da titular.", uid)
    if request is not None:
        logout(request)
