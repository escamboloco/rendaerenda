"""
Digest periodico de novidades da plataforma (sem titulos de itens / sem nicho).
"""
from __future__ import annotations

import logging
from datetime import timedelta

from django.conf import settings
from django.core.mail import send_mail
from django.db.models import Count
from django.template.loader import render_to_string
from django.utils import timezone

from apps.catalog.models import Product
from apps.stores.models import Store

from .models import MarketingSubscriber

logger = logging.getLogger(__name__)


def _site_url(path: str = "") -> str:
    scheme = "http" if settings.DEBUG else "https"
    return f"{scheme}://{settings.SITE_DOMAIN}{path}"


def build_digest_context(days: int = 7) -> dict:
    since = timezone.now() - timedelta(days=days)
    new_products = Product.objects.filter(
        status=Product.Status.PUBLISHED,
        visibility=Product.Visibility.PUBLIC,
        created_at__gte=since,
        store__status=Store.Status.ACTIVE,
    ).count()
    active_stores = Store.objects.filter(status=Store.Status.ACTIVE).count()
    top_stores = list(
        Store.objects.filter(status=Store.Status.ACTIVE, sales_count__gt=0)
        .order_by("-bayesian_rating", "-sales_count")[:5]
        .values("display_name", "slug", "sales_count")
    )
    categories = list(
        Product.objects.filter(
            status=Product.Status.PUBLISHED,
            visibility=Product.Visibility.PUBLIC,
            store__status=Store.Status.ACTIVE,
        )
        .values("category__name")
        .annotate(total=Count("id"))
        .order_by("-total")[:5]
    )
    return {
        "site_name": settings.SITE_NAME,
        "home_url": _site_url("/"),
        "days": days,
        "new_products": new_products,
        "active_stores": active_stores,
        "top_stores": top_stores,
        "categories": categories,
    }


def send_marketing_digest(*, days: int = 7, dry_run: bool = False) -> int:
    """
    Envia digest para assinantes ativos. Retorna quantos e-mails foram
    disparados (ou seriam, em dry_run).
    """
    context_base = build_digest_context(days=days)
    if context_base["new_products"] == 0 and not dry_run:
        # Ainda envia se houver lojas ativas — oportunidades de compra.
        pass

    subscribers = MarketingSubscriber.objects.filter(is_active=True)
    sent = 0
    for sub in subscribers.iterator():
        ctx = {
            **context_base,
            "subscriber_name": sub.name or "olá",
            "unsubscribe_url": _site_url(f"/email/descadastrar/{sub.unsubscribe_token}/"),
        }
        body = render_to_string("emails/marketing_digest.txt", ctx)
        subject = f"Novidades em {settings.SITE_NAME} — esta semana"
        if dry_run:
            logger.info("DRY-RUN marketing → %s", sub.email)
            sent += 1
            continue
        try:
            send_mail(
                subject=subject,
                message=body,
                from_email=settings.DEFAULT_FROM_EMAIL,
                recipient_list=[sub.email],
                fail_silently=False,
            )
            sub.last_sent_at = timezone.now()
            sub.save(update_fields=["last_sent_at"])
            sent += 1
        except Exception:
            logger.exception("Falha no marketing para %s", sub.email)
    return sent
