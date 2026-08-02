"""
Saque: a vendedora clica e o Pix sai da conta Asaas da plataforma.

O caminho do dinheiro saindo é o mais perigoso do sistema — estes testes
vigiam que só sai o que está liberado, só para a chave dela, e que uma
falha do PSP devolve o saldo em vez de sumir com ele.
"""
from decimal import Decimal
from unittest import mock

from django.test import override_settings
from django.urls import reverse
from django.utils import timezone

from apps.wallet.models import WalletEntry, WithdrawalRequest

from .base import ApiTestCase
from .factories import CPF_SELLER, FakeProvider, make_store, make_user


@override_settings(ASAAS_API_KEY="test-key")
class SaqueTests(ApiTestCase):
    def setUp(self):
        super().setUp()
        self.provider = FakeProvider()
        patcher = mock.patch("apps.payments.services.get_payment_provider", return_value=self.provider)
        patcher.start()
        self.addCleanup(patcher.stop)

        self.vendedora = make_user(role="seller", cpf=CPF_SELLER)
        self.loja = make_store(self.vendedora, pix_key=CPF_SELLER)
        self.url = reverse("wallet_api:withdrawal")
        self.client.force_login(self.vendedora)

    def _creditar(self, valor, *, liberado=True):
        return WalletEntry.objects.create(
            store=self.loja,
            kind=WalletEntry.Kind.SALE_CREDIT,
            amount=Decimal(valor),
            available_at=timezone.now() - timezone.timedelta(minutes=1)
            if liberado
            else timezone.now() + timezone.timedelta(days=3),
        )

    def sacar(self, valor):
        return self.client.post(self.url, {"amount": str(valor)}, content_type="application/json")

    # ------------------------------------------------------------- caminho ok

    def test_saque_dispara_pix_para_a_chave_dela(self):
        self._creditar("200.00")

        resposta = self.sacar("120.00")

        self.assertEqual(resposta.status_code, 201, resposta.content)
        self.assertEqual(len(self.provider.withdrawals), 1)
        pix = self.provider.withdrawals[0]
        self.assertEqual(pix["amount"], Decimal("120.00"))
        self.assertEqual(pix["pix_key"], CPF_SELLER)
        self.assertEqual(pix["pix_key_type"], "CPF")

    def test_saque_debita_o_saldo(self):
        self._creditar("200.00")

        self.sacar("120.00")

        self.assertEqual(
            WalletEntry.objects.available_balance(self.loja), Decimal("80.00")
        )

    def test_saque_fica_como_processando(self):
        self._creditar("200.00")

        self.sacar("50.00")

        saque = WithdrawalRequest.objects.get()
        self.assertEqual(saque.status, WithdrawalRequest.Status.PROCESSING)
        self.assertTrue(saque.provider_transfer_id)

    # ------------------------------------------------------------- as travas

    def test_nao_saca_mais_do_que_o_liberado(self):
        self._creditar("100.00")

        resposta = self.sacar("150.00")

        self.assertEqual(resposta.status_code, 400)
        self.assertEqual(self.provider.withdrawals, [])

    def test_valor_em_custodia_nao_pode_ser_sacado(self):
        """Retido é retido: só entra no saque depois de liberar."""
        self._creditar("300.00", liberado=False)

        resposta = self.sacar("50.00")

        self.assertEqual(resposta.status_code, 400)
        self.assertEqual(self.provider.withdrawals, [])

    def test_loja_sem_chave_pix_nao_saca(self):
        self.loja.pix_key = ""
        self.loja.save(update_fields=["pix_key"])
        self._creditar("100.00")

        resposta = self.sacar("50.00")

        self.assertEqual(resposta.status_code, 400)
        self.assertEqual(self.provider.withdrawals, [])

    def test_outra_pessoa_nao_saca_da_loja(self):
        self._creditar("100.00")
        self.client.force_login(make_user(role="buyer"))

        resposta = self.sacar("50.00")

        self.assertIn(resposta.status_code, (403, 404))
        self.assertEqual(self.provider.withdrawals, [])

    def test_anonimo_nao_saca(self):
        self.client.logout()

        self.assertIn(self.sacar("10.00").status_code, (401, 403))

    # ------------------------------------------------------- falha do PSP

    def test_falha_no_pix_devolve_o_saldo(self):
        """
        Se o Asaas recusa, o dinheiro não pode sumir: o débito é estornado
        e ela continua podendo tentar de novo.
        """
        self._creditar("100.00")

        def recusa(**kwargs):
            raise RuntimeError("Asaas fora do ar")

        self.provider.request_seller_withdrawal = recusa

        with self.assertRaises(RuntimeError):
            self.sacar("60.00")

        self.assertEqual(
            WalletEntry.objects.available_balance(self.loja), Decimal("100.00")
        )
        self.assertEqual(
            WithdrawalRequest.objects.get().status, WithdrawalRequest.Status.FAILED
        )
