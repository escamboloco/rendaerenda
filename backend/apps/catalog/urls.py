from django.urls import path

from . import views

app_name = "catalog"

urlpatterns = [
    path("vendedora/anunciar/", views.product_create_page, name="create"),
    path("loja/<slug:store_slug>/item/<slug:product_slug>/", views.product_detail, name="detail"),
]

api_urlpatterns = [
    path("vendedora/anuncios/", views.ProductCreateView.as_view(), name="api_create"),
]
