from django.urls import path

from . import views

app_name = "payments"

urlpatterns = [
    path("checkout/", views.CheckoutView.as_view(), name="checkout"),
    path("sacola/", views.CartSummaryView.as_view(), name="cart_summary"),
    path("pedido/<str:token>/status/", views.OrderStatusView.as_view(), name="order_status"),
]

page_urlpatterns = [
    path("compras/", views.my_purchases_page, name="my_purchases"),
    path("finalizar/", views.checkout_page, name="checkout_page"),
    path("pedido/<str:token>/", views.order_page, name="guest_order"),
]

webhook_urlpatterns = [
    path("asaas/", views.asaas_webhook, name="asaas_webhook"),
]
