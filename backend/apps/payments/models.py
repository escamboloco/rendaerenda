import uuid
from decimal import Decimal

from django.conf import settings
from django.core.validators import MinValueValidator
from django.db import models

from apps.catalog.models import Product
from apps.stores.models import Store


class Order(models.Model):
    """
    Pedido entre comprador e vendedora. A plataforma so intermedia:
    nao vende o item. Pagamento via Asaas.

    Repasse: vendedora recebe payout_amount (o liquido que ela pediu) +
    frete; a plataforma fica so com a comissao
    (settings.PLATFORM_COMMISSION_PERCENT) ja embutida em items_total.
    Compra pode ser guest (sem conta): buyer null + campos guest_*.

    O estoque e reservado na criacao do pedido e devolvido se o Pix nao
    for pago ate `expires_at` (management command expire_orders).
    """

    class Status(models.TextChoices):
        AWAITING_PAYMENT = "awaiting_payment", "Aguardando pagamento"
        PAID = "paid", "Pago"
        SHIPPED = "shipped", "Enviado"
        DELIVERED = "delivered", "Entregue"
        DISPUTED = "disputed", "Em disputa"
        CANCELED = "canceled", "Cancelado"
        EXPIRED = "expired", "Expirado (não pago)"
        REFUNDED = "refunded", "Reembolsado"

    # Estados em que o estoque continua reservado para o pedido.
    RESERVING_STATUSES = ("awaiting_payment", "paid", "shipped", "delivered", "disputed")

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    buyer = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="orders", null=True, blank=True
    )
    guest_name = models.CharField(max_length=150, blank=True)
    guest_email = models.EmailField(blank=True)
    guest_cpf = models.CharField(max_length=11, blank=True)
    guest_birth_date = models.DateField(null=True, blank=True)
    access_token = models.CharField(max_length=64, unique=True, db_index=True)

    store = models.ForeignKey(Store, on_delete=models.PROTECT, related_name="orders")
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.AWAITING_PAYMENT)

    items_total = models.DecimalField(max_digits=10, decimal_places=2)
    shipping_total = models.DecimalField(max_digits=8, decimal_places=2, default=Decimal("0.00"))
    packaging_fee = models.DecimalField(
        max_digits=6,
        decimal_places=2,
        default=Decimal("0.00"),
        help_text=(
            "Parcela da embalagem neutra embutida no frete. Com etiqueta "
            "pela plataforma, só este valor é creditado à vendedora; o "
            "restante do shipping_total compra a etiqueta."
        ),
    )

    # Vazio ({}) em pedido só de conteúdo digital — não existe entrega física.
    shipping_address = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    paid_at = models.DateTimeField(null=True, blank=True)
    # Ate quando o Pix deste pedido pode ser pago. Passou disso sem
    # pagamento, o pedido expira e o estoque volta para a vitrine.
    expires_at = models.DateTimeField(null=True, blank=True)
    canceled_reason = models.CharField(max_length=80, blank=True)
    # Quando o dinheiro saiu da custódia para a vendedora. Trava de
    # idempotência do repasse: preenchido, nunca mais paga de novo.
    payout_sent_at = models.DateTimeField(null=True, blank=True)
    # Repasse do frete + embalagem, feito assim que o pagamento confirma.
    # Separado de payout_sent_at porque sai antes e por outro motivo.
    shipping_payout_sent_at = models.DateTimeField(null=True, blank=True)
    # Trava de idempotencia: garante que o estoque so volta uma vez,
    # mesmo com webhook repetido + cron de expiracao rodando junto.
    stock_restored = models.BooleanField(default=False)

    class Meta:
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["status"]),
            models.Index(fields=["buyer", "status"]),
            models.Index(fields=["status", "expires_at"]),
            models.Index(fields=["store", "status"]),
        ]

    def __str__(self):
        return f"Pedido {str(self.id)[:8]} — {self.get_status_display()}"

    @property
    def short_id(self) -> str:
        return str(self.id)[:8].upper()

    @property
    def is_open_for_payment(self) -> bool:
        return self.status == self.Status.AWAITING_PAYMENT

    @property
    def track_url(self) -> str:
        return f"/pedido/{self.access_token}/" if self.access_token else "/compras/"

    @property
    def payer_cpf(self) -> str:
        if self.buyer_id and self.buyer.cpf:
            return self.buyer.cpf
        return self.guest_cpf

    @property
    def payer_name(self) -> str:
        if self.buyer_id:
            return self.buyer.get_full_name() or self.buyer.username
        return self.guest_name

    @property
    def payer_email(self) -> str:
        if self.buyer_id:
            return self.buyer.email
        return self.guest_email

    @property
    def grand_total(self) -> Decimal:
        return self.items_total + self.shipping_total

    @property
    def payout_total(self) -> Decimal:
        """Soma do que a vendedora declarou querer receber (itens + adicionais)."""
        return sum((item.line_payout for item in self.items.all()), Decimal("0.00"))

    @property
    def requires_shipping(self) -> bool:
        """Pedido só de conteúdo digital não tem endereço, frete nem rastreio."""
        return any(item.product.requires_shipping for item in self.items.all())

    @property
    def is_digital_only(self) -> bool:
        return not self.requires_shipping

    @property
    def seller_amount(self) -> Decimal:
        """
        O que a vendedora recebe no split/repasse:
        - etiqueta pela plataforma: payout + embalagem neutra;
        - modo legado: payout + frete inteiro.
        """
        from apps.shipping.services import platform_buys_shipping_label

        if platform_buys_shipping_label():
            return self.payout_total + (self.packaging_fee or Decimal("0.00"))
        return self.payout_total + self.shipping_total

    @property
    def platform_amount(self) -> Decimal:
        """Comissão do item (+ frete da transportadora se a plataforma compra a etiqueta)."""
        from apps.shipping.services import platform_buys_shipping_label

        commission = self.items_total - self.payout_total
        if platform_buys_shipping_label():
            carrier = self.shipping_total - (self.packaging_fee or Decimal("0.00"))
            return commission + max(carrier, Decimal("0.00"))
        return commission


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

    # Adicionais escolhidos ("quer com X?"). Guardados como snapshot: o
    # que foi combinado nao muda se a vendedora editar o anuncio depois.
    addons = models.JSONField(default=list, blank=True)
    addons_price = models.DecimalField(max_digits=8, decimal_places=2, default=Decimal("0.00"))
    addons_payout = models.DecimalField(max_digits=8, decimal_places=2, default=Decimal("0.00"))

    @property
    def line_price(self) -> Decimal:
        return self.unit_price * self.quantity + self.addons_price

    @property
    def line_payout(self) -> Decimal:
        return self.unit_payout_amount * self.quantity + self.addons_payout


class OrderMessage(models.Model):
    """
    Conversa privada entre comprador e vendedora, presa a um pedido.

    Existe para o combinado de item sob encomenda e para resolver dúvida
    de entrega sem ninguém precisar trocar telefone. Passa pelo mesmo
    filtro anti-contato-externo do resto da plataforma: a conversa tem
    que ficar aqui, onde a moderação enxerga (docs/BASE_JURIDICA.md § 3).
    """

    class Sender(models.TextChoices):
        BUYER = "buyer", "Comprador"
        SELLER = "seller", "Vendedora"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    order = models.ForeignKey(Order, on_delete=models.CASCADE, related_name="messages")
    sender = models.CharField(max_length=6, choices=Sender.choices)
    body = models.TextField(max_length=1000)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["created_at"]
        indexes = [models.Index(fields=["order", "created_at"])]

    def __str__(self):
        return f"{self.get_sender_display()} — pedido {self.order.short_id}"


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
    provider_charge_id = models.CharField(max_length=100, blank=True, db_index=True)
    method = models.CharField(max_length=15, choices=Method.choices)
    status = models.CharField(max_length=10, choices=Status.choices, default=Status.PENDING)

    # Dados do Pix guardados para a pessoa poder voltar ao pedido pelo link
    # do e-mail e continuar pagando sem gerar uma cobranca nova.
    payment_url = models.URLField(blank=True)
    pix_qr_code = models.TextField(blank=True, help_text="Imagem do QR em data URL.")
    pix_copy_paste = models.TextField(blank=True)
    pix_expires_at = models.DateTimeField(null=True, blank=True)
    # Ultimo status bruto retornado pelo PSP (RECEIVED, CONFIRMED, OVERDUE...).
    provider_status = models.CharField(max_length=40, blank=True)
    last_synced_at = models.DateTimeField(null=True, blank=True)
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
