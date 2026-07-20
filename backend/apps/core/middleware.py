from django.shortcuts import redirect
from django.urls import reverse

# Paths acessiveis sem age gate (ex.: a propria pagina de age gate,
# admin, estaticos, healthcheck). Tudo mais exige confirmacao.
AGE_GATE_EXEMPT_PREFIXES = (
    "/entrada/",
    "/admin/",
    "/static/",
    "/healthz",
    "/webhooks/",
    # Chamadas de API sao feitas via fetch/XHR por paginas que ja
    # passaram pelo age gate (renderizadas server-side) - um redirect
    # HTML aqui quebraria o cliente JSON. Autenticacao/permissao de
    # cada view (IsAuthenticated, is_age_verified) continua valendo.
    "/api/",
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
        if not request.path.startswith(AGE_GATE_EXEMPT_PREFIXES):
            if not request.session.get(AGE_GATE_SESSION_KEY):
                gate_url = reverse("core:age_gate")
                if request.path != gate_url:
                    return redirect(f"{gate_url}?next={request.path}")

        response = self.get_response(request)

        if not request.path.startswith("/admin/"):
            response["X-Robots-Tag"] = response.get("X-Robots-Tag", "")
        return response
