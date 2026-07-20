from django.core.exceptions import ValidationError as DjangoValidationError
from django.shortcuts import get_object_or_404
from rest_framework import status
from rest_framework.exceptions import ValidationError
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.payments.models import Order

from .serializers import ReviewCreateSerializer, ReviewSerializer
from .services import create_review


class ReviewCreateView(APIView):
    """POST /api/avaliacoes/ — avaliação (1-5 estrelas + comentário) de um pedido entregue."""

    permission_classes = [IsAuthenticated]
    throttle_scope = "offers"

    def post(self, request):
        serializer = ReviewCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        order = get_object_or_404(Order, id=data["order_id"])

        try:
            review = create_review(
                buyer=request.user, order=order, rating=data["rating"], comment=data["comment"]
            )
        except DjangoValidationError as exc:
            raise ValidationError(exc.messages)
        return Response(ReviewSerializer(review).data, status=status.HTTP_201_CREATED)
