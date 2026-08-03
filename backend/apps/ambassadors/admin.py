from django.contrib import admin

from .models import Ambassador, AmbassadorProgram, Referral


@admin.register(AmbassadorProgram)
class AmbassadorProgramAdmin(admin.ModelAdmin):
    list_display = ("slots_taken", "max_seats", "seats_left")

    def has_add_permission(self, request):
        # Singleton: a linha já existe (AmbassadorProgram.singleton()).
        return False

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(Ambassador)
class AmbassadorAdmin(admin.ModelAdmin):
    list_display = ("seat_number", "store", "referral_code", "is_active", "created_at")
    list_filter = ("is_active",)
    search_fields = ("store__display_name", "store__slug", "referral_code")
    readonly_fields = ("referral_code", "seat_number", "created_at")


@admin.register(Referral)
class ReferralAdmin(admin.ModelAdmin):
    list_display = ("referred_store", "ambassador", "created_at", "reward_expires_at")
    search_fields = ("referred_store__display_name", "ambassador__store__display_name")
    readonly_fields = ("created_at",)
