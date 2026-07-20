from allauth.account.adapter import DefaultAccountAdapter
from django.core.exceptions import PermissionDenied


class AgeGatedAccountAdapter(DefaultAccountAdapter):
    """
    Impede login/uso de conta que nao tenha verificacao de idade
    aprovada ou que esteja banida. A verificacao real acontece no
    provider de KYC (apps.accounts.services) - aqui so garantimos que
    ninguem contorna o fluxo de cadastro.
    """

    def is_open_for_signup(self, request):
        return True

    def pre_login(self, request, user, **kwargs):
        if user.is_banned:
            raise PermissionDenied("Conta banida.")
        return super().pre_login(request, user, **kwargs)

    def save_user(self, request, user, form, commit=True):
        user = super().save_user(request, user, form, commit=False)
        # Campos extras do nosso SignupForm (apps.accounts.forms.SignupForm)
        # - precisam ser setados ANTES do save() porque cpf/birth_date sao
        # NOT NULL no model. Usuario comeca sem is_age_verified=True ate o
        # KYC/verificacao de idade ser aprovado (ver apps.accounts.services).
        data = getattr(form, "cleaned_data", {})
        if "cpf" in data:
            user.cpf = data["cpf"]
        if "birth_date" in data:
            user.birth_date = data["birth_date"]
        if "role" in data:
            user.role = data["role"]
        if "public_alias" in data:
            user.public_alias = (data["public_alias"] or "").strip()
        user.is_age_verified = False
        if commit:
            user.save()
        return user
