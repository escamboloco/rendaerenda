"""
Gera o link de convite único para o programa de embaixadoras.

O mesmo link serve para todas as 20 vagas — as primeiras 20 lojas
criadas por esse link ganham o status de embaixadora automaticamente.

Uso (Render Shell ou local):
    python manage.py gerar_convite_embaixadoras
    python manage.py gerar_convite_embaixadoras --days 14   # expira em 14 dias
    python manage.py gerar_convite_embaixadoras --base-url https://rendaerenda.com.br

Copie o link impresso e envie diretamente para as candidatas (WhatsApp, DM).
"""
from django.conf import settings
from django.core.management.base import BaseCommand
from django.core.signing import TimestampSigner

from apps.ambassadors.models import AmbassadorProgram

_SIGNER = TimestampSigner(salt="ambassador-invite")
_PAYLOAD = "ambassador-program"


class Command(BaseCommand):
    help = "Gera o link de convite para o programa de embaixadoras fundadoras."

    def add_arguments(self, parser):
        parser.add_argument(
            "--days",
            type=int,
            default=30,
            help="Validade do link em dias (padrão: 30).",
        )
        parser.add_argument(
            "--base-url",
            dest="base_url",
            default=None,
            help="URL base do site (padrão: lê SITE_DOMAIN das settings).",
        )

    def handle(self, *args, **options):
        program = AmbassadorProgram.singleton()
        if program.is_full:
            self.stdout.write(self.style.ERROR(
                f"Programa lotado: {program.slots_taken}/{program.max_seats} vagas preenchidas."
            ))
            return

        token = _SIGNER.sign(_PAYLOAD)
        base = (options["base_url"] or f"https://{settings.SITE_DOMAIN}").rstrip("/")
        link = f"{base}/embaixadoras/convite/{token}/"
        days = options["days"]

        self.stdout.write(self.style.SUCCESS(
            f"\n✓ Link de convite gerado (válido por {days} dias):\n"
            f"\n  {link}\n"
            f"\n  Vagas restantes: {program.seats_left}/{program.max_seats}"
            f"\n\nEnvie este link para as candidatas. As primeiras {program.seats_left} que"
            f"\ncriarem loja por este link entram automaticamente no programa."
        ))
