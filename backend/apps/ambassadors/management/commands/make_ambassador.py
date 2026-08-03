"""
Promove uma loja existente a embaixadora.

Uso (Render Shell ou local):
    python manage.py make_ambassador <slug-da-loja>
    python manage.py make_ambassador <slug-da-loja> --code MEUCOD8

Útil para as primeiras embaixadoras que forem recrutadas fora da UI
(WhatsApp, DM, indicação pessoal) antes do programa estar em pleno ar.
"""
from django.core.exceptions import ValidationError
from django.core.management.base import BaseCommand, CommandError

from apps.ambassadors.models import Ambassador, AmbassadorProgram
from apps.ambassadors.services import join_ambassador_program
from apps.stores.models import Store


class Command(BaseCommand):
    help = "Promove uma loja existente a embaixadora do programa fundador."

    def add_arguments(self, parser):
        parser.add_argument("slug", help="Slug da loja (ex.: minha-loja)")
        parser.add_argument(
            "--code",
            dest="code",
            default=None,
            help="Código de indicação personalizado (máx. 12 chars). Se omitido, gera automaticamente.",
        )
        parser.add_argument(
            "--list",
            action="store_true",
            dest="list_all",
            help="Lista todas as embaixadoras e sai.",
        )

    def handle(self, *args, **options):
        if options["list_all"]:
            self._list()
            return

        slug = options["slug"]
        try:
            store = Store.objects.get(slug=slug)
        except Store.DoesNotExist:
            raise CommandError(f"Loja '{slug}' não encontrada.")

        if hasattr(store, "ambassador"):
            a = store.ambassador
            self.stdout.write(self.style.WARNING(
                f"'{store.display_name}' já é embaixadora #{a.seat_number}.\n"
                f"Código: {a.referral_code}\n"
                f"Link: /vender/?ref={a.referral_code}"
            ))
            return

        try:
            ambassador = join_ambassador_program(store)
        except ValidationError as exc:
            raise CommandError(str(exc))

        if options["code"]:
            code = options["code"].upper().strip()
            if len(code) > 12:
                raise CommandError("Código não pode ter mais de 12 caracteres.")
            if Ambassador.objects.filter(referral_code=code).exists():
                raise CommandError(f"Código '{code}' já está em uso por outra embaixadora.")
            ambassador.referral_code = code
            ambassador.save(update_fields=["referral_code"])

        program = AmbassadorProgram.singleton()
        self.stdout.write(self.style.SUCCESS(
            f"\n✓ {store.display_name} é agora embaixadora #{ambassador.seat_number}!\n"
            f"\n  Código de indicação : {ambassador.referral_code}"
            f"\n  Link (relativo)     : /vender/?ref={ambassador.referral_code}"
            f"\n  Vagas restantes     : {program.seats_left}/{program.max_seats}"
        ))

    def _list(self):
        ambassadors = Ambassador.objects.select_related("store").order_by("seat_number")
        if not ambassadors.exists():
            self.stdout.write("Nenhuma embaixadora cadastrada ainda.")
            return

        program = AmbassadorProgram.singleton()
        self.stdout.write(f"\nEmbaixadoras ({program.slots_taken}/{program.max_seats} vagas):\n")
        for a in ambassadors:
            status = "" if a.is_active else "  [INATIVA]"
            ref_count = a.referrals.count()
            self.stdout.write(
                f"  #{a.seat_number:02d}  {a.store.display_name:<30} "
                f"código={a.referral_code}  indicações={ref_count}{status}"
            )
        self.stdout.write("")
