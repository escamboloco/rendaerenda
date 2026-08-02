import logging
import re

import markdown
import requests
from django.conf import settings
from django.core.cache import cache
from django.http import Http404, HttpResponse, JsonResponse
from django.shortcuts import redirect, render
from django.utils.http import url_has_allowed_host_and_scheme
from django.views.decorators.http import require_GET, require_http_methods
from django_ratelimit.decorators import ratelimit

from .middleware import AGE_GATE_SESSION_KEY

logger = logging.getLogger(__name__)

LEGAL_DOCS = {
    "termos-de-uso": ("TERMOS_DE_USO.md", "Termos de Uso"),
    "privacidade": ("POLITICA_DE_PRIVACIDADE.md", "Política de Privacidade"),
}


@ratelimit(key="ip", rate="30/m", method="POST", block=True)
@require_http_methods(["GET", "POST"])
def age_gate(request):
    next_url = request.GET.get("next") or request.POST.get("next") or "/"
    if not url_has_allowed_host_and_scheme(next_url, allowed_hosts={request.get_host()}):
        next_url = "/"

    if request.method == "POST":
        if request.POST.get("confirm_adult") == "yes":
            request.session[AGE_GATE_SESSION_KEY] = True
            return redirect(next_url)
        return redirect("https://www.google.com")

    return render(request, "core/age_gate.html", {"next": next_url})


def legal_page(request, doc):
    if doc not in LEGAL_DOCS:
        raise Http404
    filename, title = LEGAL_DOCS[doc]
    raw = (settings.BASE_DIR.parent / "docs" / filename).read_text(encoding="utf-8")
    content = markdown.markdown(raw, extensions=["tables"])
    return render(request, "core/legal.html", {"content": content, "title": title})


def healthz(request):
    return HttpResponse("ok", content_type="text/plain")


@require_GET
def cep_lookup(request, cep: str):
    """
    GET /api/cep/<cep>/ — preenche o endereço no checkout a partir do CEP.

    O navegador nunca fala com o ViaCEP direto: a consulta sai do servidor.
    Isso mantém a CSP fechada (connect-src 'self'), evita expor o IP da
    compradora a terceiro e ainda deixa o resultado em cache.
    """
    cep = re.sub(r"\D", "", cep or "")
    if len(cep) != 8:
        return JsonResponse({"detail": "CEP inválido."}, status=400)

    cache_key = f"cep:{cep}"
    cached = cache.get(cache_key)
    if cached is not None:
        return JsonResponse(cached)

    try:
        response = requests.get(f"https://viacep.com.br/ws/{cep}/json/", timeout=(3, 6))
        response.raise_for_status()
        data = response.json()
    except Exception:
        # Autocomplete e conveniencia: se o ViaCEP cair, o checkout continua
        # funcionando com o endereco digitado a mao. Nunca propagar 500 aqui.
        logger.info("Consulta de CEP indisponivel para %s***", cep[:5])
        return JsonResponse({"detail": "Não foi possível consultar o CEP agora."}, status=503)

    if data.get("erro"):
        return JsonResponse({"detail": "CEP não encontrado."}, status=404)

    result = {
        "cep": cep,
        "street": data.get("logradouro", ""),
        "neighborhood": data.get("bairro", ""),
        "city": data.get("localidade", ""),
        "state": (data.get("uf") or "").upper(),
    }
    cache.set(cache_key, result, 60 * 60 * 24 * 30)
    return JsonResponse(result)


def robots_txt(request):
    lines = [
        "User-agent: *",
        "Disallow: /admin/",
        "Disallow: /api/",
        "Disallow: /webhooks/",
        "Disallow: /entrada/",
        "Disallow: /contas/",
        "Disallow: /vendedora/",
        "Disallow: /carteira/",
        "Disallow: /verificacao-idade/",
        "Disallow: /email/",
        "",
        f"Sitemap: {request.scheme}://{request.get_host()}/sitemap.xml",
    ]
    return HttpResponse("\n".join(lines), content_type="text/plain")


@require_http_methods(["GET", "POST"])
def marketing_unsubscribe(request, token: str):
    from django.shortcuts import get_object_or_404

    from .models import MarketingSubscriber

    subscriber = get_object_or_404(MarketingSubscriber, unsubscribe_token=token)
    if request.method == "POST" or request.GET.get("confirm") == "1":
        subscriber.unsubscribe()
        return render(request, "core/marketing_unsubscribed.html", {"done": True})
    return render(request, "core/marketing_unsubscribed.html", {"done": False, "token": token})
