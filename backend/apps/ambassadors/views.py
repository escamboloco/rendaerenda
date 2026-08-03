from django.conf import settings
from django.core.exceptions import ValidationError
from django.shortcuts import render
from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.stores.models import Store

from .models import Ambassador, AmbassadorProgram
from .services import ambassador_dashboard_context, join_ambassador_program


def ambassador_landing(request):
    """
    GET /embaixadoras/ — landing do programa.

    Público (sem login): explica o programa e mostra quantas vagas
    restam — página de aquisição, não painel. Vendedora com loja ativa
    vê o convite para entrar ou, se já é embaixadora, o próprio painel
    (link de indicação + extrato). É a mesma URL nos dois casos para não
    espalhar o programa em duas páginas com conteúdo quase idêntico.
    """
    program = AmbassadorProgram.singleton()
    store = getattr(request.user, "store", None) if request.user.is_authenticated else None
    ambassador = getattr(store, "ambassador", None) if store else None

    context = {
        "program": program,
        "store": store,
        "ambassador": ambassador,
        "bonus_percent": settings.AMBASSADOR_REVENUE_SHARE_PERCENT,
        "window_days": settings.AMBASSADOR_REWARD_WINDOW_DAYS,
        # noindex só na variante com dados pessoais (extrato/saldo da
        # embaixadora) — a landing pública continua indexável, é caminho
        # de aquisição orgânica (docs/BASE_JURIDICA.md § 6).
        "is_dashboard_view": bool(ambassador),
    }
    if ambassador:
        context.update(ambassador_dashboard_context(ambassador, request))

    return render(request, "ambassadors/landing.html", context)


class AmbassadorJoinView(APIView):
    """
    POST /api/vendedora/embaixadora/entrar/ — reivindica uma das 20 vagas
    para a loja do usuário autenticado.
    """

    permission_classes = [IsAuthenticated]
    throttle_scope = "checkout"

    def post(self, request):
        store = getattr(request.user, "store", None)
        if not store:
            return Response(
                {"detail": "Abra sua loja antes de entrar no programa de embaixadoras."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        if store.status != Store.Status.ACTIVE:
            return Response(
                {"detail": "Sua loja precisa estar ativa (liberada da moderação) para participar."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        try:
            ambassador = join_ambassador_program(store)
        except ValidationError as exc:
            return Response({"detail": exc.messages[0]}, status=status.HTTP_409_CONFLICT)

        return Response(
            {
                "seat_number": ambassador.seat_number,
                "referral_code": ambassador.referral_code,
                "referral_link": request.build_absolute_uri(ambassador.referral_path),
            },
            status=status.HTTP_201_CREATED,
        )
