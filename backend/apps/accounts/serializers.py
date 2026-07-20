from rest_framework import serializers

from .models import SellerKYC


class AgeVerificationRequestSerializer(serializers.Serializer):
    selfie_video_ref = serializers.CharField(max_length=200)


class SellerKYCSerializer(serializers.ModelSerializer):
    accepts_majority_and_image_consent_term = serializers.BooleanField(write_only=True)

    class Meta:
        model = SellerKYC
        fields = [
            "document_front", "document_back", "selfie_with_document",
            "accepts_majority_and_image_consent_term",
        ]

    def validate_accepts_majority_and_image_consent_term(self, value):
        if not value:
            raise serializers.ValidationError(
                "É obrigatório aceitar o termo de maioridade e cessão de imagem para vender."
            )
        return value

    def create(self, validated_data):
        from django.utils import timezone

        validated_data.pop("accepts_majority_and_image_consent_term")
        kyc, _ = SellerKYC.objects.update_or_create(
            user=self.context["request"].user,
            defaults={
                **validated_data,
                "status": SellerKYC.Status.PENDING,
                "majority_and_image_consent_term_signed_at": timezone.now(),
            },
        )
        return kyc
