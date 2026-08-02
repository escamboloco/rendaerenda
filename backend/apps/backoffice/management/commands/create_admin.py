import os
from datetime import date

from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError
from django.core.management.base import BaseCommand, CommandError

from apps.accounts.models import User, validate_adult_birth_date


class Command(BaseCommand):
    help = "Cria/promove o administrador definido por ADMIN_* (idempotente)."

    def add_arguments(self, parser):
        parser.add_argument(
            "--reset-password",
            action="store_true",
            help=(
                "Redefine a senha de uma conta já existente. Não é usado no "
                "build para evitar trocar a senha em todo deploy."
            ),
        )

    def handle(self, *args, **options):
        email = os.getenv("ADMIN_EMAIL", "").strip().lower()
        password = os.getenv("ADMIN_PASSWORD", "")
        cpf = "".join(c for c in os.getenv("ADMIN_CPF", "") if c.isdigit())
        raw_birth_date = os.getenv("ADMIN_BIRTH_DATE", "").strip()

        if not any((email, password, cpf, raw_birth_date)):
            self.stdout.write("ADMIN_* ausentes — criação do administrador ignorada.")
            return
        if email and not any((password, cpf, raw_birth_date)):
            user = User.objects.filter(email__iexact=email).first()
            if not user:
                raise CommandError(
                    "ADMIN_EMAIL não corresponde a uma conta existente. "
                    "No primeiro deploy, preencha as quatro variáveis ADMIN_*."
                )
            if not user.is_staff:
                raise CommandError(
                    "A conta de ADMIN_EMAIL existe, mas não é da equipe. "
                    "Promoção automática bloqueada por segurança."
                )
            user.is_staff = True
            user.is_superuser = True
            user.is_active = True
            user.save(update_fields=["is_staff", "is_superuser", "is_active"])
            self.stdout.write(
                self.style.SUCCESS("Administrador existente confirmado.")
            )
            return
        if not all((email, password, cpf, raw_birth_date)):
            raise CommandError(
                "Preencha ADMIN_EMAIL, ADMIN_PASSWORD, ADMIN_CPF e "
                "ADMIN_BIRTH_DATE juntos."
            )
        if len(password) < 12:
            raise CommandError("ADMIN_PASSWORD precisa ter ao menos 12 caracteres.")
        if len(cpf) != 11:
            raise CommandError("ADMIN_CPF precisa ter 11 dígitos.")
        try:
            birth_date = date.fromisoformat(raw_birth_date)
            validate_adult_birth_date(birth_date)
            validate_password(password)
        except (ValueError, ValidationError) as exc:
            raise CommandError(f"Dados do administrador inválidos: {exc}") from exc

        user = User.objects.filter(email__iexact=email).first()
        by_cpf = User.objects.filter(cpf=cpf).first()

        # E-mail e CPF apontam para contas diferentes: promove a do CPF
        # (identidade civil) e não derruba o deploy.
        if user and by_cpf and user.pk != by_cpf.pk:
            self.stdout.write(
                self.style.WARNING(
                    f"ADMIN_EMAIL ({email}) e ADMIN_CPF pertencem a contas "
                    f"diferentes. Promovendo a conta do CPF ({by_cpf.email})."
                )
            )
            user = by_cpf
        elif not user and by_cpf:
            self.stdout.write(
                self.style.WARNING(
                    f"ADMIN_CPF já está na conta {by_cpf.email}. "
                    "Promovendo essa conta em vez de criar outra."
                )
            )
            user = by_cpf

        if user:
            user.is_staff = True
            user.is_superuser = True
            user.is_active = True
            update_fields = ["is_staff", "is_superuser", "is_active"]
            if not user.username:
                user.username = email
                update_fields.append("username")
            # Alinha o e-mail ao ADMIN_EMAIL quando estiver livre (evita
            # criar segunda conta no próximo deploy).
            if user.email.lower() != email and not User.objects.filter(
                email__iexact=email
            ).exclude(pk=user.pk).exists():
                user.email = email
                update_fields.append("email")
            if options["reset_password"]:
                user.set_password(password)
                update_fields.append("password")
            user.save(update_fields=update_fields)
            message = "Administrador promovido/confirmado."
            if options["reset_password"]:
                message = "Administrador atualizado e senha redefinida."
            self.stdout.write(self.style.SUCCESS(message))
            return

        User.objects.create_superuser(
            username=email,
            email=email,
            password=password,
            cpf=cpf,
            birth_date=birth_date,
            is_age_verified=True,
        )
        self.stdout.write(self.style.SUCCESS("Administrador criado."))
