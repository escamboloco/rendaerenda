import uuid

from django.conf import settings
from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models


class Review(models.Model):
    """
    Avaliação de 1 a 5 estrelas + comentário, sempre atrelada a um
    PEDIDO ENTREGUE (comprador comprovadamente comprou da loja - nunca
    aceitar avaliação sem compra, evita review falso/manipulação).
    Uma avaliação por pedido. store é denormalizado para agregar rápido
    (apps.stores.services.recompute_store_rating).
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    order = models.OneToOneField("payments.Order", on_delete=models.CASCADE, related_name="review")
    store = models.ForeignKey("stores.Store", on_delete=models.CASCADE, related_name="reviews")
    buyer = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="reviews_written")
    rating = models.PositiveSmallIntegerField(validators=[MinValueValidator(1), MaxValueValidator(5)])
    comment = models.TextField(max_length=1000, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        indexes = [models.Index(fields=["store", "-created_at"])]
        ordering = ["-created_at"]
