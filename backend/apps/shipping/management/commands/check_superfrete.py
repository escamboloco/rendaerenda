"""
Smoke test da integração SuperFrete em produção (ou sandbox).

Uso no Render Shell / local:
  python manage.py check_superfrete
  python manage.py check_superfrete --origin-cep 01310100 --dest-cep 30130010
  python manage.py check_superfrete --allow-sandbox   # só em dev
"""
from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from apps.shipping import superfrete
from apps.stores.models import Store


class Command(BaseCommand):
    help = (
        "Confere token, ambiente e cotação SuperFrete. "
        "Use no Shell do Render depois de preencher SUPERFRETE_TOKEN."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--origin-cep",
            default="01310100",
            help="CEP de origem da cotação de teste (padrão: Av. Paulista).",
        )
        parser.add_argument(
            "--dest-cep",
            default="30130010",
            help="CEP de destino da cotação de teste (padrão: BH centro).",
        )
        parser.add_argument(
            "--allow-sandbox",
            action="store_true",
            help="Aceita SUPERFRETE_SANDBOX=True (apenas desenvolvimento).",
        )

    def handle(self, *args, **options):
        errors: list[str] = []

        provider = getattr(settings, "SHIPPING_PROVIDER", "")
        if provider != "superfrete":
            errors.append(f"SHIPPING_PROVIDER={provider!r} (esperado 'superfrete').")

        token = (getattr(settings, "SUPERFRETE_TOKEN", "") or "").strip()
        if not token:
            errors.append("SUPERFRETE_TOKEN vazio — cole o token de PRODUÇÃO do painel.")

        sandbox = bool(getattr(settings, "SUPERFRETE_SANDBOX", True))
        if sandbox and not options["allow_sandbox"]:
            errors.append(
                "SUPERFRETE_SANDBOX=True — em produção deve ser False "
                "(API https://api.superfrete.com)."
            )

        if not getattr(settings, "PLATFORM_BUYS_SHIPPING_LABEL", True):
            self.stdout.write(
                self.style.WARNING(
                    "PLATFORM_BUYS_SHIPPING_LABEL=False — a plataforma não compra etiqueta."
                )
            )

        sender_name = (
            (getattr(settings, "SHIPPING_SENDER_NAME", "") or "").strip()
            or (getattr(settings, "PLATFORM_LEGAL_NAME", "") or "").strip()
            or getattr(settings, "SITE_NAME", "")
        )
        sender_doc = (
            (getattr(settings, "SHIPPING_SENDER_DOCUMENT", "") or "").strip()
            or (getattr(settings, "PLATFORM_CNPJ", "") or "").strip()
        )
        if not sender_doc:
            self.stdout.write(
                self.style.WARNING(
                    "SHIPPING_SENDER_DOCUMENT / PLATFORM_CNPJ vazio — "
                    "a etiqueta pode sair sem documento do remetente."
                )
            )

        if errors:
            for item in errors:
                self.stderr.write(self.style.ERROR(f"• {item}"))
            raise CommandError(
                "SuperFrete NÃO está pronto para produção. Corrija os itens acima."
            )

        try:
            incomplete = (
                Store.objects.filter(status=Store.Status.ACTIVE)
                .exclude(origin_cep="")
                .filter(origin_street="")
                .count()
            )
        except Exception:  # noqa: BLE001 — DB pode não existir no shell local
            incomplete = 0
        if incomplete:
            self.stdout.write(
                self.style.WARNING(
                    f"{incomplete} loja(s) ativa(s) com CEP mas sem rua/número — "
                    "complete o endereço de postagem no admin antes da 1ª etiqueta."
                )
            )

        base = (
            "https://sandbox.superfrete.com"
            if sandbox
            else "https://api.superfrete.com"
        )
        self.stdout.write(f"Ambiente: {'sandbox' if sandbox else 'produção'} ({base})")
        self.stdout.write(f"Remetente neutro: {sender_name}")
        self.stdout.write(
            f"Cotando {options['origin_cep']} → {options['dest_cep']}…"
        )

        try:
            options_list = superfrete.calculate(
                origin_cep=options["origin_cep"],
                destination_cep=options["dest_cep"],
                weight_grams=300,
                length_cm=20,
                width_cm=15,
                height_cm=5,
                declared_value=50,
            )
        except superfrete.SuperFreteError as exc:
            raise CommandError(f"Falha na cotação SuperFrete: {exc}") from exc

        if not options_list:
            raise CommandError(
                "Cotação OK na API, mas nenhum serviço retornou. "
                "Confira SUPERFRETE_SERVICES e o saldo/contratos no painel."
            )

        for option in options_list:
            company = (option.get("company") or {}).get("name") or "?"
            service_name = option.get("name") or option.get("id")
            price = option.get("price")
            days = option.get("delivery_time") or option.get("delivery_range")
            self.stdout.write(f"  • {company} / {service_name}: R$ {price} ({days})")

        self.stdout.write(
            self.style.SUCCESS(
                f"SuperFrete OK — {len(options_list)} opção(ões). "
                "Próximo: pagar um pedido real e conferir o PDF da etiqueta."
            )
        )
