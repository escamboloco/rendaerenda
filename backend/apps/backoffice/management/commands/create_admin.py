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
        if user:
            user.is_staff = True
            user.is_superuser = True
            user.is_active = True
            if not user.username:
                user.username = email
            update_fields = ["is_staff", "is_superuser", "is_active", "username"]
            if options["reset_password"]:
                user.set_password(password)
                update_fields.append("password")
            user.save(update_fields=update_fields)
            message = "Administrador promovido/confirmado."
            if options["reset_password"]:
                message = "Administrador atualizado e senha redefinida."
            self.stdout.write(self.style.SUCCESS(message))
            return

        if User.objects.filter(cpf=cpf).exists():
            raise CommandError(
                "ADMIN_CPF já pertence a outra conta. Use o e-mail dessa conta "
                "em ADMIN_EMAIL para promovê-la."
            )
        User.objects.create_superuser(
            username=email,
            email=email,
            password=password,
            cpf=cpf,
            birth_date=birth_date,
            is_age_verified=True,
        )
        self.stdout.write(self.style.SUCCESS("Administrador criado."))
