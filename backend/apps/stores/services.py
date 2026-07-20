"""
Metricas agregadas da loja (nota media, nota bayesiana, contagem de
vendas) - cacheadas em Store para o ranking (apps.stores.views.ranking_page)
nao precisar agregar todas as lojas a cada request.
"""
from decimal import ROUND_HALF_UP, Decimal

from django.db.models import Avg, Count, F

from .models import RATING_BAYESIAN_MIN_VOTES, Store


def increment_sales_count(store: Store):
    """Chamado quando o pagamento de um pedido confirma (webhook do PSP)."""
    Store.objects.filter(id=store.id).update(sales_count=F("sales_count") + 1)


def global_average_rating() -> Decimal:
    result = Store.objects.filter(review_count__gt=0).aggregate(avg=Avg("avg_rating"))["avg"]
    return Decimal(str(result)) if result is not None else Decimal("3.00")


def recompute_store_rating(store: Store):
    """
    Recalcula avg_rating/review_count/bayesian_rating a partir das
    Review reais da loja - chamado sempre que uma avaliacao e criada
    (apps.reviews.services.create_review).
    """
    from apps.reviews.models import Review

    agg = Review.objects.filter(store=store).aggregate(avg=Avg("rating"), count=Count("id"))
    avg_rating = Decimal(str(agg["avg"])).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP) if agg["avg"] else Decimal("0.00")
    review_count = agg["count"] or 0

    global_avg = global_average_rating()
    m = Decimal(RATING_BAYESIAN_MIN_VOTES)
    v = Decimal(review_count)
    if v > 0:
        bayesian = ((v / (v + m)) * avg_rating + (m / (v + m)) * global_avg).quantize(
            Decimal("0.01"), rounding=ROUND_HALF_UP
        )
    else:
        bayesian = Decimal("0.00")

    Store.objects.filter(id=store.id).update(
        avg_rating=avg_rating, review_count=review_count, bayesian_rating=bayesian
    )
