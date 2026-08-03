from django.conf import settings
from django.contrib import messages
from django.core.exceptions import ValidationError
from django.core.signing import BadSignature, SignatureExpired, TimestampSigner
from django.shortcuts import redirect, render
from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.stores.models import Store

from .models import Ambassador, AmbassadorProgram
from .services import ambassador_dashboard_context, join_ambassador_program

_INVITE_SIGNER = TimestampSigner(salt="ambassador-invite")
INVITE_MAX_AGE = 7 * 24 * 3600  # 7 dias


def accept_ambassador_invite(request, token):
    """
    GET /embaixadoras/convite/<token>/

    Link único gerado pelo admin (python manage.py gerar_convite_embaixadoras).
    Qualquer uma das 20 embaixadoras usa o mesmo URL — as vagas são
    preenchidas por ordem de chegada.

    Fluxo:
    1. Vendedora clica o link → sessão é marcada + redireciona para /vender/
    2. Ela cria a loja → StoreOnboardView chama attach_ambassador_on_store_creation
    3. Hub da loja exibe o link de indicação dela

    Se já tem loja mas ainda não é embaixadora, entra direto sem passar
    pelo cadastro. Se já é embaixadora, vai ao hub. Requer login para
    ambos os casos.
    """
    from apps.ambassadors.services import (
        AMBASSADOR_INVITE_SESSION_KEY,
        attach_ambassador_on_store_creation,
        capture_ambassador_invite,
    )

    try:
        payload = _INVITE_SIGNER.unsign(token, max_age=INVITE_MAX_AGE)
        if payload != "ambassador-program":
            raise BadSignature
    except SignatureExpired:
        return render(request, "ambassadors/invite_expired.html", status=410)
    except BadSignature:
        return render(request, "ambassadors/invite_invalid.html", status=400)

    program = AmbassadorProgram.singleton()
    if program.is_full:
        return render(request, "ambassadors/invite_full.html", {"program": program}, status=410)

    # Vendedora já tem loja — entra direto no programa (sem sessão).
    if request.user.is_authenticated:
        store = getattr(request.user, "store", None)
        if store:
            if hasattr(store, "ambassador"):
                messages.info(request, "Você já é embaixadora! Seu link está no painel da loja.")
                return redirect("stores:seller_hub")
            try:
                join_ambassador_program(store)
                messages.success(
                    request,
                    "Bem-vinda ao programa! Seu link de indicação está pronto no painel da sua loja.",
                )
            except ValidationError as exc:
                messages.error(request, exc.messages[0])
            return redirect("stores:seller_hub")

    # Sem loja ainda — marca sessão e manda abrir a loja.
    capture_ambassador_invite(request)
    messages.info(
        request,
        "Você foi convidada para o programa de embaixadoras! Crie sua loja para ativar os benefícios.",
    )
    if not request.user.is_authenticated:
        return redirect("stores:sell")
    return redirect("stores:sell")


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
