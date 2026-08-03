from django.urls import path

from . import views

app_name = "ambassadors"

urlpatterns = [
    path("", views.ambassador_landing, name="landing"),
]

api_urlpatterns = [
    path("vendedora/embaixadora/entrar/", views.AmbassadorJoinView.as_view(), name="join"),
]
