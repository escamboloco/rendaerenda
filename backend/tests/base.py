from django.core.cache import cache
from django.test import TestCase


class ApiTestCase(TestCase):
    """
    Base dos testes de API.

    O throttling do DRF guarda o historico no cache; como o cache local
    sobrevive entre testes do mesmo processo, sem limpar aqui um teste
    derruba o outro com HTTP 429.

    Confirma o age gate na sessão: a API pública exige +18 confirmado
    (apps.core.middleware.AgeGateMiddleware).
    """

    def setUp(self):
        super().setUp()
        cache.clear()
        session = self.client.session
        session["age_gate_confirmed"] = True
        session.save()
