from django.urls import path

from . import views

app_name = "offers"

urlpatterns = [
    path("pedidos-personalizados/", views.my_requests_page, name="my_requests"),
]

api_urlpatterns = [
    path("pedidos-personalizados/", views.CustomRequestCreateView.as_view(), name="create"),
    path("pedidos-personalizados/<uuid:request_id>/decidir/", views.BuyerDecideCounterView.as_view(), name="buyer_decide"),
    path("vendedora/pedidos-personalizados/<uuid:request_id>/responder/", views.SellerRespondView.as_view(), name="seller_respond"),
]
