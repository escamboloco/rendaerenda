"""
Painel de gestão (/gestao/) e a regra "aprovou, a loja está no ar".

O que estes testes protegem: o painel é área interna (staff), a aprovação
de identidade não passa sem a data de nascimento do documento, e aprovar
libera a loja na mesma ação — sem depender de alguém lembrar de mexer no
admin depois.
"""
from datetime import date, timedelta
from decimal import Decimal

from django.urls import reverse
from django.utils import timezone

from apps.accounts.models import SellerKYC
from apps.stores.models import Store
from apps.wallet.models import WalletEntry

from .base import ApiTestCase
from .factories import make_product, make_store, make_user


def _kyc_enviado(user) -> SellerKYC:
    kyc, _ = SellerKYC.objects.get_or_create(user=user)
    kyc.status = SellerKYC.Status.PENDING
    kyc.submitted_at = timezone.now()
    kyc.save()
    return kyc


class AcessoAoPainelTests(ApiTestCase):
    """Área interna: nada aqui pode vazar para quem não é da equipe."""

    def setUp(self):
        super().setUp()
        self.rotas = [
            reverse("backoffice:dashboard"),
            reverse("backoffice:kyc_queue"),
            reverse("backoffice:finance"),
            reverse("backoffice:orders"),
            reverse("backoffice:stores"),
        ]

    def test_anonimo_nao_entra(self):
        """Sem sessão, toda rota do painel manda para a porta do painel."""
        login = reverse("backoffice:login")
        for rota in self.rotas:
            resposta = self.client.get(rota)
            self.assertEqual(resposta.status_code, 302, rota)
            self.assertEqual(resposta["Location"].split("?")[0], login, rota)

    def test_usuario_comum_nao_entra(self):
        self.client.force_login(make_user(role="buyer"))
        for rota in self.rotas:
            self.assertEqual(self.client.get(rota).status_code, 302, rota)

    def test_staff_entra(self):
        staff = make_user(role="buyer")
        staff.is_staff = True
        staff.save(update_fields=["is_staff"])
        self.client.force_login(staff)
        for rota in self.rotas:
            self.assertEqual(self.client.get(rota).status_code, 200, rota)

    def test_painel_nao_passa_pelo_age_gate(self):
        """Sem isenção, o middleware jogaria a equipe para a tela de idade."""
        staff = make_user(role="buyer")
        staff.is_staff = True
        staff.save(update_fields=["is_staff"])
        self.client.force_login(staff)

        resposta = self.client.get(reverse("backoffice:dashboard"))

        self.assertEqual(resposta.status_code, 200)
        self.assertNotContains(resposta, "maiores de 18")

    def test_painel_fica_fora_do_robots(self):
        self.assertContains(self.client.get("/robots.txt"), "Disallow: /gestao/")


class AprovacaoDeIdentidadeTests(ApiTestCase):
    def setUp(self):
        super().setUp()
        self.staff = make_user(role="buyer")
        self.staff.is_staff = True
        self.staff.save(update_fields=["is_staff"])
        self.client.force_login(self.staff)

        self.vendedora = make_user(role="seller")
        self.kyc = _kyc_enviado(self.vendedora)
        self.loja = make_store(self.vendedora)
        self.loja.status = Store.Status.PENDING_MODERATION
        self.loja.save(update_fields=["status"])
        self.url = reverse("backoffice:kyc_decide", args=[self.kyc.id])

    def test_aprovar_libera_a_loja_na_hora(self):
        self.client.post(self.url, {"acao": "aprovar", "document_birth_date": "1995-04-10"})

        self.kyc.refresh_from_db()
        self.loja.refresh_from_db()
        self.vendedora.refresh_from_db()
        self.assertEqual(self.kyc.status, SellerKYC.Status.APPROVED)
        self.assertEqual(self.loja.status, Store.Status.ACTIVE, "a loja tem que ir ao ar na aprovação")
        self.assertTrue(self.vendedora.is_age_verified)

    def test_aprovar_sem_data_do_documento_nao_passa(self):
        """Idade é exigência legal — não sai de um clique às cegas."""
        self.client.post(self.url, {"acao": "aprovar", "document_birth_date": ""})

        self.kyc.refresh_from_db()
        self.loja.refresh_from_db()
        self.assertEqual(self.kyc.status, SellerKYC.Status.PENDING)
        self.assertEqual(self.loja.status, Store.Status.PENDING_MODERATION)

    def test_documento_de_menor_bane_e_nao_libera(self):
        menor = (timezone.localdate() - timedelta(days=365 * 15)).isoformat()

        self.client.post(self.url, {"acao": "aprovar", "document_birth_date": menor})

        self.vendedora.refresh_from_db()
        self.loja.refresh_from_db()
        self.assertTrue(self.vendedora.is_banned)
        self.assertFalse(self.vendedora.is_age_verified)
        self.assertEqual(self.loja.status, Store.Status.PENDING_MODERATION)

    def test_reprovar_guarda_o_motivo_para_ela_ver(self):
        self.client.post(self.url, {"acao": "reprovar", "motivo": "Documento sem foco."})

        self.kyc.refresh_from_db()
        self.assertEqual(self.kyc.status, SellerKYC.Status.REJECTED)
        self.assertIn("foco", self.kyc.rejection_reason)

    def test_loja_ja_ativa_nao_e_alterada(self):
        self.loja.status = Store.Status.ACTIVE
        self.loja.save(update_fields=["status"])

        self.client.post(self.url, {"acao": "aprovar", "document_birth_date": "1990-01-01"})

        self.loja.refresh_from_db()
        self.assertEqual(self.loja.status, Store.Status.ACTIVE)

    def test_loja_suspensa_nao_volta_sozinha(self):
        """Suspensão é decisão de moderação: aprovar identidade não desfaz."""
        self.loja.status = Store.Status.SUSPENDED
        self.loja.save(update_fields=["status"])

        self.client.post(self.url, {"acao": "aprovar", "document_birth_date": "1990-01-01"})

        self.loja.refresh_from_db()
        self.assertEqual(self.loja.status, Store.Status.SUSPENDED)


class PainelMostraOperacaoTests(ApiTestCase):
    def setUp(self):
        super().setUp()
        self.staff = make_user(role="buyer")
        self.staff.is_staff = True
        self.staff.save(update_fields=["is_staff"])
        self.client.force_login(self.staff)

    def test_fila_de_identidade_aparece_na_visao_geral(self):
        _kyc_enviado(make_user(role="seller"))

        resposta = self.client.get(reverse("backoffice:dashboard"))

        self.assertContains(resposta, "identidade")
        self.assertEqual(resposta.context["filas"]["kyc"], 1)

    def test_loja_sem_pix_e_sinalizada(self):
        loja = make_store(pix_key="")
        loja.status = Store.Status.ACTIVE
        loja.save(update_fields=["status"])

        resposta = self.client.get(reverse("backoffice:dashboard"))

        self.assertEqual(resposta.context["filas"]["sem_pix"], 1)

    def test_custodia_aparece_separada_do_liberado(self):
        produto = make_product(payout=Decimal("100.00"))
        WalletEntry.objects.create(
            store=produto.store,
            kind=WalletEntry.Kind.SALE_CREDIT,
            amount=Decimal("100.00"),
            available_at=timezone.now() + timedelta(days=5),
        )

        resposta = self.client.get(reverse("backoffice:dashboard"))

        self.assertEqual(resposta.context["retido"], Decimal("100.00"))
        self.assertEqual(resposta.context["liberado_nao_sacado"], Decimal("0.00"))

    def test_financeiro_lista_o_que_esta_retido_com_a_data(self):
        produto = make_product()
        libera_em = timezone.now() + timedelta(days=3)
        WalletEntry.objects.create(
            store=produto.store,
            kind=WalletEntry.Kind.SALE_CREDIT,
            amount=Decimal("80.00"),
            available_at=libera_em,
        )

        resposta = self.client.get(reverse("backoffice:finance"))

        self.assertEqual(len(resposta.context["retidos"]), 1)
        self.assertContains(resposta, libera_em.strftime("%d/%m/%Y"))


class CarteiraMostraPrazoTests(ApiTestCase):
    """A vendedora precisa saber QUANDO o dinheiro cai, não só quanto."""

    def setUp(self):
        super().setUp()
        # /carteira/ é página pública do site e passa pelo age gate.
        sessao = self.client.session
        sessao["age_gate_confirmed"] = True
        sessao.save()

    def test_dashboard_mostra_data_de_liberacao(self):
        vendedora = make_user(role="seller")
        loja = make_store(vendedora)
        libera_em = timezone.now() + timedelta(days=4)
        WalletEntry.objects.create(
            store=loja,
            kind=WalletEntry.Kind.SALE_CREDIT,
            amount=Decimal("120.00"),
            available_at=libera_em,
        )
        self.client.force_login(vendedora)

        resposta = self.client.get(reverse("wallet:dashboard"))

        self.assertEqual(resposta.status_code, 200)
        self.assertContains(resposta, "até quando")
        self.assertContains(resposta, libera_em.strftime("%d/%m/%Y"))

    def test_sem_valor_retido_a_secao_some(self):
        vendedora = make_user(role="seller")
        make_store(vendedora)
        self.client.force_login(vendedora)

        self.assertNotContains(self.client.get(reverse("wallet:dashboard")), "até quando")
