from decimal import Decimal

from rest_framework import serializers

from .models import CustomOrderRequest


class CustomRequestCreateSerializer(serializers.Serializer):
    store_slug = serializers.SlugField()
    title = serializers.CharField(max_length=120)
    description = serializers.CharField(max_length=2000)
    offered_price = serializers.DecimalField(max_digits=8, decimal_places=2, min_value=Decimal("1"))


class SellerResponseSerializer(serializers.Serializer):
    action = serializers.ChoiceField(choices=["accept", "reject", "counter"])
    counter_price = serializers.DecimalField(
        max_digits=8, decimal_places=2, min_value=Decimal("1"), required=False
    )
    counter_message = serializers.CharField(max_length=500, required=False, allow_blank=True, default="")

    def validate(self, data):
        if data["action"] == "counter" and "counter_price" not in data:
            raise serializers.ValidationError("Informe o valor da contra-proposta.")
        return data


class CustomRequestSerializer(serializers.ModelSerializer):
    # Interacao usa apelido/nome social - NUNCA nome civil (privacidade).
    buyer_name = serializers.CharField(source="buyer.interaction_name", read_only=True)
    store_name = serializers.CharField(source="store.display_name", read_only=True)
    final_price = serializers.DecimalField(max_digits=8, decimal_places=2, read_only=True)
    product_url = serializers.SerializerMethodField()

    class Meta:
        model = CustomOrderRequest
        fields = [
            "id", "buyer_name", "store_name", "title", "description",
            "offered_price", "counter_price", "counter_message", "final_price",
            "status", "product_url", "created_at", "responded_at",
        ]
        read_only_fields = fields

    def get_product_url(self, obj):
        if obj.product_id and obj.status == CustomOrderRequest.Status.ACCEPTED:
            from django.urls import reverse

            return reverse("catalog:detail", args=[obj.store.slug, obj.product.slug])
        return None
