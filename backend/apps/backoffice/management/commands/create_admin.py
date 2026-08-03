"""
Cria (ou promove) a conta de administração a partir das variáveis de
ambiente. Roda no deploy, é idempotente e nunca imprime a senha.

Existe porque `createsuperuser` é interativo — não serve para o build do
Render, onde não há terminal. Sem isso, o primeiro acesso ao painel
dependeria de abrir um shell no servidor.

Uso:  python manage.py create_admin
Envs: ADMIN_EMAIL, ADMIN_PASSWORD, ADMIN_CPF, ADMIN_BIRTH_DATE
"""
import re
from datetime import date

from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand
from django.db import transaction

from decouple import config

User = get_user_model()


class Command(BaseCommand):
    help = "Cria ou promove o administrador a partir de ADMIN_EMAIL/ADMIN_PASSWORD."

    def handle(self, *args, **options):
        email = (config("ADMIN_EMAIL", default="") or "").strip().lower()
        senha = config("ADMIN_PASSWORD", default="") or ""

        if not email or not senha:
            self.stdout.write("ADMIN_EMAIL/ADMIN_PASSWORD não definidos — nada a fazer.")
            return

        if len(senha) < 12:
            # O painel dá acesso a documento de terceiro e ao dinheiro em
            # custódia. Senha curta aqui é a porta mais barata de invadir.
            self.stderr.write(self.style.ERROR("ADMIN_PASSWORD precisa de pelo menos 12 caracteres."))
            return

        cpf = re.sub(r"\D", "", config("ADMIN_CPF", default="") or "")
        nascimento = (config("ADMIN_BIRTH_DATE", default="1990-01-01") or "1990-01-01").strip()

        with transaction.atomic():
            usuario = User.objects.filter(email__iexact=email).first()
            criado = usuario is None

            if criado:
                if not cpf or len(cpf) != 11:
                    self.stderr.write(
                        self.style.ERROR("Conta nova exige ADMIN_CPF com 11 dígitos.")
                    )
                    return
                if User.objects.filter(cpf=cpf).exists():
                    self.stderr.write(self.style.ERROR("Já existe conta com esse CPF."))
                    return
                usuario = User(
                    username=email,
                    email=email,
                    cpf=cpf,
                    birth_date=date.fromisoformat(nascimento),
                )

            usuario.set_password(senha)
            usuario.is_staff = True
            usuario.is_superuser = True
            usuario.is_active = True
            usuario.is_banned = False
            usuario.save()

        acao = "criado" if criado else "atualizado"
        self.stdout.write(self.style.SUCCESS(f"Administrador {acao}: {email}"))
        self.stdout.write("Acesse em /gestao/entrar/")
