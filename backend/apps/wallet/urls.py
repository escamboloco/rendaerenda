from django.urls import path

from . import views

app_name = "wallet"

urlpatterns = [
    path("carteira/", views.dashboard, name="dashboard"),
]

api_urlpatterns = [
    path("carteira/saldo/", views.WalletBalanceView.as_view(), name="balance"),
    path("carteira/historico/", views.WalletHistoryView.as_view(), name="history"),
    path("carteira/saque/", views.WithdrawalRequestView.as_view(), name="withdrawal"),
]
