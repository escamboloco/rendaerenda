"""Entrega protegida de fotos/vídeos de produto.

Nunca usa URL pública estável. Exige assinatura HMAC válida, age gate e
mesma origem quando houver Referer. Respostas bloqueiam cache e
download amigável.
"""
from __future__ import annotations

import mimetypes
from pathlib import Path

from django.conf import settings
from django.http import FileResponse, Http404, HttpResponseForbidden
from django.views.decorators.http import require_GET

from apps.core.media_signing import verify_media_signature
from apps.core.middleware import AGE_GATE_SESSION_KEY


def _same_origin(request) -> bool:
    referer = request.META.get("HTTP_REFERER") or ""
    if not referer:
        # Navegação direta/imagem em cache sem Referer: só com cookie de sessão.
        return bool(request.session.get(AGE_GATE_SESSION_KEY) or request.user.is_authenticated)
    host = request.get_host()
    return referer.startswith(f"https://{host}/") or referer.startswith(f"http://{host}/")


@require_GET
def protected_product_media(request, path: str):
    clean = path.lstrip("/")
    if ".." in clean.split("/") or clean.startswith("/") or not clean.startswith("products/"):
        raise Http404

    if not verify_media_signature(
        clean,
        request.GET.get("e"),
        request.GET.get("s"),
    ):
        return HttpResponseForbidden("Link de mídia expirado ou inválido.")

    if not (
        request.session.get(AGE_GATE_SESSION_KEY)
        or (request.user.is_authenticated and request.user.is_staff)
    ):
        return HttpResponseForbidden("Confirme que você é maior de 18 anos.")

    if not _same_origin(request):
        return HttpResponseForbidden("Hotlink bloqueado.")

    root = Path(settings.MEDIA_ROOT).resolve()
    full = (root / clean).resolve()
    if not str(full).startswith(str(root)) or not full.is_file():
        raise Http404

    content_type, _ = mimetypes.guess_type(str(full))
    response = FileResponse(full.open("rb"), content_type=content_type or "application/octet-stream")
    response["Content-Disposition"] = "inline"
    response["Cache-Control"] = "private, no-store, max-age=0, must-revalidate"
    response["Pragma"] = "no-cache"
    response["X-Content-Type-Options"] = "nosniff"
    response["X-Robots-Tag"] = "noindex, nofollow, noimageindex"
    # Dificulta salvar via "Salvar como" em alguns clientes; não é à prova
    # de screenshot, mas remove o caminho fácil de download em massa.
    response["Content-Security-Policy"] = "default-src 'none'; sandbox"
    return response
