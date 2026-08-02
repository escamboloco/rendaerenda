from functools import wraps

from django.conf import settings
from django.contrib.auth.views import redirect_to_login
from django.http import HttpResponseForbidden
from django.views.decorators.cache import never_cache


def staff_required(view):
    """Exige equipe ativa e impede cache de dados operacionais/LGPD."""

    @wraps(view)
    @never_cache
    def wrapped(request, *args, **kwargs):
        if not request.user.is_authenticated:
            return redirect_to_login(
                request.get_full_path(),
                login_url=settings.BACKOFFICE_LOGIN_URL,
            )
        if not request.user.is_active or not request.user.is_staff:
            return HttpResponseForbidden("Acesso restrito à equipe.")
        response = view(request, *args, **kwargs)
        response["Cache-Control"] = "no-store, private"
        response["Pragma"] = "no-cache"
        return response

    return wrapped


def superuser_required(view):
    """Ações financeiras irreversíveis exigem superusuário."""

    @wraps(view)
    @never_cache
    def wrapped(request, *args, **kwargs):
        if not request.user.is_authenticated:
            return redirect_to_login(
                request.get_full_path(),
                login_url=settings.BACKOFFICE_LOGIN_URL,
            )
        if (
            not request.user.is_active
            or not request.user.is_staff
            or not request.user.is_superuser
        ):
            return HttpResponseForbidden(
                "Ação financeira restrita à administração principal."
            )
        response = view(request, *args, **kwargs)
        response["Cache-Control"] = "no-store, private"
        return response

    return wrapped
