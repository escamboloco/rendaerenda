from rest_framework import serializers

from .models import WalletEntry, WithdrawalRequest


class WalletBalanceSerializer(serializers.Serializer):
    available_balance = serializers.DecimalField(max_digits=10, decimal_places=2)
    pending_balance = serializers.DecimalField(max_digits=10, decimal_places=2)


class WalletEntrySerializer(serializers.ModelSerializer):
    class Meta:
        model = WalletEntry
        fields = ["id", "kind", "amount", "available_at", "created_at", "order"]


class WithdrawalRequestSerializer(serializers.ModelSerializer):
    # pix_key e read-only: o servico sempre usa a chave CPF da dona da loja
    # (apps.wallet.services.request_withdrawal) - o cliente nao escolhe destino.
    class Meta:
        model = WithdrawalRequest
        fields = ["id", "amount", "pix_key", "status", "requested_at", "paid_at"]
        read_only_fields = ["id", "pix_key", "status", "requested_at", "paid_at"]
