import io
import logging
import re

import markdown
import requests
from django.conf import settings
from django.core.cache import cache
from django.http import Http404, HttpResponse, JsonResponse
from django.shortcuts import redirect, render
from django.templatetags.static import static
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


# ---------------------------------------------------------------- og:image
#
# A midia dos anuncios fica em bucket privado e e servida por URL assinada
# de curta duracao (AWS_QUERYSTRING_EXPIRE, 5min). Crawler de card de link
# (X, WhatsApp, Telegram) e do Google buscam a imagem MUITO depois de ler o
# HTML - a URL assinada ja expirou e o card sai sem imagem. Por isso a
# prévia tem endereco proprio, estavel e cacheavel, que so expoe anuncio
# publicado e publico.
OG_WIDTH, OG_HEIGHT = 1200, 630
OG_BACKGROUND = (11, 7, 9)  # mesmo #0b0709 do tema
OG_CACHE_SECONDS = 60 * 60 * 24 * 7


def _render_og_card(image_field) -> bytes:
    """Encaixa a foto num quadro 1200x630 sobre o fundo da marca."""
    from PIL import Image, ImageOps

    with image_field.open("rb") as handle:
        source = Image.open(handle)
        source.load()

    # Foto de celular guarda a rotacao no EXIF em vez de girar os pixels -
    # sem isso o card sai deitado.
    source = ImageOps.exif_transpose(source)

    # "Contain" e nao "cover": foto de anuncio e vertical, e cortar para
    # preencher decepa justamente a peca anunciada.
    fitted = ImageOps.contain(source.convert("RGB"), (OG_WIDTH, OG_HEIGHT), Image.LANCZOS)
    canvas = Image.new("RGB", (OG_WIDTH, OG_HEIGHT), OG_BACKGROUND)
    canvas.paste(fitted, ((OG_WIDTH - fitted.width) // 2, (OG_HEIGHT - fitted.height) // 2))

    buffer = io.BytesIO()
    canvas.save(buffer, "JPEG", quality=82, optimize=True, progressive=True)
    return buffer.getvalue()


def _og_response(cache_key: str, image_field) -> HttpResponse:
    """Serve o card renderizado, com cache — nunca gera duas vezes a mesma foto."""
    payload = cache.get(cache_key)
    if payload is None:
        try:
            payload = _render_og_card(image_field)
        except Exception:
            # Arquivo corrompido ou storage fora do ar nao pode derrubar a
            # pagina que aponta para ca: cai na imagem de marca.
            logger.info("Falha ao gerar og:image para %s", cache_key)
            return redirect(static("img/og-brand.png"))
        cache.set(cache_key, payload, OG_CACHE_SECONDS)

    response = HttpResponse(payload, content_type="image/jpeg")
    response["Cache-Control"] = f"public, max-age={OG_CACHE_SECONDS}"
    return response


def _public_cover(product):
    return product.images.filter(is_cover=True).first() or product.images.first()


@require_GET
def og_product_image(request, store_slug: str, product_slug: str):
    """GET /og/anuncio/<loja>/<anuncio>.jpg — prévia de link do anúncio."""
    from apps.catalog.models import Product
    from apps.stores.views import public_store_filter

    product = (
        Product.objects.filter(
            public_store_filter("store__"),
            store__slug=store_slug,
            slug=product_slug,
            status=Product.Status.PUBLISHED,
            visibility=Product.Visibility.PUBLIC,
        )
        .prefetch_related("images")
        .first()
    )
    if product is None:
        raise Http404
    cover = _public_cover(product)
    if cover is None:
        return redirect(static("img/og-brand.png"))
    return _og_response(f"og:product:{product.pk}:{cover.pk}", cover.file)


@require_GET
def og_store_image(request, slug: str):
    """GET /og/loja/<loja>.jpg — prévia de link da loja (capa do item em destaque)."""
    from apps.catalog.models import Product
    from apps.stores.models import Store
    from apps.stores.views import public_store_filter

    store = Store.objects.filter(public_store_filter(), slug=slug).first()
    if store is None:
        raise Http404
    product = (
        Product.objects.filter(
            store=store,
            status=Product.Status.PUBLISHED,
            visibility=Product.Visibility.PUBLIC,
            stock__gt=0,
        )
        .prefetch_related("images")
        .order_by("-sold_count", "-created_at")
        .first()
    )
    cover = _public_cover(product) if product else None
    if cover is None:
        return redirect(static("img/og-brand.png"))
    return _og_response(f"og:store:{store.pk}:{cover.pk}", cover.file)


def robots_txt(request):
    lines = [
        "User-agent: *",
        "Disallow: /admin/",
        "Disallow: /gestao/",
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
