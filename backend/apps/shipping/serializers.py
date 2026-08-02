from rest_framework import serializers


class FreightQuoteRequestSerializer(serializers.Serializer):
    destination_cep = serializers.RegexField(r"^\d{8}$")
    product_ids = serializers.ListField(child=serializers.UUIDField(), min_length=1)
    # Quantidades por product_id (string UUID). Sem isso, cada id conta 1.
    quantities = serializers.DictField(
        child=serializers.IntegerField(min_value=1, max_value=100),
        required=False,
        default=dict,
    )


class FreightOptionSerializer(serializers.Serializer):
    service = serializers.CharField()
    label = serializers.CharField()
    price = serializers.FloatField()
    deadline_days = serializers.IntegerField()
    company = serializers.CharField(required=False, default="Correios")
    origin_city = serializers.CharField(required=False, allow_blank=True, default="")
    origin_state = serializers.CharField(required=False, allow_blank=True, default="")


class MarkPostedSerializer(serializers.Serializer):
    # Codigo de rastreio dos Correios: 2 letras + 9 digitos + BR
    tracking_code = serializers.RegexField(r"^[A-Z]{2}\d{9}[A-Z]{2}$")
