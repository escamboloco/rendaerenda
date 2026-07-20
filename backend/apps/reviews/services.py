from django.core.exceptions import ValidationError

from apps.moderation.services import run_automated_filters
from apps.payments.models import Order

from .models import Review


def create_review(*, buyer, order: Order, rating: int, comment: str) -> Review:
    if order.buyer_id != buyer.id:
        raise ValidationError("Este pedido não é seu.")
    if order.status != Order.Status.DELIVERED:
        raise ValidationError("Só é possível avaliar pedidos entregues.")
    if hasattr(order, "review"):
        raise ValidationError("Você já avaliou este pedido.")

    if comment:
        # Mesma trava anti-vazamento-de-contato/servico usada em pedidos
        # personalizados - review publica nao pode virar canal de contato.
        flags = run_automated_filters(title="", description=comment)
        if flags:
            raise ValidationError(
                "O comentário não pode conter contatos externos ou menções a serviços."
            )

    review = Review.objects.create(order=order, store=order.store, buyer=buyer, rating=rating, comment=comment)

    from apps.stores.services import recompute_store_rating

    recompute_store_rating(order.store)
    return review
