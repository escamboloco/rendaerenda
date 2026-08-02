"""Retenta compra de etiquetas SuperFrete para pedidos pagos sem PDF."""
from django.core.management.base import BaseCommand

from apps.shipping.labels import buy_pending_labels


class Command(BaseCommand):
    help = "Compra etiquetas pendentes (pedidos pagos sem label_url)."

    def add_arguments(self, parser):
        parser.add_argument("--limit", type=int, default=30)

    def handle(self, *args, **options):
        stats = buy_pending_labels(limit=options["limit"])
        self.stdout.write(
            self.style.SUCCESS(
                f"Etiquetas: tentadas={stats['tried']} ok={stats['ok']} falha={stats['failed']}"
            )
        )
