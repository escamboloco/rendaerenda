from django.contrib import admin

from .models import BoostPackage, Store, StoreBoost, StoreFollow, StorePlan


@admin.register(StorePlan)
class StorePlanAdmin(admin.ModelAdmin):
    list_display = ("name", "price", "duration_days", "is_active")


@admin.register(Store)
class StoreAdmin(admin.ModelAdmin):
    list_display = ("display_name", "owner", "status", "plan", "plan_expires_at")
    list_filter = ("status",)
    search_fields = ("display_name", "slug", "owner__username", "owner__cpf")


@admin.register(BoostPackage)
class BoostPackageAdmin(admin.ModelAdmin):
    list_display = ("name", "price", "duration_hours")


@admin.register(StoreBoost)
class StoreBoostAdmin(admin.ModelAdmin):
    list_display = ("store", "package", "starts_at", "ends_at", "paid")
    list_filter = ("paid",)


@admin.register(StoreFollow)
class StoreFollowAdmin(admin.ModelAdmin):
    list_display = ("store", "user", "created_at")
    search_fields = ("store__display_name", "user__username")
