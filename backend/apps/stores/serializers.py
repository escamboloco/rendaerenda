from rest_framework import serializers

from .models import Store, StoreBoost, StorePlan


class StoreOnboardSerializer(serializers.Serializer):
    """
    Abertura de loja.

    A chave Pix é travada no CPF da própria vendedora: o repasse só pode
    cair na conta de quem foi verificada. Chave de terceiro abriria porta
    para conta-laranja e tiraria a rastreabilidade que sustenta a
    verificação de idade (docs/BASE_JURIDICA.md).
    """

    slug = serializers.SlugField(max_length=60)
    display_name = serializers.CharField(max_length=80)
    bio = serializers.CharField(max_length=500, required=False, allow_blank=True)
    origin_cep = serializers.RegexField(r"^\d{8}$")
    origin_street = serializers.CharField(max_length=120)
    origin_number = serializers.CharField(max_length=20)
    origin_complement = serializers.CharField(
        max_length=60, required=False, allow_blank=True
    )
    origin_district = serializers.CharField(max_length=80)
    origin_city = serializers.CharField(max_length=80)
    origin_state = serializers.RegexField(r"^[A-Za-z]{2}$")
    # Chave Pix da vendedora — para onde o Asaas envia o split automaticamente.
    pix_key = serializers.CharField(max_length=140)
    pix_key_type = serializers.ChoiceField(
        choices=["CPF", "CNPJ", "EMAIL", "PHONE", "EVP"], required=False, allow_blank=True
    )
    def validate_slug(self, value):
        if Store.objects.filter(slug=value).exists():
            raise serializers.ValidationError("Esse endereço de loja já está em uso.")
        return value

    def validate_pix_key(self, value):
        import re

        digits = re.sub(r"\D", "", value or "")
        if not digits:
            raise serializers.ValidationError("Informe o CPF que vai receber os repasses.")

        request = self.context.get("request")
        owner_cpf = getattr(getattr(request, "user", None), "cpf", "") or ""
        if owner_cpf and digits != owner_cpf:
            raise serializers.ValidationError(
                "A chave Pix precisa ser o CPF da própria titular da conta. "
                "Não é possível receber em conta de outra pessoa."
            )
        return digits

    def validate_origin_state(self, value):
        return value.upper()

    def validate(self, attrs):
        # Tipo derivado, nunca escolhido: a chave é sempre o CPF da titular.
        attrs["pix_key_type"] = "CPF"
        return attrs


class StoreBoostPurchaseSerializer(serializers.Serializer):
    package_id = serializers.IntegerField()


class StorePlanCheckoutSerializer(serializers.Serializer):
    plan_id = serializers.PrimaryKeyRelatedField(queryset=StorePlan.objects.filter(is_active=True))
    payment_method = serializers.ChoiceField(choices=["pix", "credit_card", "debit_card", "boleto"], default="pix")
