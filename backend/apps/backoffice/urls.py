from django.urls import path

from . import views

app_name = "backoffice"

urlpatterns = [
    path("entrar/", views.staff_login, name="login"),
    path("sair/", views.staff_logout, name="logout"),
    path("", views.dashboard, name="dashboard"),
    path("pedidos/", views.orders, name="orders"),
    path("financeiro/", views.finance, name="finance"),
    path("lojas/", views.stores, name="stores"),
    path("moderacao/", views.moderation, name="moderation"),
    path("moderacao/<uuid:item_id>/<str:decision>/", views.moderate, name="moderate"),
    path("denuncias/<uuid:report_id>/resolver/", views.resolve_report, name="resolve_report"),
    path("disputas/", views.disputes, name="disputes"),
    path("disputas/<uuid:order_id>/<str:decision>/", views.resolve_dispute, name="resolve_dispute"),
    path("contas/", views.accounts, name="accounts"),
]
