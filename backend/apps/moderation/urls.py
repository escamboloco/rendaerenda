from django.urls import path

from . import views

api_urlpatterns = [
    path("denuncia/", views.ReportCreateView.as_view(), name="report_create"),
]
