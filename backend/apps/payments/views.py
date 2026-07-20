import hmac
from decimal import Decimal

from django.conf import settings
from django.contrib.auth.decorators import login_required
from django.db import transaction
from django.http import HttpResponse, HttpResponseForbidden, JsonResponse
from django.shortcuts import render
from django.views.decorators.csrf import csrf_exempt
from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.catalog.models import Product
from apps.shipping.models import Shipment
from apps.shipping.services import calculate_freight_options
from apps.wallet.services import credit_sale

from .models import Order, OrderItem, Payment
from .serializers import CheckoutSerializer, OrderSerializer
from .services import get_payment_provider


@login_required
def my_purchases_page(request):
    """Compras do usuário, com etapa do envio e confirmação de recebimento."""
    orders = (
        Order.objects.filter(buyer=request.user)
        .exclude(status=Order.Status.AWAITING_PAYMENT)
        .select_related("store", "shipment", "review")
        .prefetch_related("items__product")
        .order_by("-created_at")[:50]
    )
    return render(request, "payments/my_purchases.html", {"orders": orders})


class CheckoutView(APIView):
    """
    POST /api/checkout/ — cria o pedido, a cobranca com split (o PSP
    ja separa X% pra vendedora, resto pra plataforma) e o registro de
    envio. Navegar e comprar não exigem assinatura - só é cobrado o
    valor do pedido em si, no ato (docs/checkout.md - novo modelo de
    negócio: sem taxa recorrente, comissão só na venda).
    """

    permission_classes = [IsAuthenticated]
    throttle_scope = "checkout"

    @transaction.atomic
    def post(self, request):
        buyer = request.user

        if not buyer.is_phone_verified:
            return Response(
                {"detail": "Confirme seu celular (vinculado ao seu CPF) antes de comprar.",
                 "action": "verify_phone"},
                status=status.HTTP_403_FORBIDDEN,
            )

        serializer = CheckoutSerializer(data=request.data, context={"request": request})
        serializer.is_valid(raise_exception=True)
        payload = serializer.validated_data

        products = {p.id: p for p in Product.objects.select_for_update().filter(
            id__in=[i["product_id"] for i in payload["items"]]
        )}
        store = next(iter(products.values())).store

        items_total = Decimal("0.00")
        order_items_data = []
        for item in payload["items"]:
            product = products[item["product_id"]]
            quantity = item["quantity"]
            items_total += product.price * quantity
            order_items_data.append((product, quantity))

        total_weight = sum(p.weight_grams * q for p, q in order_items_data)
        freight_options = calculate_freight_options(
            destination_cep=payload["shipping_address"]["cep"],
            weight_grams=total_weight,
            length_cm=max(p.length_cm for p, _ in order_items_data),
            width_cm=max(p.width_cm for p, _ in order_items_data),
            height_cm=sum(p.height_cm * q for p, q in order_items_data),
            origin_cep=store.origin_cep,
            declared_value=items_total,
        )
        try:
            chosen = next(o for o in freight_options if o.service == payload["shipping_service"])
        except StopIteration:
            return Response(
                {"detail": "Opção de frete indisponível — recalcule o frete e tente de novo."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        # Embalagem padronizada comprada pela plataforma - custo embutido no
        # frete cobrado do comprador (docs/checkout.md).
        shipping_total = Decimal(str(chosen.price)) + settings.PACKAGING_FEE

        order = Order.objects.create(
            buyer=buyer,
            store=store,
            items_total=items_total,
            shipping_total=shipping_total,
            packaging_fee=settings.PACKAGING_FEE,
            shipping_address=payload["shipping_address"],
        )
        for product, quantity in order_items_data:
            OrderItem.objects.create(
                order=order, product=product, unit_price=product.price,
                unit_payout_amount=product.payout_amount, quantity=quantity,
            )
            product.stock -= quantity
            if product.stock == 0:
                product.status = Product.Status.SOLD
            product.save(update_fields=["stock", "status"])

        Shipment.objects.create(
            order=order,
            service=chosen.service,
            estimated_delivery_days=chosen.deadline_days,
        )

        provider = get_payment_provider()
        charge = provider.create_split_charge(
            order_id=str(order.id),
            method=payload["payment_method"],
            total_amount=order.grand_total,
            seller_subaccount_id=store.psp_subaccount_id,
            seller_amount=order.seller_amount,
            platform_amount=order.platform_amount,
            # Cobranca amarrada ao CPF do titular da conta - identidade civil,
            # nunca o apelido (ver apps.payments.services).
            customer_cpf=buyer.cpf,
            customer_name=buyer.get_full_name() or buyer.username,
            customer_email=buyer.email,
        )
        Payment.objects.create(
            order=order,
            provider_charge_id=charge.provider_charge_id,
            method=payload["payment_method"],
        )

        return Response(
            {
                "order": OrderSerializer(order).data,
                "payment_url": charge.payment_url,
                "pix_qr_code": charge.pix_qr_code,
            },
            status=status.HTTP_201_CREATED,
        )


@csrf_exempt
def asaas_webhook(request):
    """
    Webhook de confirmacao de pagamento do Asaas. Autenticado por
    token compartilhado no header (nunca confiar so no payload).
    Docs: https://docs.asaas.com/docs/webhook
    """
    if request.method != "POST":
        return HttpResponse(status=405)

    token = request.headers.get("Asaas-Access-Token", "")
    if not hmac.compare_digest(token, settings.ASAAS_WEBHOOK_TOKEN):
        return HttpResponseForbidden("Token inválido.")

    import json

    payload = json.loads(request.body)
    event = payload.get("event")
    charge_data = payload.get("payment", {})
    provider_charge_id = charge_data.get("id")

    try:
        payment = Payment.objects.select_related("order").get(provider_charge_id=provider_charge_id)
    except Payment.DoesNotExist:
        # Nao e o pagamento de um pedido - pode ser a cobranca (sem split)
        # de uma assinatura de compradora (ver apps.subscriptions.services).
        from apps.subscriptions.services import activate_subscription

        if event == "PAYMENT_CONFIRMED" and activate_subscription(provider_charge_id):
            return JsonResponse({"received": True})
        return JsonResponse({"detail": "payment not found"}, status=404)

    payment.raw_webhook_payload = payload

    if event == "PAYMENT_CONFIRMED":
        from django.utils import timezone

        from .services import verify_payer_cpf
        from .tasks import emit_invoice_for_order, send_order_confirmation_email

        # Trava "pagamento so pelo CPF do titular": se o Pix veio de conta
        # de terceiro, verify_payer_cpf ja disparou o estorno no PSP.
        if not verify_payer_cpf(payment, payload):
            payment.status = Payment.Status.REFUNDED
            payment.save()
            payment.order.status = Order.Status.CANCELED
            payment.order.save(update_fields=["status"])
            return JsonResponse({"received": True, "action": "refunded_payer_mismatch"})

        payment.status = Payment.Status.CONFIRMED
        payment.split_confirmed = True
        payment.confirmed_at = timezone.now()
        payment.save()

        order = payment.order
        order.status = Order.Status.PAID
        order.paid_at = timezone.now()
        order.save(update_fields=["status", "paid_at"])

        credit_sale(order)
        from apps.stores.services import increment_sales_count

        increment_sales_count(order.store)
        send_order_confirmation_email.delay(str(order.id))
        emit_invoice_for_order.delay(str(order.id))
        # Compra automatica da etiqueta (Melhor Envio) com o frete que o
        # comprador ja pagou - a vendedora recebe o PDF por e-mail.
        from apps.shipping.tasks import buy_label_for_order

        buy_label_for_order.delay(str(order.id))

    elif event in ("PAYMENT_REFUNDED", "PAYMENT_CHARGEBACK_REQUESTED"):
        payment.status = Payment.Status.REFUNDED
        payment.save()
        payment.order.status = Order.Status.REFUNDED
        payment.order.save(update_fields=["status"])
    else:
        payment.save(update_fields=["raw_webhook_payload"])

    return JsonResponse({"received": True})
