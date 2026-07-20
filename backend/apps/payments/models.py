import uuid
from decimal import Decimal

from django.conf import settings
from django.core.validators import MinValueValidator
from django.db import models

from apps.catalog.models import Product
from apps.stores.models import Store


class Order(models.Model):
    """
    Pedido de compra de item fisico entre comprador e vendedora. A
    plataforma NUNCA e dona do produto nem processa o dinheiro
    diretamente - o pagamento e feito via PSP (Asaas/Iugu) com split
    automatico. Ver apps.payments.services.PaymentProvider.

    Fluxo de valores (docs/checkout.md): a vendedora recebe exatamente o
    payout_amount que ela declarou em cada item (nunca items_total, que
    ja embute a comissao). O frete NAO vai para a vendedora - a
    etiqueta e comprada automaticamente pela plataforma (Melhor Envio/
    Correios) e entregue pronta pra ela colar, entao o valor do frete
    pago pelo comprador cobre esse custo e fica com a plataforma.
    """

    class Status(models.TextChoices):
        AWAITING_PAYMENT = "awaiting_payment", "Aguardando pagamento"
        PAID = "paid", "Pago"
        SHIPPED = "shipped", "Enviado"
        DELIVERED = "delivered", "Entregue"
        DISPUTED = "disputed", "Em disputa"
        CANCELED = "canceled", "Cancelado"
        REFUNDED = "refunded", "Reembolsado"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    buyer = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="orders")
    store = models.ForeignKey(Store, on_delete=models.PROTECT, related_name="orders")
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.AWAITING_PAYMENT)

    items_total = models.DecimalField(max_digits=10, decimal_places=2)
    shipping_total = models.DecimalField(max_digits=8, decimal_places=2, default=Decimal("0.00"))
    packaging_fee = models.DecimalField(
        max_digits=6, decimal_places=2, default=Decimal("0.00"),
        help_text="Já somado a shipping_total - guardado à parte só para exibir o detalhamento ao comprador.",
    )

    shipping_address = models.JSONField()
    created_at = models.DateTimeField(auto_now_add=True)
    paid_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        indexes = [models.Index(fields=["status"]), models.Index(fields=["buyer", "status"])]

    @property
    def grand_total(self) -> Decimal:
        return self.items_total + self.shipping_total

    @property
    def payout_total(self) -> Decimal:
        """Soma do que cada vendedora declarou querer receber (snapshot por item)."""
        return sum((item.unit_payout_amount * item.quantity for item in self.items.all()), Decimal("0.00"))

    @property
    def seller_amount(self) -> Decimal:
        # So o valor dos itens - frete/embalagem cobre a etiqueta que a
        # PLATAFORMA compra automaticamente (nunca vai pra vendedora).
        return self.payout_total

    @property
    def platform_amount(self) -> Decimal:
        return (self.items_total - self.payout_total) + self.shipping_total


class OrderItem(models.Model):
    order = models.ForeignKey(Order, on_delete=models.CASCADE, related_name="items")
    product = models.ForeignKey(Product, on_delete=models.PROTECT, related_name="order_items")
    unit_price = models.DecimalField(max_digits=8, decimal_places=2, validators=[MinValueValidator(Decimal("0.01"))])
    # Snapshot do payout_amount do produto no momento da compra - congela o
    # valor combinado com a vendedora mesmo se ela editar o anúncio depois.
    unit_payout_amount = models.DecimalField(
        max_digits=8, decimal_places=2, validators=[MinValueValidator(Decimal("0.01"))], default=Decimal("0.01")
    )
    quantity = models.PositiveSmallIntegerField(default=1)


class Payment(models.Model):
    """Registro da cobranca no PSP (Asaas/Iugu) para o pedido."""

    class Method(models.TextChoices):
        PIX = "pix", "Pix"
        CREDIT_CARD = "credit_card", "Cartão de crédito"
        DEBIT_CARD = "debit_card", "Cartão de débito"
        BOLETO = "boleto", "Boleto"

    class Status(models.TextChoices):
        PENDING = "pending", "Pendente"
        CONFIRMED = "confirmed", "Confirmado"
        FAILED = "failed", "Falhou"
        REFUNDED = "refunded", "Reembolsado"

    order = models.OneToOneField(Order, on_delete=models.CASCADE, related_name="payment")
    provider = models.CharField(max_length=20, default=settings.PAYMENT_PROVIDER)
    provider_charge_id = models.CharField(max_length=100, blank=True)
    method = models.CharField(max_length=15, choices=Method.choices)
    status = models.CharField(max_length=10, choices=Status.choices, default=Status.PENDING)
    split_confirmed = models.BooleanField(
        default=False, help_text="True quando o PSP confirma que o split para a subconta da vendedora foi feito."
    )
    # Trava "pagamento so pelo CPF do titular": documento de quem pagou
    # (informado pelo PSP) e o resultado da conferencia contra buyer.cpf.
    # matched=False significa que o pagamento foi estornado automaticamente.
    # None = PSP nao informou o pagador (cobranca ja e do customer titular).
    payer_document = models.CharField(max_length=14, blank=True)
    payer_cpf_matched = models.BooleanField(null=True, blank=True)
    raw_webhook_payload = models.JSONField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    confirmed_at = models.DateTimeField(null=True, blank=True)


class Invoice(models.Model):
    """
    NFS-e emitida PELA PLATAFORMA sobre o servico dela (comissao de
    intermediacao, assinatura de comprador, plano de loja, boost). A
    plataforma NAO e vendedora do item, entao nunca emite NF do item -
    a responsabilidade fiscal da venda e da vendedora (Termos de Uso).
    Emissao assincrona via Celery (apps.payments.tasks) apos o
    pagamento confirmado; o comprador recebe o link por e-mail.
    """

    class Kind(models.TextChoices):
        ORDER_COMMISSION = "order_commission", "Comissão de intermediação (pedido)"
        BUYER_SUBSCRIPTION = "buyer_subscription", "Assinatura de comprador"
        STORE_PLAN = "store_plan", "Plano de loja"
        BOOST = "boost", "Boost"

    class Status(models.TextChoices):
        PENDING = "pending", "Aguardando emissão"
        ISSUED = "issued", "Emitida"
        FAILED = "failed", "Falhou"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    kind = models.CharField(max_length=20, choices=Kind.choices)
    order = models.OneToOneField(Order, on_delete=models.PROTECT, null=True, blank=True, related_name="invoice")
    reference_id = models.CharField(max_length=100, help_text="Cobrança/assinatura no PSP a que a NF se refere.")
    # Tomador do servico - identidade CIVIL, nunca o apelido (obrigacao fiscal).
    recipient_name = models.CharField(max_length=150)
    recipient_cpf = models.CharField(max_length=11)
    recipient_email = models.EmailField()
    amount = models.DecimalField(max_digits=10, decimal_places=2, help_text="Valor do serviço da plataforma.")
    description = models.CharField(max_length=200)
    status = models.CharField(max_length=10, choices=Status.choices, default=Status.PENDING)
    provider_invoice_id = models.CharField(max_length=100, blank=True)
    pdf_url = models.URLField(blank=True)
    issued_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        indexes = [models.Index(fields=["status", "kind"])]
