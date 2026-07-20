from django.urls import path

from . import views

app_name = "shipping"

urlpatterns = [
    path("frete/cotacao/", views.FreightQuoteView.as_view(), name="quote"),
    path("vendedora/pedidos/<uuid:order_id>/postagem/", views.MarkPostedView.as_view(), name="mark_posted"),
    path("vendedora/pontos-coleta/", views.DropoffPointsView.as_view(), name="dropoff_points"),
    path("pedidos/<uuid:order_id>/recebimento/", views.DeliveryConfirmationView.as_view(), name="delivery_confirmation"),
]
