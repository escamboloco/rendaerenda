from django.apps import AppConfig


class AccountsConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.accounts"
    verbose_name = "Contas e verificação de idade"

    def ready(self):
        # Registra e-mail de boas-vindas após cadastro via django-allauth.
        from . import signals  # noqa: F401
