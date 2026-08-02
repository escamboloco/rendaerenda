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
    """
    Fila de conferência de identidade. O revisor abre os arquivos, confere
    se o rosto bate com o documento, se o código escrito no papel é o
    mesmo desta conta e digita a data de nascimento que está no documento.
    """

    list_display = ("user", "status", "verification_code", "document_birth_date", "submitted_at", "reviewed_by")
    list_filter = ("status",)
    search_fields = ("user__username", "user__email", "user__cpf", "verification_code")
    readonly_fields = ("verification_code", "submitted_at", "reviewed_at", "reviewed_by")
    actions = ["approve_selected", "reject_selected"]

    @admin.action(description="Aprovar (exige data de nascimento do documento preenchida)")
    def approve_selected(self, request, queryset):
        approved, missing = 0, 0
        for kyc in queryset:
            if not kyc.document_birth_date:
                missing += 1
                continue
            kyc.approve(reviewer=request.user)
            approved += 1
        if approved:
            self.message_user(request, f"{approved} KYC aprovado(s) e idade verificada.")
        if missing:
            self.message_user(
                request,
                f"{missing} não aprovado(s): preencha a data de nascimento lida no documento antes.",
                level="warning",
            )

    @admin.action(description="Rejeitar (pede reenvio à vendedora)")
    def reject_selected(self, request, queryset):
        for kyc in queryset:
            kyc.reject(
                reviewer=request.user,
                reason="Documento ou selfie ilegível, ou código do papel não confere. Envie novamente.",
            )
        self.message_user(request, f"{queryset.count()} KYC rejeitado(s).")
