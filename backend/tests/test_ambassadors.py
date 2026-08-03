"""
Programa de embaixadoras: vaga limitada, link de indicação, bônus sobre
vendas da loja indicada, e a distinção "bônus de venda indicada" (nunca
"comissão da plataforma") pedida em docs/checkout.md § 8.
"""
from datetime import date, timedelta
from decimal import Decimal

from django.contrib.sessions.middleware import SessionMiddleware
from django.core.exceptions import ValidationError
from django.test import RequestFactory, override_settings
from django.urls import reverse
from django.utils import timezone

from apps.accounts.models import SellerKYC, User
from apps.ambassadors.models import Ambassador, AmbassadorProgram, Referral
from apps.ambassadors.services import (
    attach_referral,
    capture_referral_code,
    join_ambassador_program,
    referral_bonus_amount,
)
from apps.payments.models import Order
from apps.wallet.models import WalletEntry
from apps.wallet.services import credit_sale, release_sale, reverse_sale_credit

from .base import ApiTestCase
from .factories import CPF_SELLER, make_product, make_store, make_user


def _request_with_session(path="/vender/", **get_params):
    request = RequestFactory().get(path, get_params)
    SessionMiddleware(lambda r: None).process_request(request)
    request.session.save()
    return request


def make_order(store, *, payout=Decimal("100.00"), paid_at=None):
    """Pedido pago mínimo, para exercitar credit_sale/reverse_sale_credit."""
    product = make_product(store, payout=payout, slug=f"item-{store.pk}")
    order = Order.objects.create(
        access_token=f"tok-{product.id}",
        store=store,
        status=Order.Status.PAID,
        items_total=product.price,
        paid_at=paid_at or timezone.now(),
        guest_name="Compradora",
        guest_email="compradora@example.com",
        guest_cpf="11144477735",
    )
    from apps.payments.models import OrderItem

    OrderItem.objects.create(
        order=order,
        product=product,
        unit_price=product.price,
        unit_payout_amount=product.payout_amount,
        quantity=1,
    )
    return order


class AmbassadorProgramSlotsTests(ApiTestCase):
    """As vagas são limitadas e travadas contra corrida."""

    @override_settings(AMBASSADOR_PROGRAM_MAX_SEATS=2)
    def test_only_the_configured_number_of_seats_can_be_claimed(self):
        first = join_ambassador_program(make_store(slug="loja-1"))
        second = join_ambassador_program(make_store(slug="loja-2"))
        self.assertEqual([first.seat_number, second.seat_number], [1, 2])

        with self.assertRaises(ValidationError):
            join_ambassador_program(make_store(slug="loja-3"))

    def test_a_store_cannot_join_twice(self):
        store = make_store()
        join_ambassador_program(store)
        with self.assertRaises(ValidationError):
            join_ambassador_program(store)

    def test_program_reports_seats_left(self):
        program = AmbassadorProgram.singleton()
        self.assertEqual(program.seats_left, program.max_seats)
        join_ambassador_program(make_store())
        program.refresh_from_db()
        self.assertEqual(program.seats_left, program.max_seats - 1)


class ReferralCaptureTests(ApiTestCase):
    """Captura do `?ref=` na sessão e vínculo na criação da loja."""

    def setUp(self):
        super().setUp()
        self.ambassador_store = make_store(slug="loja-embaixadora")
        self.ambassador = join_ambassador_program(self.ambassador_store)

    def test_valid_code_is_attached_at_store_creation(self):
        request = _request_with_session(ref=self.ambassador.referral_code)
        capture_referral_code(request)

        new_store = make_store(slug="loja-nova")
        referral = attach_referral(new_store, request)

        self.assertIsNotNone(referral)
        self.assertEqual(referral.ambassador, self.ambassador)
        self.assertEqual(new_store.referred_by, referral)

    def test_unknown_code_is_silently_ignored(self):
        request = _request_with_session(ref="CODIGO-INEXISTENTE")
        capture_referral_code(request)

        new_store = make_store(slug="loja-nova")
        self.assertIsNone(attach_referral(new_store, request))
        self.assertFalse(Referral.objects.filter(referred_store=new_store).exists())

    def test_inactive_ambassador_code_is_ignored(self):
        self.ambassador.is_active = False
        self.ambassador.save(update_fields=["is_active"])
        request = _request_with_session(ref=self.ambassador.referral_code)
        capture_referral_code(request)

        new_store = make_store(slug="loja-nova")
        self.assertIsNone(attach_referral(new_store, request))

    def test_self_referral_is_ignored(self):
        """A própria embaixadora clicando no próprio link não conta."""
        request = _request_with_session(ref=self.ambassador.referral_code)
        capture_referral_code(request)

        self.assertIsNone(attach_referral(self.ambassador_store, request))

    def test_a_store_can_only_be_referred_once(self):
        other_ambassador = join_ambassador_program(make_store(slug="loja-embaixadora-2"))
        new_store = make_store(slug="loja-nova")

        request = _request_with_session(ref=self.ambassador.referral_code)
        capture_referral_code(request)
        attach_referral(new_store, request)

        request_two = _request_with_session(ref=other_ambassador.referral_code)
        capture_referral_code(request_two)
        second_attempt = attach_referral(new_store, request_two)

        self.assertIsNone(second_attempt)
        self.assertEqual(Referral.objects.filter(referred_store=new_store).count(), 1)
        self.assertEqual(new_store.referred_by.ambassador, self.ambassador)

    def test_full_signup_flow_attaches_the_referral(self):
        """Ponta a ponta: GET com ?ref= guarda na sessão, POST de abrir loja vincula."""
        seller = User.objects.create_user(
            username="nova@example.com",
            email="nova@example.com",
            password="Senha-Forte-123!",
            cpf=CPF_SELLER,
            birth_date=date(1990, 1, 1),
        )
        SellerKYC.objects.create(user=seller, status=SellerKYC.Status.PENDING)
        self.client.force_login(seller)
        session = self.client.session
        session["age_gate_confirmed"] = True
        session.save()

        self.client.get(reverse("stores:sell"), {"ref": self.ambassador.referral_code})

        response = self.client.post(
            reverse("stores_api:onboard"),
            {
                "slug": "loja-da-nova",
                "display_name": "Loja da Nova",
                "origin_cep": "01310100",
                "origin_street": "Avenida Paulista",
                "origin_number": "1000",
                "origin_district": "Bela Vista",
                "origin_city": "São Paulo",
                "origin_state": "SP",
                "pix_key": CPF_SELLER,
            },
            content_type="application/json",
        )

        self.assertEqual(response.status_code, 201, response.content)
        new_store = seller.store
        self.assertTrue(Referral.objects.filter(referred_store=new_store, ambassador=self.ambassador).exists())


@override_settings(AMBASSADOR_REVENUE_SHARE_PERCENT=Decimal("10"), PLATFORM_COMMISSION_PERCENT=Decimal("20"))
class ReferralBonusLedgerTests(ApiTestCase):
    """O bônus entra na carteira DA EMBAIXADORA, com a mesma custódia do crédito de venda."""

    def setUp(self):
        super().setUp()
        self.ambassador_store = make_store(slug="loja-embaixadora")
        self.ambassador = join_ambassador_program(self.ambassador_store)
        self.referred_store = make_store(slug="loja-indicada")
        self.referral = Referral.objects.create(
            ambassador=self.ambassador, referred_store=self.referred_store
        )

    def test_bonus_is_ten_percent_of_the_sale_value(self):
        order = make_order(self.referred_store, payout=Decimal("100.00"))
        # items_total = 120 (comissão 20% por cima do payout) -> bônus = 10% de 120 = 12.00
        self.assertEqual(referral_bonus_amount(order), Decimal("12.00"))

    def test_bonus_is_based_on_the_sale_value_not_the_platform_commission(self):
        """
        A base é items_total (o que a compradora paga pelo item), não
        platform_amount (a comissão da plataforma) — com comissão 20%,
        10% do valor da venda é mais da metade da comissão, não uma fração dela.
        """
        order = make_order(self.referred_store, payout=Decimal("100.00"))
        self.assertEqual(referral_bonus_amount(order), order.items_total * Decimal("10") / Decimal("100"))
        self.assertNotEqual(
            referral_bonus_amount(order), order.platform_amount * Decimal("10") / Decimal("100")
        )

    def test_credit_sale_credits_the_ambassadors_own_wallet(self):
        order = make_order(self.referred_store, payout=Decimal("100.00"))

        credit_sale(order)

        bonus = WalletEntry.objects.get(order=order, kind=WalletEntry.Kind.REFERRAL_BONUS)
        self.assertEqual(bonus.store, self.ambassador_store)
        self.assertEqual(bonus.amount, Decimal("12.00"))
        # Retido junto com o crédito da venda — não sacável na hora.
        sale_credit = WalletEntry.objects.get(order=order, kind=WalletEntry.Kind.SALE_CREDIT)
        self.assertEqual(bonus.available_at, sale_credit.available_at)

    def test_no_referral_means_no_bonus(self):
        lone_store = make_store(slug="loja-sem-indicacao")
        order = make_order(lone_store)

        credit_sale(order)

        self.assertFalse(WalletEntry.objects.filter(order=order, kind=WalletEntry.Kind.REFERRAL_BONUS).exists())

    def test_sale_outside_the_reward_window_generates_no_bonus(self):
        self.referral.reward_expires_at = timezone.now() - timedelta(days=1)
        self.referral.save(update_fields=["reward_expires_at"])
        order = make_order(self.referred_store)

        credit_sale(order)

        self.assertFalse(WalletEntry.objects.filter(order=order, kind=WalletEntry.Kind.REFERRAL_BONUS).exists())

    def test_credit_sale_is_idempotent(self):
        order = make_order(self.referred_store)

        credit_sale(order)
        credit_sale(order)

        self.assertEqual(
            WalletEntry.objects.filter(order=order, kind=WalletEntry.Kind.REFERRAL_BONUS).count(), 1
        )

    def test_release_sale_releases_the_bonus_together(self):
        order = make_order(self.referred_store)
        credit_sale(order)

        release_sale(order)

        bonus = WalletEntry.objects.get(order=order, kind=WalletEntry.Kind.REFERRAL_BONUS)
        self.assertLessEqual(bonus.available_at, timezone.now())

    def test_refund_reverses_the_bonus_from_the_ambassadors_wallet(self):
        from django.db.models import Sum

        order = make_order(self.referred_store)
        credit_sale(order)
        bonus = WalletEntry.objects.get(order=order, kind=WalletEntry.Kind.REFERRAL_BONUS)

        reverse_sale_credit(order)

        adjustment = WalletEntry.objects.get(
            order=order, kind=WalletEntry.Kind.ADJUSTMENT, store=self.ambassador_store
        )
        self.assertEqual(adjustment.amount, -bonus.amount)
        # Soma o ledger bruto (disponível + em custódia) — mesmo padrão de
        # tests/test_dispute.py: reembolso zera o total, não só o disponível
        # (o bônus original ainda pode estar retido em custódia).
        total = WalletEntry.objects.filter(store=self.ambassador_store).aggregate(total=Sum("amount"))[
            "total"
        ]
        self.assertEqual(total or Decimal("0.00"), Decimal("0.00"))

    def test_deactivated_ambassador_stops_generating_new_bonuses(self):
        self.ambassador.is_active = False
        self.ambassador.save(update_fields=["is_active"])
        order = make_order(self.referred_store)

        credit_sale(order)

        self.assertFalse(WalletEntry.objects.filter(order=order, kind=WalletEntry.Kind.REFERRAL_BONUS).exists())


class AmbassadorLandingPageTests(ApiTestCase):
    def setUp(self):
        super().setUp()
        session = self.client.session
        session["age_gate_confirmed"] = True
        session.save()

    def test_anonymous_visitor_sees_the_public_teaser(self):
        response = self.client.get(reverse("ambassadors:landing"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Programa de embaixadoras")
        self.assertContains(response, 'name="robots" content="index, follow"')

    def test_seller_without_ambassador_seat_sees_the_join_button(self):
        store = make_store()
        self.client.force_login(store.owner)
        response = self.client.get(reverse("ambassadors:landing"))
        self.assertContains(response, "Quero ser embaixadora")

    def test_ambassador_sees_her_own_dashboard(self):
        store = make_store()
        ambassador = join_ambassador_program(store)
        self.client.force_login(store.owner)

        response = self.client.get(reverse("ambassadors:landing"))

        self.assertContains(response, ambassador.referral_code)
        self.assertContains(response, 'name="robots" content="noindex"')

    def test_join_view_claims_a_seat(self):
        store = make_store()
        self.client.force_login(store.owner)

        response = self.client.post(reverse("ambassadors_api:join"))

        self.assertEqual(response.status_code, 201, response.content)
        self.assertTrue(Ambassador.objects.filter(store=store).exists())

    def test_join_view_rejects_a_pending_store(self):
        from apps.stores.models import Store

        store = make_store()
        store.status = Store.Status.PENDING_MODERATION
        store.save(update_fields=["status"])
        self.client.force_login(store.owner)

        response = self.client.post(reverse("ambassadors_api:join"))

        self.assertEqual(response.status_code, 400)
        self.assertFalse(Ambassador.objects.filter(store=store).exists())

    @override_settings(AMBASSADOR_PROGRAM_MAX_SEATS=1)
    def test_join_view_returns_409_when_the_program_is_full(self):
        join_ambassador_program(make_store(slug="ja-embaixadora"))
        late_store = make_store(slug="chegou-depois")
        self.client.force_login(late_store.owner)

        response = self.client.post(reverse("ambassadors_api:join"))

        self.assertEqual(response.status_code, 409)
