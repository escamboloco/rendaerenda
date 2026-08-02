from django.urls import path

from . import views

app_name = "backoffice"

urlpatterns = [
    path("entrar/", views.staff_login, name="login"),
    path("sair/", views.staff_logout, name="logout"),
    path("", views.dashboard, name="dashboard"),
    path("identidade/", views.kyc_queue, name="kyc_queue"),
    path("identidade/<int:kyc_id>/decidir/", views.kyc_decide, name="kyc_decide"),
    path("moderacao/", views.moderation_queue, name="moderation"),
    path("moderacao/<uuid:item_id>/decidir/", views.moderation_decide, name="moderation_decide"),
    path("disputas/", views.disputes, name="disputes"),
    path("disputas/<uuid:order_id>/decidir/", views.dispute_decide, name="dispute_decide"),
    path("financeiro/", views.finance, name="finance"),
    path("pedidos/", views.orders, name="orders"),
    path("lojas/", views.stores_list, name="stores"),
    path("pessoas/", views.people, name="people"),
]
