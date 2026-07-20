from rest_framework import serializers

from .models import Review


class ReviewCreateSerializer(serializers.Serializer):
    order_id = serializers.UUIDField()
    rating = serializers.IntegerField(min_value=1, max_value=5)
    comment = serializers.CharField(max_length=1000, required=False, allow_blank=True, default="")


class ReviewSerializer(serializers.ModelSerializer):
    # Nome de interação (apelido) - nunca o nome civil do comprador na review pública.
    buyer_name = serializers.CharField(source="buyer.interaction_name", read_only=True)

    class Meta:
        model = Review
        fields = ["id", "buyer_name", "rating", "comment", "created_at"]
        read_only_fields = fields
