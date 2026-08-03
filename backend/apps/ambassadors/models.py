"""
Programa de embaixadoras: as 20 primeiras vendedoras a entrar indicam a
loja de outras vendedoras com um link próprio e recebem um bônus sobre as
vendas de quem indicaram, pelos primeiros meses da loja indicada.

O valor recebido é lançado na carteira da embaixadora como bônus ligado às
vendas indicadas (ver apps.wallet.models.WalletEntry.Kind.REFERRAL_BONUS) —
nunca como repasse da comissão da plataforma. Ver docs/checkout.md § 8 para
o porquê dessa distinção (também precisa de validação de contador/advogado,
como todo o resto de docs/BASE_JURIDICA.md).
"""
import uuid
from datetime import timedelta
from decimal import Decimal

from django.conf import settings
from django.db import models
from django.utils import timezone
from django.utils.crypto import get_random_string

# Sem 0/O/1/I/L: código para ser lido em voz alta ou digitado sem ambiguidade.
_CODE_ALPHABET = "ABCDEFGHJKMNPQRSTUVWXYZ23456789"


def _generate_referral_code() -> str:
    return get_random_string(8, allowed_chars=_CODE_ALPHABET)


class AmbassadorProgram(models.Model):
    """
    Linha única (singleton) que controla as vagas do programa.

    Guardar a contagem aqui — em vez de só fazer `Ambassador.objects.count()`
    na hora de decidir se ainda há vaga — é o que permite travar a vaga com
    `select_for_update()` numa transação curta: duas vendedoras clicando
    "quero ser embaixadora" no mesmo segundo não podem as duas ganhar a
    vaga 20.
    """

    slots_taken = models.PositiveSmallIntegerField(default=0)

    class Meta:
        verbose_name = "Programa de embaixadoras"
        verbose_name_plural = "Programa de embaixadoras"

    def __str__(self):
        return f"{self.slots_taken}/{settings.AMBASSADOR_PROGRAM_MAX_SEATS} vagas preenchidas"

    @classmethod
    def singleton(cls) -> "AmbassadorProgram":
        obj, _ = cls.objects.get_or_create(pk=1)
        return obj

    @property
    def max_seats(self) -> int:
        return int(settings.AMBASSADOR_PROGRAM_MAX_SEATS)

    @property
    def seats_left(self) -> int:
        return max(self.max_seats - self.slots_taken, 0)

    @property
    def is_full(self) -> bool:
        return self.slots_taken >= self.max_seats


class Ambassador(models.Model):
    """
    Vendedora aceita no programa. Uma por loja — `store` é OneToOne porque
    não faz sentido a mesma loja ocupar duas vagas.
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    store = models.OneToOneField("stores.Store", on_delete=models.CASCADE, related_name="ambassador")
    referral_code = models.CharField(max_length=12, unique=True, default=_generate_referral_code)
    # Vaga 1 a 20, na ordem de entrada — é o que dá o selo "Embaixadora fundadora nº X".
    seat_number = models.PositiveSmallIntegerField(unique=True)
    is_active = models.BooleanField(
        default=True,
        help_text="Desativa sem apagar o histórico (ex.: loja banida) — os bônus já lançados continuam valendo.",
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["seat_number"]

    def __str__(self):
        return f"#{self.seat_number} {self.store.display_name} ({self.referral_code})"

    @property
    def referral_path(self) -> str:
        from django.urls import reverse

        return f"{reverse('stores:sell')}?ref={self.referral_code}"


class Referral(models.Model):
    """
    Uma loja nova que entrou pelo link de uma embaixadora. `referred_store`
    é OneToOne: cada loja só pode ter sido indicada por UMA embaixadora,
    e só uma vez — sem isso, reabrir o link depois criaria uma segunda
    indicação e duplicaria o bônus.
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    ambassador = models.ForeignKey(Ambassador, on_delete=models.CASCADE, related_name="referrals")
    referred_store = models.OneToOneField(
        "stores.Store", on_delete=models.CASCADE, related_name="referred_by"
    )
    created_at = models.DateTimeField(auto_now_add=True)
    # Janela de recompensa: só venda paga DENTRO deste prazo gera bônus.
    # "2 meses" tratado como dias corridos (60), no mesmo padrão de
    # DISPUTE_WINDOW_DAYS/ESCROW_MAX_HOLD_DAYS — não é mês de calendário.
    reward_expires_at = models.DateTimeField()

    class Meta:
        ordering = ["-created_at"]
        indexes = [models.Index(fields=["ambassador", "reward_expires_at"])]

    def __str__(self):
        return f"{self.referred_store.display_name} indicada por {self.ambassador.store.display_name}"

    def save(self, *args, **kwargs):
        if not self.reward_expires_at:
            days = int(settings.AMBASSADOR_REWARD_WINDOW_DAYS)
            self.reward_expires_at = timezone.now() + timedelta(days=days)
        super().save(*args, **kwargs)

    def covers(self, moment) -> bool:
        """A venda em `moment` ainda está dentro da janela de 2 meses?"""
        return moment <= self.reward_expires_at

    @property
    def bonus_percent(self) -> Decimal:
        return Decimal(settings.AMBASSADOR_REVENUE_SHARE_PERCENT)
