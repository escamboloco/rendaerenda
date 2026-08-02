from rest_framework import serializers

from apps.core.media_security import sanitize_image, validate_safe_image

from .models import SellerKYC


class AgeVerificationRequestSerializer(serializers.Serializer):
    selfie_video_ref = serializers.CharField(max_length=200)


class SellerKYCSerializer(serializers.ModelSerializer):
    accepts_majority_and_image_consent_term = serializers.BooleanField(write_only=True)
    document_front = serializers.ImageField(validators=[validate_safe_image])
    document_back = serializers.ImageField(validators=[validate_safe_image])
    selfie_with_document = serializers.ImageField(validators=[validate_safe_image])

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
        for field in ("document_front", "document_back", "selfie_with_document"):
            validated_data[field] = sanitize_image(validated_data[field])
        kyc, _ = SellerKYC.objects.update_or_create(
            user=self.context["request"].user,
            defaults={
                **validated_data,
                "status": SellerKYC.Status.PENDING,
                "submitted_at": timezone.now(),
                "rejection_reason": "",
                "majority_and_image_consent_term_signed_at": timezone.now(),
            },
        )
        return kyc
