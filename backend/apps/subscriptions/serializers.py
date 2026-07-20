from rest_framework import serializers

from .models import SubscriptionPlan


class SubscriptionCheckoutSerializer(serializers.Serializer):
    plan_id = serializers.PrimaryKeyRelatedField(queryset=SubscriptionPlan.objects.filter(is_active=True))
    payment_method = serializers.ChoiceField(choices=["pix", "credit_card", "debit_card", "boleto"])
