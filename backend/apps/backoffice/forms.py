from django import forms


class StaffLoginForm(forms.Form):
    email = forms.EmailField(
        label="E-mail administrativo",
        widget=forms.EmailInput(
            attrs={
                "autocomplete": "username",
                "autofocus": True,
                "placeholder": "admin@empresa.com.br",
            }
        ),
    )
    password = forms.CharField(
        label="Senha",
        strip=False,
        widget=forms.PasswordInput(attrs={"autocomplete": "current-password"}),
    )
