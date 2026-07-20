from django.urls import path

from . import views

app_name = "stores"

urlpatterns = [
    path("", views.home, name="home"),
    path("ranking/", views.ranking_page, name="ranking"),
    path("vendedora/abrir-loja/", views.onboard_page, name="onboard_page"),
    path("loja/<slug:slug>/", views.store_detail, name="detail"),
]

api_urlpatterns = [
    path("vendedora/loja/", views.StoreOnboardView.as_view(), name="onboard"),
    path("vendedora/loja/plano/checkout/", views.StorePlanCheckoutView.as_view(), name="plan_checkout"),
    path("vendedora/loja/boost/", views.StoreBoostPurchaseView.as_view(), name="boost_purchase"),
]
