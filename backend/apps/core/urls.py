from django.urls import path

from . import views

app_name = "core"

urlpatterns = [
    path("", views.age_gate, name="age_gate"),
]

page_urlpatterns = [
    path("healthz/", views.healthz, name="healthz"),
    path("robots.txt", views.robots_txt, name="robots_txt"),
    path("termos-de-uso/", views.legal_page, {"doc": "termos-de-uso"}, name="terms"),
    path("privacidade/", views.legal_page, {"doc": "privacidade"}, name="privacy"),
]
