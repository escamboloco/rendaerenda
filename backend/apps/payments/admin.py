from django.contrib import admin

from .models import Invoice, Order, OrderItem, Payment


class OrderItemInline(admin.TabularInline):
    model = OrderItem
    extra = 0


@admin.register(Order)
class OrderAdmin(admin.ModelAdmin):
    list_display = ("id", "buyer", "store", "status", "items_total", "shipping_total", "created_at")
    list_filter = ("status",)
    inlines = [OrderItemInline]


@admin.register(Payment)
class PaymentAdmin(admin.ModelAdmin):
    list_display = ("order", "method", "status", "split_confirmed", "payer_cpf_matched", "confirmed_at")
    list_filter = ("method", "status", "split_confirmed", "payer_cpf_matched")


@admin.register(Invoice)
class InvoiceAdmin(admin.ModelAdmin):
    list_display = ("id", "kind", "recipient_cpf", "amount", "status", "issued_at")
    list_filter = ("kind", "status")
    search_fields = ("recipient_cpf", "provider_invoice_id")
