import hmac
import json
import logging
from decimal import Decimal

from django.conf import settings
from django.contrib.auth.decorators import login_required
from django.http import HttpResponse, HttpResponseForbidden, JsonResponse
from django.shortcuts import get_object_or_404, render
from django.utils import timezone
from django.views.decorators.csrf import csrf_exempt
from rest_framework import status
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.views import APIView

from .asaas import AsaasError
from .checkout import (
    CartLine,
    CheckoutError,
    confirm_paid_order,
    create_charge_for_order,
    mark_refunded,
    quote_shipping,
    reserve_order,
    sync_payment_status,
)
from .models import Order, OrderMessage, Payment
from .serializers import CheckoutSerializer, OrderSerializer
from .services import _digits, is_adult

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------- paginas


@login_required
def my_purchases_page(request):
    """Compras do usuário logado."""
    orders = (
        Order.objects.filter(buyer=request.user)
        .exclude(status__in=[Order.Status.EXPIRED, Order.Status.CANCELED])
        .select_related("store", "shipment", "review", "payment")
        .prefetch_related("items__product__images")
        .order_by("-created_at")[:50]
    )
    return render(request, "payments/my_purchases.html", {"orders": orders})


def order_page(request, token):
    """
    Acompanhamento do pedido pelo link (sem login). E também a tela de
    pagamento: se o Pix ainda não foi pago, o QR aparece aqui e a página
    consulta o status sozinha até confirmar.
    """
    order = get_object_or_404(
        Order.objects.select_related("store", "shipment", "payment").prefetch_related(
            "items__product__images", "items__product__assets"
        ),
        access_token=token,
    )
    paid = order.status in (Order.Status.PAID, Order.Status.SHIPPED, Order.Status.DELIVERED)
    # Conteúdo digital só aparece com o pedido pago.
    digital_assets = []
    if paid:
        for item in order.items.all():
            for asset in item.product.assets.all():
                digital_assets.append({"product": item.product, "asset": asset})

    shipment = getattr(order, "shipment", None)
    can_confirm = paid and order.status != Order.Status.DISPUTED and not (
        shipment and (shipment.buyer_confirmed_at or shipment.buyer_disputed_at)
    )
    return render(
        request,
        "payments/order_detail.html",
        {
            "order": order,
            "payment": getattr(order, "payment", None),
            "digital_assets": digital_assets,
            "can_confirm": can_confirm,
            "dispute_window_days": settings.DISPUTE_WINDOW_DAYS,
        },
    )


# Nome antigo mantido para não quebrar imports/urls existentes.
guest_order_page = order_page


def checkout_page(request):
    """
    Página única do funil: sacola -> dados -> entrega -> Pix.

    Não recebe nada por querystring: a sacola vive no navegador e os
    preços são sempre recalculados pelo servidor (CartSummaryView).
    """
    return render(
        request,
        "payments/checkout.html",
        {
            "free_shipping": getattr(settings, "CHECKOUT_FREE_SHIPPING", False),
            "statement_descriptor": getattr(settings, "STATEMENT_DESCRIPTOR", ""),
        },
    )


class CartSummaryView(APIView):
    """
    POST /api/sacola/ — devolve os itens da sacola com preço, foto e
    disponibilidade conferidos no servidor.

    A sacola do navegador guarda só id + quantidade; preço, título e
    estoque nunca vêm do cliente.
    """

    permission_classes = [AllowAny]
    throttle_scope = "cart"

    def post(self, request):
        raw_items = request.data.get("items") or []
        if not isinstance(raw_items, list):
            return Response({"detail": "Sacola inválida."}, status=status.HTTP_400_BAD_REQUEST)

        wanted: dict[str, int] = {}
        addon_choice: dict[str, set] = {}
        for item in raw_items[:50]:
            if not isinstance(item, dict):
                continue
            product_id = str(item.get("id") or item.get("product_id") or "").strip()
            if not product_id:
                continue
            try:
                quantity = max(1, min(int(item.get("qty") or item.get("quantity") or 1), 20))
            except (TypeError, ValueError):
                quantity = 1
            wanted[product_id] = wanted.get(product_id, 0) + quantity
            raw_addons = item.get("addons") or []
            if isinstance(raw_addons, list):
                addon_choice.setdefault(product_id, set()).update(
                    str(a) for a in raw_addons[:10] if a
                )

        from apps.catalog.models import Product

        products = (
            Product.objects.select_related("store")
            .prefetch_related("images", "addons")
            .filter(id__in=list(wanted))
        )
        # Filtro no Python porque is_available() depende do estado da loja.
        items, unavailable = [], []
        items_total = Decimal("0.00")
        store = None
        needs_shipping = False
        for product in products:
            quantity = min(wanted[str(product.id)], product.stock)
            if not product.is_available() or quantity < 1:
                unavailable.append({"id": str(product.id), "title": product.title})
                continue
            store = store or product.store
            if product.store_id != store.id:
                unavailable.append({"id": str(product.id), "title": product.title, "other_store": True})
                continue

            picked = addon_choice.get(str(product.id), set())
            addons = [a for a in product.addons.all() if a.is_active and str(a.id) in picked]
            addons_total = sum((a.price for a in addons), Decimal("0.00"))
            line_total = product.price * quantity + addons_total
            cover = product.images.first()
            needs_shipping = needs_shipping or product.requires_shipping
            items.append(
                {
                    "id": str(product.id),
                    "title": product.title,
                    "price": str(product.price),
                    "qty": quantity,
                    "kind": product.kind,
                    "requires_shipping": product.requires_shipping,
                    "addons": [
                        {"id": str(a.id), "title": a.title, "price": str(a.price)} for a in addons
                    ],
                    "addons_total": str(addons_total),
                    "line_total": str(line_total),
                    "stock": product.stock,
                    "image": cover.file.url if cover else "",
                    "url": f"/loja/{product.store.slug}/item/{product.slug}/",
                }
            )
            items_total += line_total

        known = {i["id"] for i in items} | {u["id"] for u in unavailable}
        for product_id in wanted:
            if product_id not in known:
                unavailable.append({"id": product_id, "title": ""})

        return Response(
            {
                "items": items,
                "unavailable": unavailable,
                "items_total": str(items_total),
                "shipping_total": "0.00",
                "grand_total": str(items_total),
                "requires_shipping": needs_shipping,
                "store": (
                    {"slug": store.slug, "name": store.display_name, "url": f"/loja/{store.slug}/"}
                    if store
                    else None
                ),
            }
        )


# -------------------------------------------------------------------- API


class CheckoutView(APIView):
    """
    POST /api/checkout/ — fecha a compra com ou sem cadastro.

    Fluxo: valida -> reserva estoque (transação curta) -> cria a cobrança
    Pix no Asaas (fora da transação) -> devolve QR + link de
    acompanhamento. Qualquer falha na cobrança cancela o pedido e devolve
    o estoque, sem cobrar nada de ninguém.
    """

    permission_classes = [AllowAny]
    throttle_scope = "checkout"

    def post(self, request):
        user = request.user if request.user.is_authenticated else None

        serializer = CheckoutSerializer(data=request.data, context={"request": request})
        serializer.is_valid(raise_exception=True)
        payload = serializer.validated_data

        guest_birth = None
        if user:
            if not user.cpf:
                return Response(
                    {"detail": "Complete seu cadastro com CPF antes de comprar."},
                    status=status.HTTP_400_BAD_REQUEST,
                )
        else:
            guest_birth = payload["guest_birth_date"]
            if not is_adult(guest_birth):
                return Response(
                    {"detail": "Compras apenas para maiores de 18 anos."},
                    status=status.HTTP_403_FORBIDDEN,
                )

        lines = [
            CartLine(
                product_id=str(item["product_id"]),
                quantity=item["quantity"],
                addon_ids=tuple(str(a) for a in item.get("addon_ids") or ()),
            )
            for item in payload["items"]
        ]

        address = payload["shipping_address"]
        try:
            # Cotacao antes da reserva: pode fazer chamada externa e nao
            # pode acontecer com o estoque travado.
            freight = quote_shipping(
                lines=lines,
                destination_cep=address.get("cep", ""),
                preferred_service=payload.get("shipping_service") or "pac",
            )
            order = reserve_order(
                lines=lines,
                buyer=user,
                guest_name=(payload.get("guest_name") or "").strip(),
                guest_email=(payload.get("guest_email") or "").strip(),
                guest_cpf=_digits(payload.get("guest_cpf")),
                guest_birth_date=guest_birth,
                shipping_address=address,
                shipping_service=freight.service,
                shipping_total=Decimal(str(freight.price)),
                shipping_deadline_days=freight.deadline_days,
            )
        except CheckoutError as exc:
            return Response({"detail": exc.detail}, status=exc.status_code)

        try:
            payment = create_charge_for_order(order, method=payload["payment_method"])
        except CheckoutError as exc:
            return Response({"detail": exc.detail}, status=exc.status_code)

        if payload.get("marketing_opt_in"):
            from apps.core.models import MarketingSubscriber

            MarketingSubscriber.subscribe(
                email=order.payer_email, name=order.payer_name, source="checkout"
            )

        return Response(
            {
                "order": OrderSerializer(order).data,
                "payment_url": payment.payment_url or None,
                "pix_qr_code": payment.pix_qr_code or None,
                "pix_copy_paste": payment.pix_copy_paste or None,
                "provider": "asaas",
                "access_token": order.access_token,
                "track_url": order.track_url,
                "expires_at": order.expires_at,
            },
            status=status.HTTP_201_CREATED,
        )


class OrderConfirmView(APIView):
    """
    POST /api/pedido/<token>/confirmar/ — o comprador libera (ou trava) o
    dinheiro que está em custódia.

    Autenticado pelo token do pedido: quem comprou sem cadastro também
    precisa poder confirmar, senão a custódia só sairia pelo prazo.
      action=confirm  -> libera o valor e dispara o Pix para a vendedora
      action=dispute  -> trava o valor e manda o caso para a moderação
    """

    permission_classes = [AllowAny]
    throttle_scope = "checkout"

    def post(self, request, token):
        from apps.wallet.services import release_and_payout

        order = get_object_or_404(
            Order.objects.select_related("shipment", "store"), access_token=token
        )
        if order.status not in (Order.Status.PAID, Order.Status.SHIPPED, Order.Status.DELIVERED):
            return Response(
                {"detail": "Este pedido ainda não está pago."}, status=status.HTTP_409_CONFLICT
            )
        if order.status == Order.Status.DISPUTED:
            return Response({"detail": "Já existe uma contestação aberta."}, status=status.HTTP_409_CONFLICT)

        shipment = getattr(order, "shipment", None)
        if shipment and (shipment.buyer_confirmed_at or shipment.buyer_disputed_at):
            return Response({"detail": "Você já respondeu sobre este pedido."}, status=status.HTTP_409_CONFLICT)

        action = (request.data.get("action") or "").strip()
        now = timezone.now()

        if action == "confirm":
            if shipment:
                shipment.buyer_confirmed_at = now
                shipment.save(update_fields=["buyer_confirmed_at"])
            order.status = Order.Status.DELIVERED
            order.save(update_fields=["status"])
            release_and_payout(order)
            return Response({"status": "confirmed"})

        if action == "dispute":
            from .tasks import send_dispute_opened_email

            if shipment:
                shipment.buyer_disputed_at = now
                shipment.save(update_fields=["buyer_disputed_at"])
            order.status = Order.Status.DISPUTED
            order.save(update_fields=["status"])
            logger.warning("Contestacao aberta no pedido %s", order.id)
            try:
                send_dispute_opened_email.delay(str(order.id))
            except Exception:
                logger.exception("Falha ao avisar da contestacao do pedido %s", order.id)
            return Response({"status": "disputed"})

        return Response(
            {"detail": "Ação inválida (use confirm ou dispute)."}, status=status.HTTP_400_BAD_REQUEST
        )


class OrderMessagesView(APIView):
    """
    GET/POST /api/pedido/<token>/mensagens/ — conversa do pedido.

    Quem é quem: a vendedora é identificada pela conta (dona da loja do
    pedido); qualquer outra pessoa com o token é o comprador. O token do
    pedido é o segredo que dá acesso — é o mesmo que abre a página.
    """

    permission_classes = [AllowAny]
    throttle_scope = "offers"

    def _order_and_role(self, request, token):
        order = get_object_or_404(Order.objects.select_related("store"), access_token=token)
        is_seller = (
            request.user.is_authenticated and order.store.owner_id == request.user.id
        )
        return order, (OrderMessage.Sender.SELLER if is_seller else OrderMessage.Sender.BUYER)

    def get(self, request, token):
        order, role = self._order_and_role(request, token)
        messages = order.messages.all()[:200]
        return Response(
            {
                "role": role,
                "messages": [
                    {
                        "id": str(m.id),
                        "sender": m.sender,
                        "mine": m.sender == role,
                        "body": m.body,
                        "created_at": m.created_at,
                    }
                    for m in messages
                ],
            }
        )

    def post(self, request, token):
        from apps.moderation.services import run_automated_filters

        order, role = self._order_and_role(request, token)
        if order.status in (Order.Status.EXPIRED, Order.Status.CANCELED):
            return Response(
                {"detail": "Este pedido não está mais ativo."}, status=status.HTTP_409_CONFLICT
            )

        body = (request.data.get("body") or "").strip()
        if not 1 <= len(body) <= 1000:
            return Response({"detail": "Escreva uma mensagem."}, status=status.HTTP_400_BAD_REQUEST)
        if run_automated_filters(title="", description=body):
            return Response(
                {
                    "detail": (
                        "A conversa precisa ficar na plataforma. Combinar contato ou "
                        "pagamento por fora não é permitido — e tira a sua proteção."
                    )
                },
                status=status.HTTP_400_BAD_REQUEST,
            )

        message = OrderMessage.objects.create(order=order, sender=role, body=body)
        return Response(
            {
                "id": str(message.id),
                "sender": message.sender,
                "mine": True,
                "body": message.body,
                "created_at": message.created_at,
            },
            status=status.HTTP_201_CREATED,
        )


class OrderStatusView(APIView):
    """
    GET /api/pedido/<token>/status/ — usado pela tela de pagamento.

    Além de ler o banco, consulta o Asaas quando o pedido ainda está
    aguardando: é isso que faz o Pix confirmar sozinho mesmo se o webhook
    não estiver configurado (ou tiver falhado).
    """

    permission_classes = [AllowAny]
    throttle_scope = "order_status"

    def get(self, request, token):
        order = get_object_or_404(
            Order.objects.select_related("payment", "shipment"), access_token=token
        )
        payment = getattr(order, "payment", None)

        if order.status == Order.Status.AWAITING_PAYMENT and payment:
            try:
                sync_payment_status(payment)
            except AsaasError as exc:
                logger.info("Polling do pedido %s: %s", order.id, exc.user_message)
            order.refresh_from_db()

        return Response(
            {
                "status": order.status,
                "status_label": order.get_status_display(),
                "paid": order.status
                not in (Order.Status.AWAITING_PAYMENT, Order.Status.EXPIRED, Order.Status.CANCELED),
                "expired": order.status == Order.Status.EXPIRED,
                "expires_at": order.expires_at,
                "track_url": order.track_url,
            }
        )


# ---------------------------------------------------------------- webhook


# Eventos que significam "o dinheiro entrou".
PAID_EVENTS = {"PAYMENT_RECEIVED", "PAYMENT_CONFIRMED", "PAYMENT_RECEIVED_IN_CASH"}
# Eventos que desfazem a cobranca.
REFUND_EVENTS = {
    "PAYMENT_REFUNDED",
    "PAYMENT_PARTIALLY_REFUNDED",
    "PAYMENT_CHARGEBACK_REQUESTED",
    "PAYMENT_CHARGEBACK_DISPUTE",
    "PAYMENT_REVERSED",
}


@csrf_exempt
def asaas_webhook(request):
    """
    Webhook do Asaas.

    Idempotente por construção: a confirmação do pedido é feita por
    confirm_paid_order(), que trava a linha do pagamento e não repete
    crédito nem repasse. O Asaas reenvia o mesmo evento até receber 200,
    então responder 200 para evento já processado é o comportamento certo.
    """
    if request.method == "GET":
        # Navegador abre com GET — nao e erro. O Asaas so usa POST.
        return JsonResponse(
            {
                "ok": True,
                "service": "asaas-webhook",
                "hint": "Endpoint ativo. O Asaas deve enviar POST com o header asaas-access-token.",
            }
        )
    if request.method != "POST":
        return HttpResponse(status=405)

    expected = (getattr(settings, "ASAAS_WEBHOOK_TOKEN", "") or "").strip()
    if not expected:
        # Sem token configurado o endpoint fica FECHADO: aceitar qualquer
        # POST aqui deixaria qualquer um marcar pedido como pago.
        logger.error("Webhook Asaas chamado sem ASAAS_WEBHOOK_TOKEN configurado no servidor.")
        return JsonResponse({"detail": "webhook nao configurado"}, status=503)

    token = request.headers.get("asaas-access-token") or request.headers.get("Asaas-Access-Token") or ""
    if not hmac.compare_digest(token, expected):
        logger.warning("Webhook Asaas com token invalido.")
        return HttpResponseForbidden("Token inválido.")

    try:
        payload = json.loads(request.body or b"{}")
    except json.JSONDecodeError:
        return JsonResponse({"detail": "payload inválido"}, status=400)

    event = payload.get("event") or ""
    charge_data = payload.get("payment") or {}
    provider_charge_id = charge_data.get("id")
    if not provider_charge_id:
        return JsonResponse({"received": True, "ignored": "sem id de cobranca"})

    payment = (
        Payment.objects.select_related("order", "order__store")
        .filter(provider_charge_id=provider_charge_id)
        .first()
    )
    if payment is None:
        # Pode ser cobranca de assinatura/plano (nao tem Order).
        from apps.subscriptions.services import activate_subscription

        if event in PAID_EVENTS and activate_subscription(provider_charge_id):
            return JsonResponse({"received": True, "kind": "subscription"})
        logger.info("Webhook Asaas para cobranca desconhecida %s (%s)", provider_charge_id, event)
        return JsonResponse({"received": True, "ignored": "cobranca desconhecida"})

    if event in PAID_EVENTS:
        confirmed = confirm_paid_order(payment, webhook_payload=payload)
        return JsonResponse({"received": True, "confirmed_now": confirmed})

    if event in REFUND_EVENTS:
        mark_refunded(payment, reason=event.lower())
        return JsonResponse({"received": True, "action": "refunded"})

    if event in ("PAYMENT_OVERDUE", "PAYMENT_DELETED"):
        payment.provider_status = charge_data.get("status") or event
        payment.raw_webhook_payload = payload
        payment.save(update_fields=["provider_status", "raw_webhook_payload"])
        return JsonResponse({"received": True})

    payment.provider_status = charge_data.get("status") or payment.provider_status
    payment.raw_webhook_payload = payload
    payment.save(update_fields=["provider_status", "raw_webhook_payload"])
    return JsonResponse({"received": True})
