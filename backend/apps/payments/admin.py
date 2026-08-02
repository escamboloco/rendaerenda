import logging

from django.contrib import admin, messages

from .models import Invoice, Order, OrderItem, Payment

logger = logging.getLogger(__name__)


class OrderItemInline(admin.TabularInline):
    model = OrderItem
    extra = 0
    readonly_fields = ("addons", "addons_price", "addons_payout")


@admin.register(Order)
class OrderAdmin(admin.ModelAdmin):
    list_display = (
        "short_id", "buyer", "store", "status", "items_total", "shipping_total",
        "payout_sent_at", "created_at",
    )
    list_filter = ("status", "payout_sent_at")
    search_fields = ("id", "guest_email", "guest_cpf", "store__display_name")
    readonly_fields = ("access_token", "stock_restored", "payout_sent_at", "created_at", "paid_at")
    inlines = [OrderItemInline]
    actions = ["refund_to_buyer", "release_to_seller"]

    @admin.action(description="Disputa procedente: estornar para o comprador")
    def refund_to_buyer(self, request, queryset):
        """Fecha a disputa a favor de quem comprou: estorna no PSP e desfaz o crédito."""
        from .checkout import refund_order

        if not request.user.is_superuser:
            self.message_user(
                request, "Ação financeira restrita ao superusuário.", messages.ERROR
            )
            return
        done, failed = 0, 0
        for order in queryset.select_related("payment", "store"):
            try:
                if refund_order(order, reason="disputa_procedente"):
                    done += 1
                else:
                    failed += 1
            except Exception:
                logger.exception("Falha ao estornar o pedido %s pelo admin", order.id)
                failed += 1
        if done:
            self.message_user(request, f"{done} pedido(s) estornado(s).", messages.SUCCESS)
        if failed:
            self.message_user(
                request,
                f"{failed} pedido(s) não puderam ser estornados — confira o log e o painel do Asaas.",
                messages.ERROR,
            )

    @admin.action(description="Disputa improcedente: liberar o valor para a vendedora")
    def release_to_seller(self, request, queryset):
        """Fecha a disputa a favor da vendedora: tira da custódia e paga."""
        from apps.wallet.services import release_and_payout

        if not request.user.is_superuser:
            self.message_user(
                request, "Ação financeira restrita ao superusuário.", messages.ERROR
            )
            return
        done = 0
        for order in queryset.select_related("store"):
            if order.status == Order.Status.DISPUTED and release_and_payout(order):
                order.status = Order.Status.DELIVERED
                order.save(update_fields=["status"])
                done += 1
        self.message_user(request, f"{done} pedido(s) liberado(s) e repassado(s).", messages.SUCCESS)


@admin.register(Payment)
class PaymentAdmin(admin.ModelAdmin):
    list_display = (
        "order", "method", "status", "provider_status", "payer_cpf_matched", "confirmed_at",
    )
    list_filter = ("method", "status", "payer_cpf_matched")
    search_fields = ("provider_charge_id", "order__id")
    readonly_fields = ("pix_qr_code", "pix_copy_paste", "raw_webhook_payload", "last_synced_at")


@admin.register(Invoice)
class InvoiceAdmin(admin.ModelAdmin):
    list_display = ("id", "kind", "recipient_cpf", "amount", "status", "issued_at")
    list_filter = ("kind", "status")
    search_fields = ("recipient_cpf", "provider_invoice_id")
