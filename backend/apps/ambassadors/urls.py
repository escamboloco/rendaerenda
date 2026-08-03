from django.urls import path

from . import views

app_name = "ambassadors"

urlpatterns = [
    path("", views.ambassador_landing, name="landing"),
    path("convite/<str:token>/", views.accept_ambassador_invite, name="accept_invite"),
]

api_urlpatterns = [
    path("vendedora/embaixadora/entrar/", views.AmbassadorJoinView.as_view(), name="join"),
]
