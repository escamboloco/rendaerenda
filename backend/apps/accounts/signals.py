"""E-mails de conta disparados pelos signals do django-allauth."""
import logging

from allauth.account.signals import user_signed_up
from django.conf import settings
from django.core.mail import send_mail
from django.dispatch import receiver
from django.template.loader import render_to_string

logger = logging.getLogger(__name__)


def _absolute(path: str) -> str:
    scheme = "http" if settings.DEBUG else "https"
    return f"{scheme}://{settings.SITE_DOMAIN}{path}"


@receiver(user_signed_up, dispatch_uid="accounts.send_safe_welcome_email")
def send_safe_welcome_email(request, user, **kwargs):
    """
    Envia os dados necessários para voltar à conta, nunca a senha.

    Senhas são armazenadas como hash e não são recuperáveis. Mandá-las por
    e-mail também criaria uma cópia permanente e insegura na caixa postal.
    """
    if not user.email:
        return
    context = {
        "user": user,
        "site_name": settings.SITE_NAME,
        "login_url": _absolute("/contas/login/"),
        "reset_url": _absolute("/contas/password/reset/"),
        "profile_url": _absolute("/minha-conta/"),
    }
    try:
        send_mail(
            subject="Sua conta foi criada",
            message=render_to_string("emails/welcome.txt", context),
            from_email=settings.DEFAULT_FROM_EMAIL,
            recipient_list=[user.email],
        )
    except Exception:
        # SMTP indisponível não deve desfazer uma conta já criada.
        logger.exception("Falha ao enviar boas-vindas para o usuário %s", user.pk)
