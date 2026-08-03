"""
Porta de entrada do painel.

É a única tela do sistema que dá acesso a documento de identidade de
terceiro e ao dinheiro em custódia. Estes testes vigiam as três coisas
que importam: só equipe entra, a mensagem de erro não entrega o que
existe, e o `next` não vira redirecionamento para fora.
"""
from django.core.cache import cache
from django.test import override_settings
from django.urls import reverse

from .base import ApiTestCase
from .factories import make_user

SENHA = "senha-bem-forte-123"


def _staff():
    user = make_user(role="buyer")
    user.is_staff = True
    user.save(update_fields=["is_staff"])
    return user


class LoginDoPainelTests(ApiTestCase):
    def setUp(self):
        super().setUp()
        self.url = reverse("backoffice:login")
        cache.clear()

    def test_pagina_abre_sem_login(self):
        resposta = self.client.get(self.url)
        self.assertEqual(resposta.status_code, 200)
        self.assertContains(resposta, "Acesso restrito")

    def test_pagina_e_noindex(self):
        """Painel não pode aparecer em buscador."""
        resposta = self.client.get(self.url)
        self.assertContains(resposta, "noindex")
        # NÃO afirmar "no-referrer" aqui: isso já foi bug em produção — sem
        # Referer no POST em HTTPS, o Django rejeita o CSRF antes mesmo de
        # checar login. Ver test_backoffice.py::test_login_manda_referer_para_o_csrf_passar.

    def test_staff_entra_e_vai_para_o_painel(self):
        staff = _staff()

        resposta = self.client.post(self.url, {"email": staff.email, "password": SENHA})

        self.assertEqual(resposta.status_code, 302)
        self.assertEqual(resposta["Location"], reverse("backoffice:dashboard"))

    def test_usuario_comum_nao_entra(self):
        comum = make_user(role="seller")

        resposta = self.client.post(self.url, {"email": comum.email, "password": SENHA})

        self.assertEqual(resposta.status_code, 200)
        self.assertContains(resposta, "inválidos")
        self.assertEqual(self.client.get(reverse("backoffice:dashboard")).status_code, 302)

    def test_senha_errada_nao_entra(self):
        staff = _staff()

        resposta = self.client.post(self.url, {"email": staff.email, "password": "errada-errada"})

        self.assertContains(resposta, "inválidos")

    def test_mensagem_nao_revela_se_a_conta_existe(self):
        """Erro idêntico nos três casos — senão vira enumeração de contas."""
        staff = _staff()

        inexistente = self.client.post(
            self.url, {"email": "ninguem@example.com", "password": "qualquer-coisa"}
        )
        cache.clear()
        senha_errada = self.client.post(self.url, {"email": staff.email, "password": "outra-senha"})
        cache.clear()
        sem_permissao = self.client.post(
            self.url, {"email": make_user(role="buyer").email, "password": SENHA}
        )

        textos = {r.content.decode().split('rounded-xl px-3 py-2.5">')[1].split("</p>")[0].strip()
                  for r in (inexistente, senha_errada, sem_permissao)}
        self.assertEqual(len(textos), 1, f"mensagens diferentes vazam informação: {textos}")

    def test_conta_banida_nao_entra(self):
        staff = _staff()
        staff.ban("teste")

        resposta = self.client.post(self.url, {"email": staff.email, "password": SENHA})

        self.assertEqual(resposta.status_code, 200)

    def test_next_para_fora_do_site_e_ignorado(self):
        staff = _staff()

        resposta = self.client.post(
            self.url,
            {"email": staff.email, "password": SENHA, "next": "https://site-malicioso.example/"},
        )

        self.assertEqual(resposta["Location"], reverse("backoffice:dashboard"))

    def test_next_interno_e_respeitado(self):
        staff = _staff()
        destino = reverse("backoffice:finance")

        resposta = self.client.post(
            self.url, {"email": staff.email, "password": SENHA, "next": destino}
        )

        self.assertEqual(resposta["Location"], destino)

    def test_forca_bruta_trava_apos_cinco_tentativas(self):
        staff = _staff()

        for _ in range(6):
            resposta = self.client.post(self.url, {"email": staff.email, "password": "chute"})

        self.assertContains(resposta, "Muitas tentativas")

    def test_pagina_protegida_manda_para_a_porta_do_painel(self):
        """E não para o /admin/login/, que é outra porta com outras regras."""
        resposta = self.client.get(reverse("backoffice:finance"))

        self.assertEqual(resposta.status_code, 302)
        self.assertIn(reverse("backoffice:login"), resposta["Location"])

    def test_sair_encerra_a_sessao(self):
        staff = _staff()
        self.client.force_login(staff)

        self.client.post(reverse("backoffice:logout"))

        self.assertEqual(self.client.get(reverse("backoffice:dashboard")).status_code, 302)

    def test_sair_nao_aceita_get(self):
        """Logout por GET permite deslogar a equipe com um link/imagem."""
        self.client.force_login(_staff())

        self.assertEqual(self.client.get(reverse("backoffice:logout")).status_code, 405)


class TelasNovasTests(ApiTestCase):
    def setUp(self):
        super().setUp()
        self.client.force_login(_staff())

    def test_moderacao_disputas_e_contas_abrem(self):
        for nome in ("backoffice:moderation", "backoffice:disputes", "backoffice:people"):
            self.assertEqual(self.client.get(reverse(nome)).status_code, 200, nome)

    def test_busca_de_conta_encontra_por_cpf(self):
        alvo = make_user(role="seller")

        resposta = self.client.get(reverse("backoffice:people"), {"q": alvo.cpf})

        self.assertContains(resposta, alvo.email)

    def test_busca_vazia_nao_lista_todo_mundo(self):
        make_user(role="seller")

        resposta = self.client.get(reverse("backoffice:people"))

        self.assertEqual(len(resposta.context["usuarios"]), 0)
