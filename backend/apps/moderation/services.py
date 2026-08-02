"""
Filtros automaticos (regex + OCR) que rodam ANTES da revisao humana.
Qualquer indicio de servico sexual (encontro, programa, acompanhante,
webcam) ou contato direto (telefone, whatsapp, @instagram) embutido em
titulo/descricao/imagem derruba o item para AUTO_FLAGGED, nunca publica
direto. Ver docs/BASE_JURIDICA.md secao 3.
"""
import re

SEXUAL_SERVICE_PATTERNS = [
    re.compile(r"\bprograma\b", re.IGNORECASE),
    re.compile(r"\bacompanhante\b", re.IGNORECASE),
    re.compile(r"\bencontro(s)?\b", re.IGNORECASE),
    re.compile(r"\bwebcam\b", re.IGNORECASE),
    re.compile(r"\bvideo\s*chamada\b", re.IGNORECASE),
    re.compile(r"\bsexting\b", re.IGNORECASE),
]

CONTACT_LEAK_PATTERNS = [
    re.compile(r"\b\d{2}\s?9?\d{4}[-\s]?\d{4}\b"),  # telefone BR
    re.compile(r"\b(?:\+?55\s?)?\(?\d{2}\)?\s?9?\d{4}[-\s]?\d{4}\b"),
    re.compile(r"\bwhats\s?app\b", re.IGNORECASE),
    re.compile(r"\b(?:zap|zapp|wpp|whts|whasapp)\b", re.IGNORECASE),
    re.compile(r"@[a-zA-Z0-9_.]{3,}"),  # @handle de rede social
    re.compile(r"\btelegram\b", re.IGNORECASE),
    re.compile(r"\bt\.me/\S+", re.IGNORECASE),
    re.compile(r"\b(?:discord|signal|onlyfans|privacy\.com\.br)\b", re.IGNORECASE),
    re.compile(r"\b(?:instagram|insta|ig|tiktok|kwai)\b", re.IGNORECASE),
    re.compile(r"(?:instagram|tiktok|facebook|t\.me|wa\.me|api\.whatsapp)\.com/\S+", re.IGNORECASE),
    re.compile(r"\b[\w.+-]+@[\w.-]+\.[a-z]{2,}\b", re.IGNORECASE),  # e-mail
    re.compile(r"\b(?:pix|chave\s*pix)\b.{0,40}\b\d{11,14}\b", re.IGNORECASE),
]


def scan_text(text: str) -> list[str]:
    flags = []
    for pattern in SEXUAL_SERVICE_PATTERNS:
        if pattern.search(text):
            flags.append(f"sexual_service:{pattern.pattern}")
    for pattern in CONTACT_LEAK_PATTERNS:
        if pattern.search(text):
            flags.append(f"contact_leak:{pattern.pattern}")
    return flags


def run_automated_filters(*, title: str, description: str) -> list[str]:
    return scan_text(f"{title}\n{description}")
