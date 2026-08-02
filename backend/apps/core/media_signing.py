"""URLs assinadas de curta duração para mídia de produto.

Impede hotlink estável e scraping em massa: cada URL expira e exige
assinatura HMAC com o SECRET_KEY. A view ainda exige age gate/sessão.
"""
from __future__ import annotations

import hashlib
import hmac
import time
from urllib.parse import urlencode

from django.conf import settings
from django.core.files.storage import FileSystemStorage
from django.urls import reverse


MEDIA_URL_TTL_SECONDS = 300


def _signing_key() -> bytes:
    return settings.SECRET_KEY.encode("utf-8")


def sign_media_path(path: str, *, ttl: int = MEDIA_URL_TTL_SECONDS) -> str:
    clean = path.lstrip("/")
    expires = int(time.time()) + max(int(ttl), 30)
    payload = f"{clean}:{expires}".encode("utf-8")
    signature = hmac.new(_signing_key(), payload, hashlib.sha256).hexdigest()[:40]
    query = urlencode({"e": expires, "s": signature})
    return f"{reverse('core_pages:protected_media', kwargs={'path': clean})}?{query}"


def verify_media_signature(path: str, expires: str | int | None, signature: str | None) -> bool:
    if not expires or not signature:
        return False
    try:
        expires_int = int(expires)
    except (TypeError, ValueError):
        return False
    if expires_int < int(time.time()):
        return False
    clean = path.lstrip("/")
    payload = f"{clean}:{expires_int}".encode("utf-8")
    expected = hmac.new(_signing_key(), payload, hashlib.sha256).hexdigest()[:40]
    return hmac.compare_digest(expected, signature)


class SignedProductStorage(FileSystemStorage):
    """Storage local que devolve URL assinada em vez de /media/ direto."""

    def url(self, name: str) -> str:
        return sign_media_path(name)
