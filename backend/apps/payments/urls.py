from django.urls import path

from . import views

app_name = "payments"

urlpatterns = [
    path("checkout/", views.CheckoutView.as_view(), name="checkout"),
]

page_urlpatterns = [
    path("compras/", views.my_purchases_page, name="my_purchases"),
]

webhook_urlpatterns = [
    path("asaas/", views.asaas_webhook, name="asaas_webhook"),
]
