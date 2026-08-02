"""
Regras de negocio dos pedidos personalizados. A criacao do Product
privado na aceitacao e o que permite reusar TODO o pipeline existente
(checkout com frete, split por CPF do titular, carteira, rastreio) sem
caminho paralelo de pagamento.
"""
from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone
from django.utils.text import slugify

from apps.catalog.models import Category, Product, payout_from_price
from apps.moderation.services import run_automated_filters

from .models import CustomOrderRequest

CUSTOM_CATEGORY_NAME = "Pedidos personalizados"
# Item fisico pequeno por padrao (roupa intima): a vendedora pode ajustar
# depois no admin se o combinado for maior/mais pesado.
DEFAULT_WEIGHT_GRAMS = 80


def create_custom_request(*, buyer, store, title: str, description: str, offered_price) -> CustomOrderRequest:
    flags = run_automated_filters(title=title, description=description)
    if flags:
        # Fail closed: pedido que menciona servico sexual ou tenta vazar
        # contato nem chega a ser criado (linha vermelha, secao 3).
        raise ValidationError(
            "Pedidos personalizados são apenas para itens físicos e a conversa deve ficar na plataforma. "
            "Remova menções a serviços, encontros ou contatos externos."
        )
    return CustomOrderRequest.objects.create(
        buyer=buyer, store=store, title=title, description=description, offered_price=offered_price
    )


@transaction.atomic
def accept_request(request_obj: CustomOrderRequest, *, price=None) -> CustomOrderRequest:
    """Aceite (da vendedora sobre a oferta, ou do comprador sobre a contra-proposta)."""
    category, _ = Category.objects.get_or_create(
        name=CUSTOM_CATEGORY_NAME, defaults={"slug": slugify(CUSTOM_CATEGORY_NAME)}
    )
    # O valor negociado (oferta/contra-proposta) e o TOTAL que o comprador
    # paga - igual a exibicao na UI de negociacao. Convertemos pro liquido
    # da vendedora aqui pra manter a mesma regra de comissao dos anuncios
    # normais (Product.save() vai recalcular price a partir disso).
    final_price = price if price is not None else request_obj.final_price
    payout = payout_from_price(final_price)

    base_slug = slugify(request_obj.title)[:80] or "pedido-personalizado"
    slug = f"{base_slug}-{str(request_obj.id)[:8]}"

    product = Product.objects.create(
        store=request_obj.store,
        category=category,
        title=request_obj.title[:120],
        slug=slug,
        description=request_obj.description,
        payout_amount=payout,
        weight_grams=DEFAULT_WEIGHT_GRAMS,
        status=Product.Status.PUBLISHED,
        visibility=Product.Visibility.PRIVATE,
        reserved_for=request_obj.buyer,
        stock=1,
    )
    request_obj.product = product
    request_obj.status = CustomOrderRequest.Status.ACCEPTED
    request_obj.responded_at = timezone.now()
    request_obj.save(update_fields=["product", "status", "responded_at"])
    return request_obj


def counter_request(request_obj: CustomOrderRequest, *, counter_price, counter_message: str = "") -> CustomOrderRequest:
    if counter_message:
        flags = run_automated_filters(title="", description=counter_message)
        if flags:
            raise ValidationError("A contra-proposta deve falar só do item físico, sem contatos externos.")
    request_obj.counter_price = counter_price
    request_obj.counter_message = counter_message
    request_obj.status = CustomOrderRequest.Status.COUNTERED
    request_obj.responded_at = timezone.now()
    request_obj.save(update_fields=["counter_price", "counter_message", "status", "responded_at"])
    return request_obj
