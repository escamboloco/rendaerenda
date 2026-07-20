from rest_framework import serializers

from .models import Store, StoreBoost, StorePlan


class StoreOnboardSerializer(serializers.Serializer):
    # Sem campo pix_key: a chave de recebimento/saque e SEMPRE o CPF da
    # dona da loja (ver apps.wallet.services.request_withdrawal).
    # Abrir loja e anunciar sao gratuitos - plan_id so existe se, no
    # futuro, a vendedora optar por um plano PAGO opcional (destaque etc.).
    slug = serializers.SlugField(max_length=60)
    display_name = serializers.CharField(max_length=80)
    bio = serializers.CharField(max_length=500, required=False, allow_blank=True)
    # CEP de onde a vendedora posta - origem de toda cotacao de frete e
    # base para achar o ponto de coleta mais proximo dela.
    origin_cep = serializers.RegexField(r"^\d{8}$")
    plan_id = serializers.PrimaryKeyRelatedField(
        queryset=StorePlan.objects.filter(is_active=True), required=False, allow_null=True
    )

    def validate_slug(self, value):
        if Store.objects.filter(slug=value).exists():
            raise serializers.ValidationError("Esse endereço de loja já está em uso.")
        return value


class StoreBoostPurchaseSerializer(serializers.Serializer):
    package_id = serializers.IntegerField()


class StorePlanCheckoutSerializer(serializers.Serializer):
    plan_id = serializers.PrimaryKeyRelatedField(queryset=StorePlan.objects.filter(is_active=True))
    payment_method = serializers.ChoiceField(choices=["pix", "credit_card", "debit_card", "boleto"], default="pix")
