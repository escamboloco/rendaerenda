from django import forms

from .models import User, validate_adult_birth_date


class SignupForm(forms.Form):
    """
    Campos extras exigidos pelo nosso User (cpf, birth_date, role) no
    cadastro, plugados via ACCOUNT_SIGNUP_FORM_CLASS. A verificacao de
    idade REAL (biometria) acontece depois, em apps.accounts -
    birth_date aqui e so o dado declarado que entra na checagem
    oficial, nao substitui a verificacao (Lei 15.211/2025).

    IMPORTANTE: esta classe NAO pode herdar de allauth.account.forms.SignupForm
    (causa import circular - allauth monta BaseSignupForm a partir desta
    classe). O allauth exige um metodo signup(request, user); os campos
    extras ja sao persistidos antes disso, em
    apps.accounts.adapter.AgeGatedAccountAdapter.save_user (ver docstring la).
    """

    cpf = forms.CharField(
        max_length=14,
        label="CPF",
        widget=forms.TextInput(attrs={"placeholder": "Somente números", "inputmode": "numeric"}),
    )
    birth_date = forms.DateField(
        label="Data de nascimento",
        widget=forms.DateInput(attrs={"type": "date"}),
    )
    role = forms.ChoiceField(
        choices=User.Role.choices,
        initial=User.Role.BUYER,
        label="Quero",
        widget=forms.RadioSelect,
    )
    public_alias = forms.CharField(
        max_length=40,
        required=False,
        label="Apelido (opcional)",
        help_text="Como você aparece para a outra parte nas conversas. Seus dados reais continuam nos registros internos.",
        widget=forms.TextInput(attrs={"placeholder": "Deixe em branco para usar um identificador neutro"}),
    )

    field_order = ["email", "cpf", "birth_date", "role", "public_alias", "password1", "password2"]

    def clean_cpf(self):
        cpf = "".join(ch for ch in self.cleaned_data["cpf"] if ch.isdigit())
        if len(cpf) != 11:
            raise forms.ValidationError("CPF inválido.")
        if User.objects.filter(cpf=cpf).exists():
            raise forms.ValidationError("Já existe uma conta com esse CPF.")
        return cpf

    def clean_birth_date(self):
        birth_date = self.cleaned_data["birth_date"]
        validate_adult_birth_date(birth_date)
        return birth_date

    def signup(self, request, user):
        # No-op: cpf/birth_date/role ja foram setados em save_user (adapter.py)
        # antes do user.save() - obrigatorio, porque esses campos sao NOT NULL.
        pass
