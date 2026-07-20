from rest_framework import serializers

from .models import Report


class ReportCreateSerializer(serializers.Serializer):
    target_type = serializers.ChoiceField(choices=["product", "store"])
    object_id = serializers.CharField()
    reason = serializers.ChoiceField(choices=Report.Reason.choices)
    details = serializers.CharField(max_length=1000, required=False, allow_blank=True)
