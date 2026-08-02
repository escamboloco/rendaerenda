from django.contrib import admin
from django.contrib.auth.admin import UserAdmin as DjangoUserAdmin
from django.urls import reverse
from django.utils.html import format_html

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
    exclude = ("document_front", "document_back", "selfie_with_document")
    readonly_fields = (
        "verification_code",
        "submitted_at",
        "reviewed_at",
        "reviewed_by",
        "secure_document_front",
        "secure_document_back",
        "secure_selfie",
    )
    actions = ["approve_selected", "reject_selected"]

    def _secure_link(self, obj, field, label):
        stored_file = getattr(obj, field)
        if not stored_file:
            return "Não enviado"
        url = reverse("backoffice:kyc_file", args=[obj.id, field])
        return format_html('<a href="{}" target="_blank" rel="noreferrer">{}</a>', url, label)

    @admin.display(description="Documento — frente")
    def secure_document_front(self, obj):
        return self._secure_link(obj, "document_front", "Abrir frente com acesso protegido")

    @admin.display(description="Documento — verso")
    def secure_document_back(self, obj):
        return self._secure_link(obj, "document_back", "Abrir verso com acesso protegido")

    @admin.display(description="Selfie + código")
    def secure_selfie(self, obj):
        return self._secure_link(obj, "selfie_with_document", "Abrir selfie com acesso protegido")

    @admin.action(description="Aprovar (exige data de nascimento do documento preenchida)")
    def approve_selected(self, request, queryset):
        approved, missing = 0, 0
        for kyc in queryset:
            try:
                kyc.approve(reviewer=request.user)
            except ValueError:
                missing += 1
                continue
            approved += 1
        if approved:
            self.message_user(
                request,
                f"{approved} KYC aprovado(s), idade verificada e loja liberada quando aplicável.",
            )
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
