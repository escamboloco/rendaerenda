from django.contrib import admin

from .models import CustomOrderRequest


@admin.register(CustomOrderRequest)
class CustomOrderRequestAdmin(admin.ModelAdmin):
    list_display = ("title", "store", "buyer", "offered_price", "counter_price", "status", "created_at")
    list_filter = ("status",)
    search_fields = ("title", "store__display_name", "buyer__cpf")
