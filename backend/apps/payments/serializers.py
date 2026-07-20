from rest_framework import serializers

from apps.catalog.models import Product

from .models import Order, OrderItem, Payment


class CheckoutItemSerializer(serializers.Serializer):
    product_id = serializers.UUIDField()
    quantity = serializers.IntegerField(min_value=1, default=1)


class CheckoutSerializer(serializers.Serializer):
    """
    Checkout de uma loja por vez (o split de pagamento e por
    vendedora, entao carrinho misturando lojas viraria N pedidos).
    """

    items = CheckoutItemSerializer(many=True)
    # "pac"/"sedex" (Correios direto) ou "me-<id>" (Melhor Envio) - validado
    # contra as opcoes reais da cotacao na CheckoutView.
    shipping_service = serializers.RegexField(r"^(pac|sedex|me-\d+)$", max_length=20)
    shipping_address = serializers.JSONField()
    payment_method = serializers.ChoiceField(choices=["pix", "credit_card", "debit_card", "boleto"])

    def validate_items(self, items):
        if not items:
            raise serializers.ValidationError("Carrinho vazio.")
        request = self.context.get("request")
        buyer = getattr(request, "user", None)
        product_ids = [item["product_id"] for item in items]
        products = {p.id: p for p in Product.objects.filter(id__in=product_ids)}
        store_ids = set()
        for item in items:
            product = products.get(item["product_id"])
            if not product or not product.is_available():
                raise serializers.ValidationError(f"Produto {item['product_id']} indisponível.")
            # Item de pedido personalizado: so quem encomendou pode comprar.
            if product.reserved_for_id and (buyer is None or product.reserved_for_id != buyer.id):
                raise serializers.ValidationError(f"Produto {item['product_id']} indisponível.")
            if item["quantity"] > product.stock:
                raise serializers.ValidationError(f"Estoque insuficiente para {product.title}.")
            store_ids.add(product.store_id)
        if len(store_ids) > 1:
            raise serializers.ValidationError("Todos os itens do pedido devem ser da mesma loja.")
        return items


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

    class Meta:
        model = Order
        fields = [
            "id", "status", "items_total", "shipping_total", "items",
            "payment", "created_at",
        ]
        read_only_fields = fields
