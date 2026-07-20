from django.urls import path

from . import views

app_name = "accounts"

urlpatterns = [
    path("verificacao-idade/", views.AgeVerificationRequestView.as_view(), name="age_verification_request"),
    path("telefone/solicitar/", views.PhoneVerificationRequestView.as_view(), name="phone_request"),
    path("telefone/confirmar/", views.PhoneVerificationConfirmView.as_view(), name="phone_confirm"),
    path("vendedora/kyc/", views.SellerKYCSubmitView.as_view(), name="seller_kyc_submit"),
]

webhook_urlpatterns = [
    path("kyc/", views.age_verification_webhook, name="age_verification_webhook"),
]

page_urlpatterns = [
    path("verificacao-idade/", views.verification_page, name="verification_page"),
    path("verificacao-telefone/", views.phone_page, name="phone_page"),
    path("minha-conta/", views.profile_page, name="profile_page"),
    path("vendedora/kyc/", views.seller_kyc_page, name="seller_kyc_page"),
]
