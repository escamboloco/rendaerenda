from rest_framework import serializers

from apps.catalog.models import Product

from .models import Order, OrderItem, Payment
from .services import _digits


class CheckoutItemSerializer(serializers.Serializer):
    product_id = serializers.UUIDField()
    quantity = serializers.IntegerField(min_value=1, default=1)


class CheckoutSerializer(serializers.Serializer):
    """
    Checkout de uma loja por vez. Guest (sem login) exige nome/e-mail/CPF/nascimento.
    """

    items = CheckoutItemSerializer(many=True)
    shipping_service = serializers.RegexField(r"^(pac|sedex|me-\d+)$", max_length=20)
    shipping_address = serializers.JSONField()
    payment_method = serializers.ChoiceField(choices=["pix", "credit_card", "debit_card", "boleto"])

    guest_name = serializers.CharField(max_length=150, required=False, allow_blank=True)
    guest_email = serializers.EmailField(required=False, allow_blank=True)
    guest_cpf = serializers.CharField(max_length=14, required=False, allow_blank=True)
    guest_birth_date = serializers.DateField(required=False, allow_null=True)

    def validate(self, attrs):
        request = self.context.get("request")
        user = getattr(request, "user", None)
        authenticated = bool(user and getattr(user, "is_authenticated", False))
        if not authenticated:
            missing = []
            if not (attrs.get("guest_name") or "").strip():
                missing.append("guest_name")
            if not (attrs.get("guest_email") or "").strip():
                missing.append("guest_email")
            if len(_digits(attrs.get("guest_cpf"))) != 11:
                missing.append("guest_cpf")
            if not attrs.get("guest_birth_date"):
                missing.append("guest_birth_date")
            if missing:
                raise serializers.ValidationError(
                    {f: "Obrigatório para compra sem cadastro." for f in missing}
                )
        return attrs

    def validate_items(self, items):
        if not items:
            raise serializers.ValidationError("Carrinho vazio.")
        request = self.context.get("request")
        buyer = getattr(request, "user", None)
        authenticated = bool(buyer and getattr(buyer, "is_authenticated", False))
        product_ids = [item["product_id"] for item in items]
        products = {p.id: p for p in Product.objects.filter(id__in=product_ids)}
        store_ids = set()
        for item in items:
            product = products.get(item["product_id"])
            if not product or not product.is_available():
                raise serializers.ValidationError(f"Produto {item['product_id']} indisponível.")
            if product.reserved_for_id and (not authenticated or product.reserved_for_id != buyer.id):
                raise serializers.ValidationError(f"Produto {item['product_id']} indisponível.")
            if item["quantity"] > product.stock:
                raise serializers.ValidationError(f"Estoque insuficiente para {product.title}.")
            store_ids.add(product.store_id)
        if len(store_ids) > 1:
            raise serializers.ValidationError("Todos os itens do pedido devem ser da mesma loja.")
        return items

    def validate_shipping_address(self, value):
        if not isinstance(value, dict):
            raise serializers.ValidationError("Endereço inválido.")
        cep = _digits(value.get("cep", ""))
        if len(cep) != 8:
            raise serializers.ValidationError("CEP inválido.")
        for field in ("street", "number", "neighborhood", "city", "state"):
            if not str(value.get(field, "")).strip():
                raise serializers.ValidationError(f"Informe {field}.")
        value = {**value, "cep": cep}
        return value


class OrderItemSerializer(serializers.ModelSerializer):
    product_title = serializers.CharField(source="product.title", read_only=True)

    class Meta:
        model = OrderItem
        fields = ["product", "product_title", "unit_price", "quantity"]


class PaymentSerializer(serializers.ModelSerializer):
    class Meta:
        model = Payment
        fields = ["method", "status", "provider_charge_id"]


class OrderSerializer(serializers.ModelSerializer):
    items = OrderItemSerializer(many=True, read_only=True)
    payment = PaymentSerializer(read_only=True)
    grand_total = serializers.DecimalField(max_digits=10, decimal_places=2, read_only=True)

    class Meta:
        model = Order
        fields = [
            "id", "status", "items_total", "shipping_total", "grand_total",
            "items", "payment", "created_at",
        ]
        read_only_fields = fields
