from django.urls import path

from . import views

api_urlpatterns = [
    path("avaliacoes/", views.ReviewCreateView.as_view(), name="create"),
]
