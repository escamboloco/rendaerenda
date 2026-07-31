from rest_framework import serializers

from apps.catalog.models import Product

from .models import Order, OrderItem, Payment
from .services import _digits

UF_LIST = {
    "AC", "AL", "AP", "AM", "BA", "CE", "DF", "ES", "GO", "MA", "MT", "MS",
    "MG", "PA", "PB", "PR", "PE", "PI", "RJ", "RN", "RS", "RO", "RR", "SC",
    "SP", "SE", "TO",
}

ADDRESS_FIELDS = ("street", "number", "neighborhood", "city", "state")
ADDRESS_LABELS = {
    "street": "a rua",
    "number": "o número",
    "neighborhood": "o bairro",
    "city": "a cidade",
    "state": "o estado (UF)",
}


def cpf_is_valid(cpf: str) -> bool:
    """Valida os digitos verificadores do CPF (evita cobranca recusada pelo Asaas)."""
    cpf = _digits(cpf)
    if len(cpf) != 11 or cpf == cpf[0] * 11:
        return False
    for length in (9, 10):
        total = sum(int(cpf[i]) * (length + 1 - i) for i in range(length))
        check = (total * 10) % 11 % 10
        if check != int(cpf[length]):
            return False
    return True


def clean_shipping_address(value):
    """Normaliza e valida o endereço de entrega. Levanta ValidationError."""
    if not isinstance(value, dict):
        raise serializers.ValidationError("Endereço inválido.")
    cep = _digits(value.get("cep", ""))
    if len(cep) != 8:
        raise serializers.ValidationError("Informe um CEP válido com 8 dígitos.")
    for field in ADDRESS_FIELDS:
        if not str(value.get(field, "")).strip():
            raise serializers.ValidationError(f"Informe {ADDRESS_LABELS[field]}.")
    state = str(value["state"]).strip().upper()[:2]
    if state not in UF_LIST:
        raise serializers.ValidationError("UF inválida.")
    return {
        "cep": cep,
        "street": str(value["street"]).strip()[:120],
        "number": str(value["number"]).strip()[:20],
        "complement": str(value.get("complement", "")).strip()[:60],
        "neighborhood": str(value["neighborhood"]).strip()[:80],
        "city": str(value["city"]).strip()[:80],
        "state": state,
    }


class CheckoutItemSerializer(serializers.Serializer):
    product_id = serializers.UUIDField()
    quantity = serializers.IntegerField(min_value=1, max_value=20, default=1)
    # Adicionais opcionais do anúncio ("quer com X?").
    addon_ids = serializers.ListField(
        child=serializers.UUIDField(), required=False, default=list, max_length=10
    )


class CheckoutSerializer(serializers.Serializer):
    """
    Checkout de uma loja por vez. Sem cadastro exige nome, e-mail, CPF e
    data de nascimento (+18) — é o mínimo legal para vender item adulto.
    """

    items = CheckoutItemSerializer(many=True)
    shipping_service = serializers.RegexField(
        r"^(pac|sedex|me-\d+)$", max_length=20, required=False, default="pac"
    )
    # Opcional: pedido só de conteúdo digital não tem entrega física.
    shipping_address = serializers.JSONField(required=False, default=dict)
    # Soft-launch: so Pix (cartao exige tokenizacao Asaas, ainda nao ligada).
    payment_method = serializers.ChoiceField(choices=["pix"], default="pix")

    guest_name = serializers.CharField(max_length=150, required=False, allow_blank=True)
    guest_email = serializers.EmailField(required=False, allow_blank=True)
    guest_cpf = serializers.CharField(max_length=14, required=False, allow_blank=True)
    guest_birth_date = serializers.DateField(required=False, allow_null=True)
    # Opt-in explicito LGPD — default False (nunca pre-marcado na tela).
    marketing_opt_in = serializers.BooleanField(required=False, default=False)

    def validate(self, attrs):
        # Endereço só é exigido quando existe item físico na sacola.
        if self._needs_shipping(attrs.get("items") or []):
            try:
                attrs["shipping_address"] = clean_shipping_address(attrs.get("shipping_address"))
            except serializers.ValidationError as exc:
                raise serializers.ValidationError({"shipping_address": exc.detail}) from exc
        else:
            attrs["shipping_address"] = {}

        request = self.context.get("request")
        user = getattr(request, "user", None)
        if bool(user and getattr(user, "is_authenticated", False)):
            return attrs

        errors = {}
        if not (attrs.get("guest_name") or "").strip():
            errors["guest_name"] = "Informe seu nome completo."
        if not (attrs.get("guest_email") or "").strip():
            errors["guest_email"] = "Informe um e-mail para receber o pedido."
        if not cpf_is_valid(attrs.get("guest_cpf") or ""):
            errors["guest_cpf"] = "CPF inválido."
        if not attrs.get("guest_birth_date"):
            errors["guest_birth_date"] = "Informe sua data de nascimento."
        if errors:
            raise serializers.ValidationError(errors)
        return attrs

    def validate_items(self, items):
        if not items:
            raise serializers.ValidationError("Sua sacola está vazia.")
        request = self.context.get("request")
        buyer = getattr(request, "user", None)
        authenticated = bool(buyer and getattr(buyer, "is_authenticated", False))

        wanted: dict = {}
        for item in items:
            wanted[item["product_id"]] = wanted.get(item["product_id"], 0) + item["quantity"]

        products = {p.id: p for p in Product.objects.select_related("store").filter(id__in=list(wanted))}
        store_ids = set()
        for product_id, quantity in wanted.items():
            product = products.get(product_id)
            if not product or not product.is_available():
                raise serializers.ValidationError("Um dos itens da sacola não está mais disponível.")
            if product.reserved_for_id and (not authenticated or product.reserved_for_id != buyer.id):
                raise serializers.ValidationError("Um dos itens da sacola não está mais disponível.")
            if quantity > product.stock:
                raise serializers.ValidationError(f"Estoque insuficiente para “{product.title}”.")
            store_ids.add(product.store_id)
        if len(store_ids) > 1:
            raise serializers.ValidationError("Finalize uma loja por vez.")
        return items

    @staticmethod
    def _needs_shipping(items) -> bool:
        ids = [item["product_id"] for item in items]
        if not ids:
            return False
        return Product.objects.filter(id__in=ids, kind=Product.Kind.PHYSICAL).exists()


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
