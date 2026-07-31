"""
Repassa para a vendedora o que já saiu da custódia e ainda não foi pago.

Cobre principalmente conteúdo digital (não existe entrega física para
confirmar, então a liberação é por prazo) e qualquer repasse que tenha
ficado para trás por falha momentânea do PSP.

Roda de 30 em 30 minutos via Render Cron (ver render.yaml).
"""
from django.core.management.base import BaseCommand

from apps.wallet.services import release_matured_escrow


class Command(BaseCommand):
    help = "Paga por Pix os pedidos cuja custódia já venceu."

    def handle(self, *args, **options):
        paid = release_matured_escrow()
        self.stdout.write(self.style.SUCCESS(f"Repasses efetuados: {paid}"))
