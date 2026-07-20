from django.urls import path

from . import views

app_name = "subscriptions"

urlpatterns = [
    path("planos/", views.plans, name="plans"),
]

api_urlpatterns = [
    path("assinatura/checkout/", views.SubscriptionCheckoutView.as_view(), name="checkout"),
    path("assinatura/cancelar/", views.SubscriptionCancelView.as_view(), name="cancel"),
]
