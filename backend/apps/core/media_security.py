"""Validação e normalização de uploads sensíveis.

Nunca confia em extensão ou MIME enviados pelo navegador. Imagens são
decodificadas e regravadas sem EXIF/metadados, reduzindo risco de polyglot,
XSS e vazamento de localização/dispositivo.
"""
from __future__ import annotations

import io
import secrets
from pathlib import Path

from django.core.files.base import ContentFile
from PIL import Image, ImageDraw, UnidentifiedImageError
from rest_framework import serializers

MAX_KYC_IMAGE_BYTES = 10 * 1024 * 1024
MAX_IMAGE_PIXELS = 40_000_000


def validate_safe_image(upload, *, max_bytes: int = MAX_KYC_IMAGE_BYTES) -> None:
    if upload.size > max_bytes:
        raise serializers.ValidationError(
            f"Imagem muito grande (máximo {max_bytes // (1024 * 1024)}MB)."
        )
    try:
        upload.seek(0)
        with Image.open(upload) as image:
            if image.width * image.height > MAX_IMAGE_PIXELS:
                raise serializers.ValidationError("Imagem possui resolução excessiva.")
            if image.format not in {"JPEG", "PNG", "WEBP", "GIF"}:
                raise serializers.ValidationError(
                    "Formato inválido. Envie JPEG, PNG ou WebP."
                )
            image.verify()
    except (UnidentifiedImageError, OSError, ValueError) as exc:
        raise serializers.ValidationError("Arquivo não é uma imagem válida.") from exc
    finally:
        upload.seek(0)


def sanitize_image(
    upload,
    *,
    max_bytes: int = MAX_KYC_IMAGE_BYTES,
    watermark: str = "",
) -> ContentFile:
    """Decodifica e regrava em JPEG, removendo EXIF e payloads anexos."""
    validate_safe_image(upload, max_bytes=max_bytes)
    upload.seek(0)
    try:
        with Image.open(upload) as source:
            source.seek(0)
            image = source.convert("RGB")
            if watermark:
                overlay = Image.new("RGBA", image.size, (0, 0, 0, 0))
                draw = ImageDraw.Draw(overlay)
                label = watermark[:80]
                for y in range(30, image.height, 140):
                    for x in range(-40, image.width, 240):
                        draw.text((x, y), label, fill=(255, 255, 255, 72))
                image = Image.alpha_composite(image.convert("RGBA"), overlay).convert("RGB")
            output = io.BytesIO()
            image.save(
                output,
                format="JPEG",
                quality=90,
                optimize=True,
                progressive=True,
            )
    except (UnidentifiedImageError, OSError, ValueError) as exc:
        raise serializers.ValidationError("Não foi possível processar a imagem.") from exc
    finally:
        upload.seek(0)
    safe_name = f"{secrets.token_hex(16)}.jpg"
    return ContentFile(output.getvalue(), name=safe_name)


def validate_digital_asset(upload, *, max_bytes: int) -> None:
    """Whitelist de formatos entregáveis; bloqueia executáveis e HTML/SVG."""
    if upload.size > max_bytes:
        raise serializers.ValidationError(
            f"Arquivo muito grande (máximo {max_bytes // (1024 * 1024)}MB)."
        )
    suffix = Path(upload.name or "").suffix.lower()
    allowed = {
        ".zip",
        ".pdf",
        ".mp4",
        ".mov",
        ".webm",
        ".jpg",
        ".jpeg",
        ".png",
        ".webp",
        ".gif",
        ".txt",
    }
    if suffix not in allowed:
        raise serializers.ValidationError(
            "Formato não permitido. Use ZIP, PDF, vídeo, imagem ou TXT."
        )

    head = upload.read(512)
    upload.seek(0)
    lower = head.lstrip().lower()
    dangerous_text = (
        lower.startswith(b"<html")
        or lower.startswith(b"<!doctype html")
        or lower.startswith(b"<svg")
        or b"<script" in lower
    )
    if dangerous_text or head[:2] == b"MZ" or head[:4] == b"\x7fELF":
        raise serializers.ValidationError("Arquivo potencialmente executável foi bloqueado.")

    signatures = {
        ".zip": head[:4] in {b"PK\x03\x04", b"PK\x05\x06", b"PK\x07\x08"},
        ".pdf": head.startswith(b"%PDF-"),
        ".jpg": head.startswith(b"\xff\xd8\xff"),
        ".jpeg": head.startswith(b"\xff\xd8\xff"),
        ".png": head.startswith(b"\x89PNG\r\n\x1a\n"),
        ".webp": head[:4] == b"RIFF" and head[8:12] == b"WEBP",
        ".gif": head[:6] in {b"GIF87a", b"GIF89a"},
        ".mp4": head[4:8] == b"ftyp",
        ".mov": head[4:8] == b"ftyp",
        ".webm": head[:4] == b"\x1a\x45\xdf\xa3",
    }
    if suffix in signatures and not signatures[suffix]:
        raise serializers.ValidationError("Conteúdo do arquivo não corresponde à extensão.")
    if suffix == ".txt":
        try:
            head.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise serializers.ValidationError("TXT precisa estar em UTF-8.") from exc
