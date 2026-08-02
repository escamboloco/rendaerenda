from django.core.cache import cache
from django.test import TestCase


class ApiTestCase(TestCase):
    """
    Base dos testes de API.

    O throttling do DRF guarda o historico no cache; como o cache local
    sobrevive entre testes do mesmo processo, sem limpar aqui um teste
    derruba o outro com HTTP 429.
    """

    def setUp(self):
        super().setUp()
        cache.clear()
