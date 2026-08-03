"""Regra de negócio do programa de embaixadoras — ver models.py para o schema."""
from __future__ import annotations

import re
from decimal import ROUND_HALF_UP, Decimal

from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.utils import timezone

from .models import Ambassador, AmbassadorProgram, Referral

REFERRAL_SESSION_KEY = "referral_code"
AMBASSADOR_INVITE_SESSION_KEY = "ambassador_program_invite"
_CODE_RE = re.compile(r"^[A-Za-z0-9-]{1,12}$")


def capture_referral_code(request) -> None:
    """
    Guarda `?ref=<código>` na sessão no primeiro toque.

    Só a forma é validada aqui (evita lixo na sessão); se o código não
    corresponder a nenhuma embaixadora, `attach_referral` simplesmente não
    cria a indicação — não vale a pena consultar o banco a cada clique em
    link de indicação só para validar cedo.
    """
    code = (request.GET.get("ref") or "").strip()
    if code and _CODE_RE.match(code) and not request.session.get(REFERRAL_SESSION_KEY):
        request.session[REFERRAL_SESSION_KEY] = code


def attach_referral(store, request) -> Referral | None:
    """
    Chamado na criação da loja (StoreOnboardView.post). Cria a indicação
    se a sessão tiver um código de embaixadora válido — silenciosamente
    ignora código inexistente, inativo, ou auto-indicação, para nunca
    quebrar o cadastro da vendedora por causa de um link de indicação
    velho ou malformado.
    """
    code = request.session.get(REFERRAL_SESSION_KEY)
    if not code:
        return None

    ambassador = Ambassador.objects.filter(referral_code__iexact=code, is_active=True).first()
    if ambassador is None or ambassador.store_id == store.id:
        return None
    if Referral.objects.filter(referred_store=store).exists():
        return None

    try:
        referral = Referral.objects.create(ambassador=ambassador, referred_store=store)
    except IntegrityError:
        # Corrida rara (duas abas criando a loja "ao mesmo tempo") — a
        # constraint de unicidade do OneToOne já resolveu, nada a fazer.
        return None

    request.session.pop(REFERRAL_SESSION_KEY, None)
    return referral


def capture_ambassador_invite(request) -> None:
    """Marca a sessão quando a vendedora chega pelo link de convite do programa."""
    request.session[AMBASSADOR_INVITE_SESSION_KEY] = True


def attach_ambassador_on_store_creation(store, request) -> "Ambassador | None":
    """
    Chamado logo após criar a loja (StoreOnboardView.post).

    Se a sessão tem a marca do convite, entra no programa automaticamente.
    Silenciosamente ignora se as vagas já foram preenchidas — o cadastro
    da loja nunca falha por causa disso; a vendedora vira cliente comum.
    """
    if not request.session.pop(AMBASSADOR_INVITE_SESSION_KEY, False):
        return None
    try:
        return join_ambassador_program(store)
    except ValidationError:
        return None


def join_ambassador_program(store) -> Ambassador:
    """
    Reivindica uma vaga para `store`, se houver. Transação curta com
    `select_for_update()` na linha singleton — é o que impede duas
    vendedoras ganharem a mesma vaga 20 clicando no mesmo instante.
    """
    if hasattr(store, "ambassador"):
        raise ValidationError("Esta loja já é embaixadora.")

    with transaction.atomic():
        program, _ = AmbassadorProgram.objects.select_for_update().get_or_create(pk=1)
        if program.is_full:
            raise ValidationError("As vagas do programa de embaixadoras já foram todas preenchidas.")

        seat_number = program.slots_taken + 1
        try:
            ambassador = Ambassador.objects.create(store=store, seat_number=seat_number)
        except IntegrityError:
            # Duplo clique na mesma loja: o hasattr() acima não pega quem
            # entrou entre a checagem e o lock. Sem isso vazaria um
            # IntegrityError cru em vez de uma mensagem tratável.
            raise ValidationError("Esta loja já é embaixadora.")
        program.slots_taken = seat_number
        program.save(update_fields=["slots_taken"])

    return ambassador


def referral_bonus_amount(order) -> Decimal | None:
    """
    Quanto (se algo) a embaixadora ganha por este pedido — 10% do valor
    da venda (`order.items_total`, o preço do item pago pelo comprador,
    sem frete), só se a loja que vendeu foi indicada e o pedido foi pago
    dentro da janela de 2 meses. Sem teto: soma normalmente em cada
    pedido novo, quantas vezes a loja indicada vender dentro da janela.

    Base de cálculo é o valor da venda, não o lucro da plataforma
    (`order.platform_amount`) — ver docs/checkout.md § 8. É bem mais
    generoso: com comissão padrão de 20%, isso consome a maior parte do
    lucro da plataforma naquele pedido durante a janela de bônus.

    Retorna None (não Decimal(0)) quando não há bônus, para o chamador
    nunca criar um WalletEntry de valor zero à toa.
    """
    referral = getattr(order.store, "referred_by", None)
    if referral is None or not referral.ambassador.is_active:
        return None
    moment = order.paid_at or timezone.now()
    if not referral.covers(moment):
        return None

    amount = (order.items_total * referral.bonus_percent / Decimal("100")).quantize(
        Decimal("0.01"), rounding=ROUND_HALF_UP
    )
    return amount if amount > 0 else None


def ambassador_dashboard_context(ambassador: Ambassador, request) -> dict:
    """Dados para a landing: link, extrato por indicada, total ganho."""
    from django.db.models import Sum

    from apps.wallet.models import WalletEntry

    now = timezone.now()
    rows = []
    total_earned = Decimal("0.00")
    for referral in ambassador.referrals.select_related("referred_store"):
        earned = (
            WalletEntry.objects.filter(
                store=ambassador.store,
                kind=WalletEntry.Kind.REFERRAL_BONUS,
                order__store=referral.referred_store,
            ).aggregate(total=Sum("amount"))["total"]
            or Decimal("0.00")
        )
        total_earned += earned
        rows.append(
            {
                "referral": referral,
                "store": referral.referred_store,
                "earned": earned,
                "days_left": max((referral.reward_expires_at - now).days, 0),
                "window_open": referral.covers(now),
            }
        )

    return {
        # Absoluta: é para ser colada fora do site (WhatsApp, X, DM) — um
        # caminho relativo não significa nada fora do próprio navegador.
        "referral_link": request.build_absolute_uri(ambassador.referral_path),
        "referral_code": ambassador.referral_code,
        "seat_number": ambassador.seat_number,
        "referrals": rows,
        "referred_count": len(rows),
        "total_earned": total_earned,
        "available_balance": WalletEntry.objects.available_balance(ambassador.store),
        "pending_balance": WalletEntry.objects.pending_balance(ambassador.store),
    }
