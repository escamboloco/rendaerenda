"""
Dispara o digest de novidades para assinantes com opt-in.

Uso:
    python manage.py send_marketing_digest
    python manage.py send_marketing_digest --days=7 --dry-run
"""
from django.core.management.base import BaseCommand

from apps.core.marketing import send_marketing_digest


class Command(BaseCommand):
    help = "Envia e-mail marketing periodico (novos anuncios / oportunidades)."

    def add_arguments(self, parser):
        parser.add_argument("--days", type=int, default=7)
        parser.add_argument("--dry-run", action="store_true")

    def handle(self, *args, **options):
        sent = send_marketing_digest(days=options["days"], dry_run=options["dry_run"])
        label = "seriam enviados" if options["dry_run"] else "enviados"
        self.stdout.write(self.style.SUCCESS(f"{sent} e-mails {label}."))
