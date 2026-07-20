from rest_framework import serializers


class FreightQuoteRequestSerializer(serializers.Serializer):
    destination_cep = serializers.RegexField(r"^\d{8}$")
    product_ids = serializers.ListField(child=serializers.UUIDField(), min_length=1)


class FreightOptionSerializer(serializers.Serializer):
    service = serializers.CharField()
    label = serializers.CharField()
    price = serializers.FloatField()
    deadline_days = serializers.IntegerField()
    company = serializers.CharField(required=False, default="Correios")


class MarkPostedSerializer(serializers.Serializer):
    # Codigo de rastreio dos Correios: 2 letras + 9 digitos + BR
    tracking_code = serializers.RegexField(r"^[A-Z]{2}\d{9}[A-Z]{2}$")
