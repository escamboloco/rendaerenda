import markdown
from django.conf import settings
from django.http import Http404, HttpResponse
from django.shortcuts import redirect, render
from django.utils.http import url_has_allowed_host_and_scheme
from django.views.decorators.http import require_http_methods

from .middleware import AGE_GATE_SESSION_KEY

LEGAL_DOCS = {
    "termos-de-uso": ("TERMOS_DE_USO.md", "Termos de Uso"),
    "privacidade": ("POLITICA_DE_PRIVACIDADE.md", "Política de Privacidade"),
}


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
