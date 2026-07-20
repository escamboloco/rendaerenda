from django.contrib import admin

from .models import WalletEntry, WithdrawalRequest


@admin.register(WalletEntry)
class WalletEntryAdmin(admin.ModelAdmin):
    list_display = ("store", "kind", "amount", "available_at", "created_at")
    list_filter = ("kind",)
    search_fields = ("store__display_name",)


@admin.register(WithdrawalRequest)
class WithdrawalRequestAdmin(admin.ModelAdmin):
    list_display = ("store", "amount", "status", "requested_at", "paid_at")
    list_filter = ("status",)
