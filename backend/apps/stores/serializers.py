from rest_framework import serializers

from .models import Store, StoreBoost, StorePlan


class StoreOnboardSerializer(serializers.Serializer):
    slug = serializers.SlugField(max_length=60)
    display_name = serializers.CharField(max_length=80)
    bio = serializers.CharField(max_length=500, required=False, allow_blank=True)
    origin_cep = serializers.RegexField(r"^\d{8}$")
    # Chave Pix da vendedora — para onde o Asaas envia o split automaticamente.
    pix_key = serializers.CharField(max_length=140)
    pix_key_type = serializers.ChoiceField(
        choices=["CPF", "CNPJ", "EMAIL", "PHONE", "EVP"], required=False, allow_blank=True
    )
    plan_id = serializers.PrimaryKeyRelatedField(
        queryset=StorePlan.objects.filter(is_active=True), required=False, allow_null=True
    )

    def validate_slug(self, value):
        if Store.objects.filter(slug=value).exists():
            raise serializers.ValidationError("Esse endereço de loja já está em uso.")
        return value

    def validate_pix_key(self, value):
        value = (value or "").strip()
        if not value:
            raise serializers.ValidationError("Informe a chave Pix para receber.")
        return value


class StoreBoostPurchaseSerializer(serializers.Serializer):
    package_id = serializers.IntegerField()


class StorePlanCheckoutSerializer(serializers.Serializer):
    plan_id = serializers.PrimaryKeyRelatedField(queryset=StorePlan.objects.filter(is_active=True))
    payment_method = serializers.ChoiceField(choices=["pix", "credit_card", "debit_card", "boleto"], default="pix")
