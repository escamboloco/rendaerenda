from django.contrib.auth import logout
from django.http import JsonResponse
from django.shortcuts import redirect
from django.urls import reverse

# Paths acessiveis sem age gate (ex.: a propria pagina de age gate,
# admin, estaticos, healthcheck). Tudo mais exige confirmacao.
AGE_GATE_EXEMPT_PREFIXES = (
    "/entrada/",
    "/admin/",
    "/gestao/",
    "/contas/",  # login, cadastro, reset de senha (link do e-mail)
    "/static/",
    "/media/protegido/",
    "/healthz",
    "/webhooks/",
    # robots.txt/sitemap.xml precisam ser legiveis por crawlers sem
    # sessao/cookie - nunca colocar HTML atras do gate aqui.
    "/robots.txt",
    "/sitemap.xml",
)

AGE_GATE_SESSION_KEY = "age_gate_confirmed"


class AgeGateMiddleware:
    """
    Bloqueia qualquer pagina publica ate o visitante confirmar +18 no
    age gate. Isso e apenas a barreira de entrada do site (visual) -
    NAO substitui a verificacao de idade real (CPF + biometria) exigida
    para cadastro/compra/venda, que fica em apps.accounts.
    """

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        user = getattr(request, "user", None)
        if (
            user
            and user.is_authenticated
            and (not user.is_active or getattr(user, "is_banned", False))
        ):
            logout(request)
            if request.path.startswith("/api/"):
                return JsonResponse({"detail": "Conta suspensa."}, status=403)

        if not request.path.startswith(AGE_GATE_EXEMPT_PREFIXES):
            # Conta autenticada já passou pela declaração de maioridade no
            # cadastro. O age gate visual vale para visitantes anônimos.
            authenticated_adult = bool(
                user and user.is_authenticated and user.is_active
            )
            if not authenticated_adult and not request.session.get(AGE_GATE_SESSION_KEY):
                if request.path.startswith("/api/"):
                    return JsonResponse(
                        {"detail": "Confirme que você é maior de 18 anos."},
                        status=403,
                    )
                gate_url = reverse("core:age_gate")
                if request.path != gate_url:
                    return redirect(f"{gate_url}?next={request.path}")

        response = self.get_response(request)

        if not request.path.startswith("/admin/"):
            response["X-Robots-Tag"] = response.get("X-Robots-Tag", "")
        response["Permissions-Policy"] = (
            "camera=(), microphone=(), geolocation=(), payment=(), usb=(), "
            "interest-cohort=()"
        )
        return response
