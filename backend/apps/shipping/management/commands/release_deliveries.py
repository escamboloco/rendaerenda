from django.core.management.base import BaseCommand

from apps.shipping.tasks import release_confirmed_deliveries


class Command(BaseCommand):
    help = (
        "Libera o saldo da vendedora para entregas confirmadas pelo comprador "
        "ou com a janela de contestação vencida. Rodado via Render Cron Job."
    )

    def handle(self, *args, **options):
        release_confirmed_deliveries()
        self.stdout.write(self.style.SUCCESS("Saldos liberados."))
