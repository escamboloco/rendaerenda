from django.contrib import admin

from .models import Invoice, Order, OrderItem, Payment


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
