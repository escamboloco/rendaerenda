from django.contrib import admin
from django.contrib.auth.admin import UserAdmin as DjangoUserAdmin

from .models import AgeVerification, SellerKYC, User


@admin.register(User)
class UserAdmin(DjangoUserAdmin):
    list_display = ("username", "cpf", "role", "is_age_verified", "is_banned", "is_active")
    list_filter = ("role", "is_age_verified", "is_banned")
    search_fields = ("username", "cpf", "email")
    readonly_fields = ("cpf",)
    actions = ["ban_selected_users"]

    @admin.action(description="Banir usuarios selecionados (por CPF)")
    def ban_selected_users(self, request, queryset):
        for user in queryset:
            user.ban(reason=f"Banimento manual via admin por {request.user}")


@admin.register(AgeVerification)
class AgeVerificationAdmin(admin.ModelAdmin):
    list_display = ("user", "provider", "status", "document_validated", "created_at")
    list_filter = ("status", "provider")
    search_fields = ("user__username", "user__cpf", "provider_reference_id")


@admin.register(SellerKYC)
class SellerKYCAdmin(admin.ModelAdmin):
    list_display = ("user", "status", "majority_and_image_consent_term_signed_at", "reviewed_by")
    list_filter = ("status",)
    actions = ["approve_selected"]

    @admin.action(description="Aprovar KYC selecionados")
    def approve_selected(self, request, queryset):
        for kyc in queryset:
            kyc.approve(reviewer=request.user)
