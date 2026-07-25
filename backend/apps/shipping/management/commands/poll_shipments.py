from django.core.management.base import BaseCommand

from apps.shipping.tasks import poll_active_shipments


class Command(BaseCommand):
    help = "Atualiza o rastreio dos envios em andamento (Correios/Melhor Envio). Rodado via Render Cron Job."

    def handle(self, *args, **options):
        poll_active_shipments()
        self.stdout.write(self.style.SUCCESS("Rastreio de envios atualizado."))
