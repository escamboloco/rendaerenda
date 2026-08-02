"""Filtros dos metadados que aparecem fora do site (busca e card de link)."""
import re

from django import template
from django.template.defaultfilters import stringfilter

register = template.Library()

_WHITESPACE = re.compile(r"\s+")
# Pontuação que não deve ficar pendurada antes das reticências.
_DANGLING = " ,.;:–-—"


@register.filter(is_safe=True)
@stringfilter
def meta_text(value, length=160):
    """
    Resumo de uma linha para `<meta name="description">` e Open Graph.

    Não usar `truncatechars` aqui. Em pt-BR a string de truncamento do
    Django é `" %(truncated_text)s…"` — com espaço NA FRENTE —, então toda
    descrição truncada do site saía começando com um espaço no resultado
    de busca e no card compartilhado.

    Também colapsa quebra de linha (descrição de anúncio vem de textarea)
    e corta na última palavra inteira, em vez de partir palavra ao meio.
    """
    text = _WHITESPACE.sub(" ", value).strip()
    try:
        length = int(length)
    except (TypeError, ValueError):
        return text
    if len(text) <= length:
        return text
    head = text[:length]
    if " " in head:
        head = head.rsplit(" ", 1)[0]
    return head.rstrip(_DANGLING) + "…"
