import hmac
import secrets
from decimal import Decimal

from django.conf import settings
from django.contrib.auth.decorators import login_required
from django.db import transaction
from django.http import HttpResponse, HttpResponseForbidden, JsonResponse
from django.shortcuts import get_object_or_404, render
from django.views.decorators.csrf import csrf_exempt
from rest_framework import status
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.catalog.models import Product
from apps.shipping.models import Shipment
from apps.shipping.services import (
    calculate_freight_options,
    products_are_payment_test,
    test_free_freight_option,
)
from apps.wallet.services import credit_and_auto_payout

from .models import Order, OrderItem, Payment
from .serializers import CheckoutSerializer, OrderSerializer
from .services import _adult_from_birth, _digits, asaas_uses_split, get_payment_provider


@login_required
def my_purchases_page(request):
    """Compras do usuário logado."""
    orders = (
        Order.objects.filter(buyer=request.user)
        .exclude(status=Order.Status.AWAITING_PAYMENT)
        .select_related("store", "shipment", "review")
        .prefetch_related("items__product")
        .order_by("-created_at")[:50]
    )
    return render(request, "payments/my_purchases.html", {"orders": orders})


def guest_order_page(request, token):
    """Acompanhar pedido guest pelo link do e-mail (sem login)."""
    order = get_object_or_404(
        Order.objects.select_related("store", "shipment", "payment").prefetch_related("items__product"),
        access_token=token,
    )
    return render(request, "payments/guest_order.html", {"order": order})


class CheckoutView(APIView):
    """
    POST /api/checkout/ — compra com ou sem cadastro.

    Split Asaas: vendedora recebe item (payout) + frete; plataforma recebe
    so os 30%. Frete e so cotado — a vendedora posta por conta propria.
    Guest: nome, e-mail, CPF, data de nascimento (+18), endereco, pagamento.
    """

    permission_classes = [AllowAny]
    throttle_scope = "checkout"

    @transaction.atomic
    def post(self, request):
        user = request.user if request.user.is_authenticated else None

        serializer = CheckoutSerializer(data=request.data, context={"request": request})
        serializer.is_valid(raise_exception=True)
        payload = serializer.validated_data

        if user:
            customer_cpf = user.cpf
            customer_name = user.get_full_name() or user.username
            customer_email = user.email
            guest_birth = None
        else:
            customer_cpf = _digits(payload["guest_cpf"])
            customer_name = payload["guest_name"].strip()
            customer_email = payload["guest_email"].strip()
            guest_birth = payload["guest_birth_date"]
            if len(customer_cpf) != 11:
                return Response({"detail": "CPF inválido."}, status=status.HTTP_400_BAD_REQUEST)
            if not _adult_from_birth(guest_birth):
                return Response(
                    {"detail": "Compras apenas para maiores de 18 anos."},
                    status=status.HTTP_403_FORBIDDEN,
                )

        products = {
            p.id: p
            for p in Product.objects.select_for_update().filter(
                id__in=[i["product_id"] for i in payload["items"]]
            )
        }
        store = next(iter(products.values())).store
        if not (getattr(settings, "ASAAS_API_KEY", "") or "").strip():
            return Response(
                {
                    "detail": (
                        "Pagamento Asaas não configurado. "
                        "Defina ASAAS_API_KEY no ambiente do servidor."
                    )
                },
                status=status.HTTP_503_SERVICE_UNAVAILABLE,
            )
        if not store.pix_key:
            return Response(
                {"detail": "Esta loja ainda não cadastrou chave Pix para receber."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        if asaas_uses_split() and not store.psp_subaccount_id:
            return Response(
                {"detail": "Esta loja ainda não está apta a receber pagamentos (subconta Asaas)."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        items_total = Decimal("0.00")
        order_items_data = []
        for item in payload["items"]:
            product = products[item["product_id"]]
            quantity = item["quantity"]
            items_total += product.price * quantity
            order_items_data.append((product, quantity))

        total_weight = sum(p.weight_grams * q for p, q in order_items_data)
        product_list = [p for p, _ in order_items_data]
        if getattr(settings, "CHECKOUT_FREE_SHIPPING", True) or products_are_payment_test(product_list):
            freight_options = [test_free_freight_option()]
        else:
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
            # Fallback: se o front mandou pac e o frete gratis esta ativo.
            if freight_options:
                chosen = freight_options[0]
            else:
                return Response(
                    {"detail": "Opção de frete indisponível."},
                    status=status.HTTP_400_BAD_REQUEST,
                )
        shipping_total = Decimal(str(chosen.price))

        access_token = secrets.token_urlsafe(32)
        order = Order.objects.create(
            buyer=user,
            guest_name="" if user else customer_name,
            guest_email="" if user else customer_email,
            guest_cpf="" if user else customer_cpf,
            guest_birth_date=guest_birth,
            access_token=access_token,
            store=store,
            items_total=items_total,
            shipping_total=shipping_total,
            packaging_fee=Decimal("0.00"),
            shipping_address=payload["shipping_address"],
        )
        for product, quantity in order_items_data:
            OrderItem.objects.create(
                order=order,
                product=product,
                unit_price=product.price,
                unit_payout_amount=product.payout_amount,
                quantity=quantity,
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
        try:
            charge = provider.create_split_charge(
                order_id=str(order.id),
                method=payload["payment_method"],
                total_amount=order.grand_total,
                seller_subaccount_id=store.psp_subaccount_id,
                seller_amount=order.seller_amount,
                platform_amount=order.platform_amount,
                customer_cpf=customer_cpf,
                customer_name=customer_name,
                customer_email=customer_email,
            )
        except Exception as exc:
            import logging

            logging.getLogger(__name__).exception("Falha ao criar cobrança Asaas do pedido %s", order.id)
            order.status = Order.Status.CANCELED
            order.save(update_fields=["status"])
            # Devolve estoque
            for product, quantity in order_items_data:
                product.stock += quantity
                if product.status == Product.Status.SOLD and product.stock > 0:
                    product.status = Product.Status.PUBLISHED
                product.save(update_fields=["stock", "status"])
            detail = "Não foi possível gerar a cobrança no Asaas. Tente de novo em instantes."
            resp = getattr(exc, "response", None)
            if resp is not None:
                try:
                    err = resp.json()
                    errors = err.get("errors") or []
                    if errors and isinstance(errors, list):
                        detail = errors[0].get("description") or detail
                except Exception:
                    pass
            return Response({"detail": detail}, status=status.HTTP_502_BAD_GATEWAY)

        Payment.objects.create(
            order=order,
            provider_charge_id=charge.provider_charge_id,
            method=payload["payment_method"],
        )

        if payload.get("marketing_opt_in"):
            from apps.core.models import MarketingSubscriber

            MarketingSubscriber.subscribe(
                email=customer_email,
                name=customer_name,
                source="checkout",
            )

        return Response(
            {
                "order": OrderSerializer(order).data,
                "payment_url": charge.payment_url,
                "pix_qr_code": charge.pix_qr_code,
                "pix_copy_paste": getattr(charge, "pix_copy_paste", None),
                "provider": "asaas",
                "access_token": access_token,
                "track_url": f"/pedido/{access_token}/",
            },
            status=status.HTTP_201_CREATED,
        )


@csrf_exempt
def asaas_webhook(request):
    """
    Webhook Asaas. No PAYMENT_CONFIRMED: marca pago, split ja feito pelo
    Asaas, e dispara Pix automatico pra chave da vendedora.
    """
    if request.method == "GET":
        # Navegador abre com GET — nao e erro. Asaas so usa POST.
        return JsonResponse(
            {
                "ok": True,
                "service": "asaas-webhook",
                "hint": "Endpoint ativo. O Asaas deve enviar POST com o header Asaas-Access-Token.",
            }
        )
    if request.method != "POST":
        return HttpResponse(status=405)

    token = request.headers.get("Asaas-Access-Token", "")
    expected = getattr(settings, "ASAAS_WEBHOOK_TOKEN", "") or ""
    if not expected or not hmac.compare_digest(token, expected):
        return HttpResponseForbidden("Token inválido.")

    import json

    payload = json.loads(request.body)
    event = payload.get("event")
    charge_data = payload.get("payment", {})
    provider_charge_id = charge_data.get("id")

    try:
        payment = Payment.objects.select_related("order", "order__store").get(
            provider_charge_id=provider_charge_id
        )
    except Payment.DoesNotExist:
        from apps.subscriptions.services import activate_subscription

        if event == "PAYMENT_CONFIRMED" and activate_subscription(provider_charge_id):
            return JsonResponse({"received": True})
        return JsonResponse({"detail": "payment not found"}, status=404)

    payment.raw_webhook_payload = payload

    if event == "PAYMENT_CONFIRMED":
        from django.utils import timezone

        from .services import verify_payer_cpf
        from .tasks import (
            emit_invoice_for_order,
            send_order_confirmation_email,
            send_seller_new_sale_email,
        )

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

        # Credita ledger e, se AUTO_PAYOUT_ON_PAYMENT, Pix imediato pra vendedora.
        try:
            credit_and_auto_payout(order)
        except Exception:
            import logging

            logging.getLogger(__name__).exception(
                "Falha no repasse Pix do pedido %s — pedido permanece pago.", order.id
            )

        from apps.stores.services import increment_sales_count

        increment_sales_count(order.store)
        # E-mail/NF nunca podem derrubar o webhook apos o pedido ja estar PAID.
        try:
            send_order_confirmation_email.delay(str(order.id))
            send_seller_new_sale_email.delay(str(order.id))
            emit_invoice_for_order.delay(str(order.id))
        except Exception:
            import logging

            logging.getLogger(__name__).exception(
                "Falha ao enfileirar e-mails/NF do pedido %s", order.id
            )
        # Vendedora posta sozinha — nao compramos etiqueta pela plataforma.

    elif event in ("PAYMENT_REFUNDED", "PAYMENT_CHARGEBACK_REQUESTED"):
        payment.status = Payment.Status.REFUNDED
        payment.save()
        payment.order.status = Order.Status.REFUNDED
        payment.order.save(update_fields=["status"])
    else:
        payment.save(update_fields=["raw_webhook_payload"])

    return JsonResponse({"received": True})
