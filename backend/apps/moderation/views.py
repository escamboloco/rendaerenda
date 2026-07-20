from django.contrib.contenttypes.models import ContentType
from django.shortcuts import get_object_or_404
from rest_framework import status
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.catalog.models import Product
from apps.stores.models import Store

from .models import Report
from .serializers import ReportCreateSerializer

TARGET_MODELS = {"product": Product, "store": Store}


class ReportCreateView(APIView):
    """
    POST /api/denuncia/ — botao obrigatorio em toda pagina de conteudo
    (docs/BASE_JURIDICA.md secao 3). Aberto a visitantes nao logados
    (denuncia de suspeita de menor nao pode depender de cadastro), mas
    limitado por throttle para evitar abuso.
    """

    permission_classes = [AllowAny]
    throttle_scope = "report"

    def post(self, request):
        serializer = ReportCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data

        model = TARGET_MODELS[data["target_type"]]
        target = get_object_or_404(model, id=data["object_id"])

        Report.objects.create(
            reporter=request.user if request.user.is_authenticated else None,
            content_type=ContentType.objects.get_for_model(model),
            object_id=str(target.id),
            reason=data["reason"],
            details=data.get("details", ""),
        )
        return Response({"received": True}, status=status.HTTP_201_CREATED)
