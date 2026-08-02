"""
Dominio do checkout: transformar um carrinho em pedido pago.

Separado das views de proposito — a mesma logica e usada pela API do
checkout, pelo webhook do Asaas, pelo polling da pagina de pagamento e
pelos crons de expiracao/reconciliacao.

Sequencia de uma compra:

  1. reserve_order()   — transacao curta: valida, trava os produtos com
                         SELECT FOR UPDATE, baixa estoque e cria o pedido
                         com prazo de expiracao.
  2. create_charge_for_order() — chamada HTTP ao Asaas FORA da transacao
                         (nunca segurar lock de linha esperando rede).
  3. confirm_paid_order()      — idempotente: marca pago, credita a
                         vendedora, dispara Pix de repasse e e-mails.
  4. expire_order() / cancel_order() — devolve o estoque uma unica vez.
"""
from __future__ import annotations

import logging
import secrets
from dataclasses import dataclass
from datetime import timedelta
from decimal import Decimal

from django.conf import settings
from django.db import transaction
from django.db.models import F
from django.utils import timezone

from apps.catalog.models import Product
from apps.shipping.models import Shipment

from . import services
from .asaas import AsaasError
from .models import Order, OrderItem, Payment

logger = logging.getLogger(__name__)

ZERO = Decimal("0.00")


class CheckoutError(Exception):
    """Erro de checkout ja pronto para virar resposta HTTP."""

    def __init__(self, detail: str, status_code: int = 400):
        super().__init__(detail)
        self.detail = detail
        self.status_code = status_code


@dataclass(frozen=True)
class CartLine:
    product_id: str
    quantity: int
    # Ids dos adicionais escolhidos para este item ("quer com X?").
    addon_ids: tuple[str, ...] = ()


def order_ttl_minutes() -> int:
    return int(getattr(settings, "ORDER_PAYMENT_TTL_MINUTES", 60))


# --------------------------------------------------------------------------
# 0. Frete
# --------------------------------------------------------------------------

def quote_shipping(*, lines: list[CartLine], destination_cep: str, preferred_service: str = "pac"):
    """
    Cotacao de frete do checkout. Roda ANTES da reserva porque pode fazer
    chamada externa (Melhor Envio) — nunca dentro da transacao que trava
    o estoque.

    Com CHECKOUT_FREE_SHIPPING (padrao no lancamento) devolve frete zero
    sem falar com ninguem.
    """
    from apps.shipping.services import (
        FreightOption,
        calculate_freight_options,
        products_are_payment_test,
        test_free_freight_option,
    )

    ids = [str(line.product_id) for line in lines]
    products = list(Product.objects.select_related("store").filter(id__in=ids))
    if not products:
        raise CheckoutError("Um dos itens da sacola não está mais disponível.")

    products = [p for p in products if p.requires_shipping]
    if not products:
        # Sacola só de conteúdo digital: nada a enviar.
        return test_free_freight_option()

    if getattr(settings, "CHECKOUT_FREE_SHIPPING", True) or products_are_payment_test(products):
        return test_free_freight_option()

    quantities = {str(line.product_id): line.quantity for line in lines}
    weight = sum(p.weight_grams * quantities.get(str(p.id), 1) for p in products)
    origin_cep = products[0].store.origin_cep

    if not origin_cep:
        raise CheckoutError(
            "Esta loja ainda não cadastrou o CEP de postagem — o frete não pode ser calculado."
        )

    try:
        options = calculate_freight_options(
            destination_cep=destination_cep,
            weight_grams=weight,
            length_cm=max(p.length_cm for p in products),
            width_cm=max(p.width_cm for p in products),
            height_cm=sum(p.height_cm * quantities.get(str(p.id), 1) for p in products),
            origin_cep=origin_cep,
            declared_value=sum(p.price for p in products),
        )
    except Exception:
        # Transportadora fora do ar ou sem contrato: cai para a tarifa fixa
        # em vez de derrubar a venda. Se a tarifa for zero, o frete some e
        # a vendedora fica no prejuizo — por isso o valor e configuravel e
        # esta no checklist de producao.
        logger.exception("Falha ao cotar frete para o CEP %s*** — usando tarifa fixa.", destination_cep[:5])
        options = []

    if not options:
        flat = Decimal(str(getattr(settings, "SHIPPING_FLAT_RATE", 0) or 0))
        options = [
            FreightOption(
                service="pac",
                label="Envio com rastreio",
                price=float(flat),
                deadline_days=8,
                company="Correios",
            )
        ]
    chosen = next((o for o in options if o.service == preferred_service), options[0])

    # Embalagem neutra embutida no frete: com etiqueta pela plataforma,
    # só essa parcela vai para a vendedora; o restante compra a etiqueta.
    from apps.shipping.packaging import neutral_box_for

    box = neutral_box_for(
        weight_grams=weight,
        length_cm=max(p.length_cm for p in products),
        width_cm=max(p.width_cm for p in products),
        height_cm=sum(p.height_cm * quantities.get(str(p.id), 1) for p in products),
    )
    packaging = box.price + Decimal(str(getattr(settings, "PACKAGING_FEE", 0) or 0))
    return FreightOption(
        service=chosen.service,
        label=f"{chosen.label} + {box.label.lower()}" if packaging else chosen.label,
        price=float(Decimal(str(chosen.price)) + packaging),
        deadline_days=chosen.deadline_days,
        company=chosen.company,
        packaging_amount=float(packaging),
    )


# --------------------------------------------------------------------------
# 1. Reserva
# --------------------------------------------------------------------------

@transaction.atomic
def reserve_order(
    *,
    lines: list[CartLine],
    buyer=None,
    guest_name: str = "",
    guest_email: str = "",
    guest_cpf: str = "",
    guest_birth_date=None,
    shipping_address: dict,
    shipping_service: str = "pac",
    shipping_total: Decimal = ZERO,
    packaging_fee: Decimal = ZERO,
    shipping_deadline_days: int = 7,
) -> Order:
    """
    Cria o pedido baixando o estoque sob lock. Transacao curta e sem I/O
    externo — e o unico ponto do sistema autorizado a reduzir estoque.
    """
    if not lines:
        raise CheckoutError("Sua sacola está vazia.")

    # Agrupa linhas repetidas do mesmo produto: sem isso, dois itens iguais
    # no carrinho passariam duas validacoes de estoque de 1 unidade cada.
    wanted: dict[str, int] = {}
    chosen_addons: dict[str, set[str]] = {}
    for line in lines:
        key = str(line.product_id)
        wanted[key] = wanted.get(key, 0) + int(line.quantity)
        chosen_addons.setdefault(key, set()).update(str(a) for a in (line.addon_ids or ()))

    products = {
        str(p.id): p
        for p in Product.objects.select_for_update()
        .select_related("store", "store__owner")
        .filter(id__in=list(wanted))
    }
    if len(products) != len(wanted):
        raise CheckoutError("Um dos itens da sacola não está mais disponível.")

    stores = {p.store_id for p in products.values()}
    if len(stores) > 1:
        raise CheckoutError("Finalize uma loja por vez — separe os itens em pedidos diferentes.")

    store = next(iter(products.values())).store
    if not store.is_public():
        raise CheckoutError("Esta loja não está disponível no momento.")

    addons_by_product = _load_addons(chosen_addons)

    items_total = ZERO
    reserved: list[tuple[Product, int, list]] = []
    for product_id, quantity in wanted.items():
        product = products[product_id]
        if not product.is_available():
            raise CheckoutError(f"“{product.title}” não está mais disponível.")
        if product.reserved_for_id and (not buyer or product.reserved_for_id != buyer.id):
            raise CheckoutError(f"“{product.title}” é um pedido personalizado de outra pessoa.")
        # Revalida o estoque JA com o lock: a validacao do serializer roda
        # sem lock e pode estar velha quando duas pessoas compram o ultimo.
        if quantity > product.stock:
            raise CheckoutError(
                f"Restou {product.stock} unidade(s) de “{product.title}”. Ajuste a quantidade."
                if product.stock
                else f"“{product.title}” acabou de ser vendido."
            )
        addons = addons_by_product.get(product_id, [])
        items_total += product.price * quantity + sum((a.price for a in addons), ZERO)
        reserved.append((product, quantity, addons))

    needs_shipping = any(product.requires_shipping for product, _, _ in reserved)
    if not needs_shipping:
        # Pedido só de conteúdo digital: sem endereço, sem frete, sem envio.
        shipping_address = {}
        shipping_total = ZERO
        packaging_fee = ZERO

    order = Order.objects.create(
        buyer=buyer,
        guest_name="" if buyer else guest_name,
        guest_email="" if buyer else guest_email,
        guest_cpf="" if buyer else guest_cpf,
        guest_birth_date=None if buyer else guest_birth_date,
        access_token=secrets.token_urlsafe(32),
        store=store,
        items_total=items_total,
        shipping_total=shipping_total,
        packaging_fee=packaging_fee,
        shipping_address=shipping_address,
        expires_at=timezone.now() + timedelta(minutes=order_ttl_minutes()),
    )

    OrderItem.objects.bulk_create(
        [
            OrderItem(
                order=order,
                product=product,
                unit_price=product.price,
                unit_payout_amount=product.payout_amount,
                quantity=quantity,
                addons=[
                    {"id": str(a.id), "title": a.title, "price": str(a.price), "payout": str(a.payout_amount)}
                    for a in addons
                ],
                addons_price=sum((a.price for a in addons), ZERO),
                addons_payout=sum((a.payout_amount for a in addons), ZERO),
            )
            for product, quantity, addons in reserved
        ]
    )

    for product, quantity, _ in reserved:
        Product.objects.filter(pk=product.pk).update(stock=F("stock") - quantity)
        product.refresh_from_db(fields=["stock"])
        if product.stock == 0 and product.status == Product.Status.PUBLISHED:
            Product.objects.filter(pk=product.pk).update(status=Product.Status.SOLD)

    if needs_shipping:
        Shipment.objects.create(
            order=order,
            service=shipping_service,
            estimated_delivery_days=shipping_deadline_days,
        )
    return order


def _load_addons(chosen: dict[str, set[str]]) -> dict[str, list]:
    """
    Carrega os adicionais escolhidos conferindo que cada um pertence mesmo
    ao produto da linha — o navegador manda só o id, o preço vem daqui.
    """
    from apps.catalog.models import ProductAddon

    all_ids = {addon_id for ids in chosen.values() for addon_id in ids}
    if not all_ids:
        return {}
    found = ProductAddon.objects.filter(id__in=all_ids, is_active=True)
    by_product: dict[str, list] = {}
    valid_ids = set()
    for addon in found:
        product_id = str(addon.product_id)
        if str(addon.id) in chosen.get(product_id, set()):
            by_product.setdefault(product_id, []).append(addon)
            valid_ids.add(str(addon.id))
    if valid_ids != all_ids:
        raise CheckoutError("Um dos adicionais escolhidos não está mais disponível.")
    return by_product


# --------------------------------------------------------------------------
# 2. Cobranca
# --------------------------------------------------------------------------

def order_return_url(order: Order) -> str:
    """
    URL absoluta da pagina do pedido, usada como retorno do checkout
    hospedado do Asaas (cartao). Precisa ser absoluta: quem redireciona e
    o PSP, nao o nosso servidor.
    """
    domain = (getattr(settings, "SITE_DOMAIN", "") or "").strip()
    if not domain:
        return ""
    scheme = "http" if getattr(settings, "DEBUG", False) else "https"
    return f"{scheme}://{domain}{order.track_url}"


def create_charge_for_order(order: Order, *, method: str = "pix") -> Payment:
    """
    Cria a cobranca no PSP e guarda o Pix no pedido. Chamado FORA de
    transacao: se o Asaas falhar, o pedido e cancelado e o estoque volta.
    """
    if not services.payment_is_configured():
        cancel_order(order, reason="pagamento_nao_configurado")
        raise CheckoutError(
            "Pagamento indisponível no momento. Nenhuma cobrança foi feita — tente de novo em instantes.",
            status_code=503,
        )

    store = order.store
    provider = services.get_payment_provider()
    try:
        charge = provider.create_split_charge(
            order_id=str(order.id),
            method=method,
            total_amount=order.grand_total,
            seller_subaccount_id=store.psp_subaccount_id,
            seller_amount=order.seller_amount,
            platform_amount=order.platform_amount,
            customer_cpf=order.payer_cpf,
            customer_name=order.payer_name,
            customer_email=order.payer_email,
            return_url=order_return_url(order),
        )
    except AsaasError as exc:
        cancel_order(order, reason="falha_cobranca")
        raise CheckoutError(exc.user_message, status_code=502) from exc
    except Exception as exc:  # pragma: no cover - defesa contra provider novo
        logger.exception("Falha inesperada ao criar a cobranca do pedido %s", order.id)
        cancel_order(order, reason="falha_cobranca")
        raise CheckoutError(
            "Não foi possível gerar a cobrança. Nenhum valor foi cobrado — tente novamente.",
            status_code=502,
        ) from exc

    if method != "pix" and not charge.payment_url:
        # Cartão depende da página hospedada do Asaas: sem ela, a pessoa
        # ficaria com um pedido sem nenhuma forma de pagar.
        cancel_order(order, reason="sem_link_pagamento")
        raise CheckoutError(
            "Não foi possível abrir a página de pagamento. Nada foi cobrado — tente com Pix.",
            status_code=502,
        )

    payment = Payment.objects.create(
        order=order,
        provider_charge_id=charge.provider_charge_id,
        method=method,
        payment_url=charge.payment_url or "",
        pix_qr_code=charge.pix_qr_code or "",
        pix_copy_paste=charge.pix_copy_paste or "",
        provider_status=charge.status,
        last_synced_at=timezone.now(),
    )
    if charge.is_paid:
        # Raro, mas possivel (cobranca ja quitada na criacao).
        confirm_paid_order(payment)
    return payment


# --------------------------------------------------------------------------
# 3. Confirmacao (idempotente)
# --------------------------------------------------------------------------

def confirm_paid_order(payment: Payment, webhook_payload: dict | None = None) -> bool:
    """
    Marca o pedido como pago, credita a vendedora e dispara os e-mails.

    Idempotente: chamado varias vezes (webhook do Asaas repete entrega,
    e o polling da pagina roda em paralelo) so tem efeito na primeira.
    Retorna True se ESTA chamada foi a que confirmou o pedido.
    """
    from apps.stores.services import increment_sales_count
    from apps.wallet.services import credit_and_auto_payout

    with transaction.atomic():
        # Lock da linha: duas confirmacoes simultaneas nao podem creditar duas vezes.
        locked = (
            Payment.objects.select_for_update()
            .select_related("order", "order__store")
            .get(pk=payment.pk)
        )
        if locked.status == Payment.Status.CONFIRMED:
            return False
        if locked.status == Payment.Status.REFUNDED:
            return False

        order = locked.order
        if webhook_payload:
            locked.raw_webhook_payload = webhook_payload

        if not services.verify_payer_cpf(locked, webhook_payload):
            locked.status = Payment.Status.REFUNDED
            locked.save()
            order.status = Order.Status.REFUNDED
            order.canceled_reason = "cpf_pagador_divergente"
            order.save(update_fields=["status", "canceled_reason"])
            restore_stock(order)
            return False

        locked.status = Payment.Status.CONFIRMED
        locked.split_confirmed = True
        locked.confirmed_at = timezone.now()
        locked.last_synced_at = timezone.now()
        locked.save()

        order.status = Order.Status.PAID
        order.paid_at = timezone.now()
        order.expires_at = None
        order.save(update_fields=["status", "paid_at", "expires_at"])

    # Efeitos colaterais fora da transacao: dinheiro e e-mail nao podem
    # segurar o lock nem derrubar a confirmacao ja gravada.
    try:
        credit_and_auto_payout(order)
    except Exception:
        logger.exception("Falha no repasse do pedido %s — pedido segue pago, repasse manual.", order.id)

    try:
        increment_sales_count(order.store)
        for item in order.items.all():
            Product.objects.filter(pk=item.product_id).update(sold_count=F("sold_count") + item.quantity)
    except Exception:
        logger.exception("Falha ao atualizar contadores de venda do pedido %s", order.id)

    _enqueue_shipping_label(order)
    _dispatch_paid_notifications(order)
    return True


def _enqueue_shipping_label(order: Order) -> None:
    """Compra a etiqueta Melhor Envio quando a plataforma fica com o frete."""
    from apps.shipping.services import platform_buys_shipping_label

    if not order.requires_shipping or not platform_buys_shipping_label():
        return
    try:
        from apps.shipping.tasks import buy_label_for_order

        buy_label_for_order.delay(str(order.id))
    except Exception:
        logger.exception("Falha ao enfileirar etiqueta do pedido %s", order.id)


def _dispatch_paid_notifications(order: Order) -> None:
    from .tasks import emit_invoice_for_order, send_order_confirmation_email, send_seller_new_sale_email

    for task in (send_order_confirmation_email, send_seller_new_sale_email, emit_invoice_for_order):
        try:
            task.delay(str(order.id))
        except Exception:
            logger.exception("Falha ao enfileirar %s do pedido %s", task.name, order.id)


def mark_refunded(payment: Payment, *, reason: str = "estorno") -> None:
    """
    Registra o estorno no nosso lado (o dinheiro já voltou no PSP).
    Devolve o estoque e desfaz o crédito da vendedora.
    """
    from apps.wallet.services import reverse_sale_credit

    with transaction.atomic():
        locked = Payment.objects.select_for_update().select_related("order").get(pk=payment.pk)
        if locked.status == Payment.Status.REFUNDED:
            return
        locked.status = Payment.Status.REFUNDED
        locked.save(update_fields=["status"])
        order = locked.order
        order.status = Order.Status.REFUNDED
        order.canceled_reason = reason[:80]
        order.save(update_fields=["status", "canceled_reason"])

    reverse_sale_credit(order)
    restore_stock(order)


def refund_order(order: Order, *, reason: str = "disputa") -> bool:
    """
    Reembolsa de verdade: pede o estorno ao PSP e só então desfaz tudo
    do nosso lado. É o desfecho de uma contestação aceita.

    Retorna False se não havia cobrança para estornar.
    """
    payment = getattr(order, "payment", None)
    if payment is None or not payment.provider_charge_id:
        logger.warning("Pedido %s sem cobrança — nada a estornar.", order.id)
        return False
    if payment.status == Payment.Status.REFUNDED:
        return True

    provider = services.get_payment_provider()
    provider.refund_charge(provider_charge_id=payment.provider_charge_id)
    mark_refunded(payment, reason=reason)
    logger.info("Pedido %s estornado (%s).", order.id, reason)
    return True


# --------------------------------------------------------------------------
# 4. Cancelamento / expiracao
# --------------------------------------------------------------------------

@transaction.atomic
def restore_stock(order: Order) -> bool:
    """Devolve o estoque do pedido para a vitrine — no maximo uma vez."""
    locked = Order.objects.select_for_update().get(pk=order.pk)
    if locked.stock_restored:
        return False
    for item in locked.items.select_related("product"):
        Product.objects.filter(pk=item.product_id).update(stock=F("stock") + item.quantity)
        Product.objects.filter(pk=item.product_id, status=Product.Status.SOLD, stock__gt=0).update(
            status=Product.Status.PUBLISHED
        )
    locked.stock_restored = True
    locked.save(update_fields=["stock_restored"])
    order.stock_restored = True
    return True


def cancel_order(order: Order, *, reason: str = "cancelado") -> None:
    order.status = Order.Status.CANCELED
    order.canceled_reason = reason[:80]
    order.expires_at = None
    order.save(update_fields=["status", "canceled_reason", "expires_at"])
    restore_stock(order)


def expire_order(order: Order) -> None:
    order.status = Order.Status.EXPIRED
    order.canceled_reason = "pix_nao_pago"
    order.expires_at = None
    order.save(update_fields=["status", "canceled_reason", "expires_at"])
    restore_stock(order)


def expire_stale_orders(*, now=None) -> int:
    """
    Devolve para a vitrine o estoque de pedidos cujo Pix nunca foi pago.

    Antes de expirar, confere no PSP se o pagamento nao entrou (webhook
    perdido) — melhor consultar do que cancelar uma venda de verdade.
    """
    now = now or timezone.now()
    stale = (
        Order.objects.filter(status=Order.Status.AWAITING_PAYMENT, expires_at__lt=now)
        .select_related("payment", "store")
        .prefetch_related("items")
    )
    expired = 0
    for order in stale:
        payment = getattr(order, "payment", None)
        if payment and payment.provider_charge_id:
            try:
                if sync_payment_status(payment):
                    continue
            except AsaasError:
                logger.warning("Nao foi possivel conferir a cobranca do pedido %s antes de expirar.", order.id)
                continue
        expire_order(order)
        expired += 1
    return expired


# --------------------------------------------------------------------------
# 5. Reconciliacao / polling
# --------------------------------------------------------------------------

def reconcile_pending_payments(*, max_age_hours: int = 48) -> int:
    """
    Rede de seguranca: confere no PSP todo pedido ainda aguardando
    pagamento. Cobre webhook perdido e comprador que pagou com a aba ja
    fechada. Retorna quantos pedidos foram confirmados agora.
    """
    cutoff = timezone.now() - timedelta(hours=max_age_hours)
    pending = Payment.objects.select_related("order", "order__store").filter(
        status=Payment.Status.PENDING,
        order__status=Order.Status.AWAITING_PAYMENT,
        created_at__gte=cutoff,
    )
    confirmed = 0
    for payment in pending:
        try:
            if sync_payment_status(payment):
                confirmed += 1
        except AsaasError as exc:
            logger.warning("Reconciliacao do pedido %s: %s", payment.order_id, exc.user_message)
    return confirmed


def sync_payment_status(payment: Payment) -> bool:
    """
    Consulta o PSP e confirma o pedido se o dinheiro entrou.

    E o que faz o checkout funcionar mesmo sem webhook configurado: a
    pagina de pagamento chama isso a cada poucos segundos.
    Retorna True se o pedido esta pago.
    """
    if payment.status == Payment.Status.CONFIRMED:
        return True
    if payment.status == Payment.Status.REFUNDED:
        return False
    if not payment.provider_charge_id:
        return False

    provider = services.get_payment_provider()
    charge = provider.get_charge(payment.provider_charge_id)

    fields = ["provider_status", "last_synced_at"]
    payment.provider_status = charge.status
    payment.last_synced_at = timezone.now()
    if charge.pix_copy_paste and not payment.pix_copy_paste:
        payment.pix_copy_paste = charge.pix_copy_paste
        fields.append("pix_copy_paste")
    if charge.pix_qr_code and not payment.pix_qr_code:
        payment.pix_qr_code = charge.pix_qr_code
        fields.append("pix_qr_code")
    payment.save(update_fields=fields)

    if charge.is_paid:
        confirm_paid_order(payment)
        payment.refresh_from_db()
        return payment.status == Payment.Status.CONFIRMED
    return False
