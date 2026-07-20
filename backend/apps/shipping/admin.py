from django.contrib import admin

from .models import Shipment, ShippingQuote


@admin.register(ShippingQuote)
class ShippingQuoteAdmin(admin.ModelAdmin):
    list_display = ("origin_cep", "destination_cep", "service", "price", "deadline_days", "quoted_at")
    list_filter = ("service",)


@admin.register(Shipment)
class ShipmentAdmin(admin.ModelAdmin):
    list_display = ("order", "service", "tracking_code", "status", "estimated_delivery_days")
    list_filter = ("status", "service")
    search_fields = ("tracking_code",)
