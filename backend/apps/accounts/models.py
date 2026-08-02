import uuid
from datetime import date

from django.contrib.auth.models import AbstractUser
from django.core.exceptions import ValidationError
from django.db import models
from django.utils import timezone


def validate_adult_birth_date(value: date):
    today = timezone.localdate()
    age = today.year - value.year - ((today.month, today.day) < (value.month, value.day))
    if age < 18:
        raise ValidationError("Cadastro permitido apenas para maiores de 18 anos.")


class User(AbstractUser):
    """
    Usuario base. Autodeclaracao de idade (checkbox) e proibida pela Lei
    15.211/2025 (ECA Digital) - is_age_verified so vira True apos um
    AgeVerification com status APPROVED. Nao remover essa trava.
    """

    class Role(models.TextChoices):
        BUYER = "buyer", "Comprador"
        SELLER = "seller", "Vendedora"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    role = models.CharField(max_length=10, choices=Role.choices, default=Role.BUYER)
    cpf = models.CharField(max_length=11, unique=True, db_index=True)
    birth_date = models.DateField(validators=[validate_adult_birth_date])
    is_age_verified = models.BooleanField(default=False)
    is_banned = models.BooleanField(default=False)
    banned_reason = models.TextField(blank=True)
    banned_at = models.DateTimeField(null=True, blank=True)

    # Telefone confirmado por SMS E vinculado ao CPF do cadastro (o bureau
    # confirma que a linha pertence ao titular do CPF antes do OTP ser
    # enviado - ver apps.accounts.phone). Compra/assinatura exigem
    # is_phone_verified=True.
    phone_number = models.CharField(max_length=15, blank=True)  # so digitos, formato 55DDDNUMERO
    is_phone_verified = models.BooleanField(default=False)

    # Apelido OPCIONAL usado exclusivamente na interacao comprador<->vendedora
    # (pedidos personalizados, mensagens). NUNCA substitui o nome/CPF reais em
    # pedido, pagamento, nota fiscal, KYC ou admin - a gestao interna e sempre
    # com identidade civil (LGPD/dever de guarda). Se vazio, mostramos um
    # identificador neutro (ver interaction_name).
    public_alias = models.CharField(max_length=40, blank=True)

    @property
    def interaction_name(self) -> str:
        return self.public_alias or f"Usuário {str(self.id)[:8]}"

    @property
    def has_store(self) -> bool:
        # Reverse OneToOne: acessar .store sem loja levanta DoesNotExist (500 no template).
        return hasattr(self, "store")

    def ban(self, reason: str):
        # Banimento por CPF (nao so e-mail), conforme docs/BASE_JURIDICA.md secao 3.
        self.is_banned = True
        self.banned_reason = reason
        self.banned_at = timezone.now()
        self.is_active = False
        self.save(update_fields=["is_banned", "banned_reason", "banned_at", "is_active"])


class AgeVerification(models.Model):
    """
    Registro auditavel de verificacao de idade. Nunca aceitar
    autodeclaracao - exige CPF + data de nascimento validados em base
    oficial + prova de vida facial (biometria). A idade "oficial" do
    usuario e SEMPRE derivada de validated_birth_date (data que o
    provider retornou da base oficial do CPF), nunca da data digitada
    no cadastro.
    """

    class Status(models.TextChoices):
        PENDING = "pending", "Pendente"
        APPROVED = "approved", "Aprovado"
        REJECTED = "rejected", "Rejeitado"

    user = models.OneToOneField(User, on_delete=models.CASCADE, related_name="age_verification")
    provider = models.CharField(max_length=50)  # idwall, unico, caf...
    provider_reference_id = models.CharField(max_length=100)
    status = models.CharField(max_length=10, choices=Status.choices, default=Status.PENDING)
    liveness_score = models.DecimalField(max_digits=5, decimal_places=2, null=True, blank=True)
    document_validated = models.BooleanField(default=False)
    # Data de nascimento REGISTRADA NA BASE OFICIAL do CPF, retornada pelo
    # provider - fonte unica de verdade para idade (Lei 15.211/2025).
    validated_birth_date = models.DateField(null=True, blank=True)
    reviewed_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        indexes = [models.Index(fields=["status"])]

    @property
    def validated_age(self) -> int | None:
        """Idade calculada da data validada em base oficial (None se ainda nao validado)."""
        if not self.validated_birth_date:
            return None
        today = timezone.localdate()
        born = self.validated_birth_date
        return today.year - born.year - ((today.month, today.day) < (born.month, born.day))


def generate_kyc_code() -> str:
    """
    Codigo curto que a vendedora escreve num papel e segura na selfie.

    E a prova de vivacidade dos pobres: garante que a foto foi tirada
    DEPOIS do cadastro e para este cadastro especifico, o que derruba
    selfie salva de outra pessoa ou baixada da internet. Nao substitui
    biometria com prova de vida (ver AgeVerification), mas e o que da
    para fazer com revisao humana enquanto o bureau nao esta contratado.
    """
    import secrets

    alphabet = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"  # sem I/O/0/1 (confunde na foto)
    return "RR-" + "".join(secrets.choice(alphabet) for _ in range(6))


class SellerKYC(models.Model):
    """
    KYC da vendedora: documento frente/verso + selfie segurando o
    documento E um papel com o codigo desta conta + termo de maioridade
    e cessao de imagem.

    Revisao HUMANA (admin), com prazo publicado de 24h uteis. Guardado em
    storage privado (AWS_QUERYSTRING_AUTH) e com retencao minima.
    """

    class Status(models.TextChoices):
        NOT_SENT = "not_sent", "Não enviada"
        PENDING = "pending", "Em análise"
        APPROVED = "approved", "Aprovada"
        REJECTED = "rejected", "Rejeitada"

    user = models.OneToOneField(User, on_delete=models.CASCADE, related_name="seller_kyc")
    # Codigo que precisa aparecer escrito a mao na selfie.
    verification_code = models.CharField(max_length=12, default=generate_kyc_code, editable=False)
    submitted_at = models.DateTimeField(null=True, blank=True)
    rejection_reason = models.TextField(blank=True)
    # Data de nascimento LIDA NO DOCUMENTO pelo revisor. E ela que vira a
    # idade oficial da conta — nunca a data digitada no cadastro.
    document_birth_date = models.DateField(null=True, blank=True)
    # blank=True porque a linha nasce vazia (status NOT_SENT) assim que a
    # vendedora abre a pagina — e isso que da um codigo estavel para ela
    # escrever no papel. O envio de verdade e validado no serializer.
    document_front = models.FileField(upload_to="kyc/documents/", blank=True)
    document_back = models.FileField(upload_to="kyc/documents/", blank=True)
    selfie_with_document = models.FileField(upload_to="kyc/selfies/", blank=True)
    majority_and_image_consent_term_signed_at = models.DateTimeField(null=True, blank=True)

    # Assinatura ELETRONICA do termo de maioridade + cessao de imagem via
    # provider (Clicksign/D4Sign/ZapSign). O checkbox de aceite continua
    # valido para o MVP, mas para forca probatoria plena (modelo Privacy)
    # o termo e enviado para assinatura eletronica com trilha de auditoria
    # (IP, timestamp, hash do documento) - referencia do envelope guardada
    # aqui. Ver docs/checkout.md.
    esign_provider = models.CharField(max_length=30, blank=True)  # clicksign, d4sign, zapsign...
    esign_document_ref = models.CharField(max_length=120, blank=True)
    esign_signed_at = models.DateTimeField(null=True, blank=True)
    esign_signed_document_url = models.URLField(blank=True)

    status = models.CharField(max_length=10, choices=Status.choices, default=Status.NOT_SENT)
    reviewed_by = models.ForeignKey(
        User, on_delete=models.SET_NULL, null=True, blank=True, related_name="kyc_reviews"
    )
    reviewed_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    def approve(self, reviewer: User, *, document_birth_date=None):
        """
        Aprova o KYC e, com a data de nascimento lida no documento,
        promove a conta a "idade verificada".

        Sem data do documento a conta continua NÃO verificada: a idade é
        exigência legal (Lei 15.211/2025) e não pode sair de um aceite
        administrativo às cegas.
        """
        from apps.payments.services import is_adult

        self.status = self.Status.APPROVED
        self.reviewed_by = reviewer
        self.reviewed_at = timezone.now()
        self.rejection_reason = ""
        if document_birth_date:
            self.document_birth_date = document_birth_date
        self.save(
            update_fields=[
                "status", "reviewed_by", "reviewed_at", "rejection_reason", "document_birth_date"
            ]
        )

        if not self.document_birth_date:
            return

        if not is_adult(self.document_birth_date):
            self.user.ban("Menor de idade confirmado na conferência do documento.")
            return

        verification, _ = AgeVerification.objects.get_or_create(
            user=self.user,
            defaults={"provider": "manual", "provider_reference_id": f"kyc:{self.pk}"},
        )
        verification.provider = "manual"
        verification.status = AgeVerification.Status.APPROVED
        verification.document_validated = True
        verification.validated_birth_date = self.document_birth_date
        verification.reviewed_at = timezone.now()
        verification.save(
            update_fields=[
                "provider", "status", "document_validated", "validated_birth_date", "reviewed_at"
            ]
        )
        self.user.is_age_verified = True
        self.user.save(update_fields=["is_age_verified"])

    def reject(self, reviewer: User, reason: str):
        self.status = self.Status.REJECTED
        self.reviewed_by = reviewer
        self.reviewed_at = timezone.now()
        self.rejection_reason = reason[:500]
        self.save(update_fields=["status", "reviewed_by", "reviewed_at", "rejection_reason"])


class PhoneVerification(models.Model):
    """
    Confirmacao de telefone em duas etapas:
      1. Bureau confirma que a linha pertence ao CPF cadastrado
         (cpf_ownership_match) - sem isso o SMS nem e enviado.
      2. OTP de 6 digitos por SMS confirma a posse do aparelho.
    O codigo NUNCA e salvo em claro - so o hash (mesmo hasher de senha
    do Django). Expira em OTP_TTL_MINUTES e trava apos MAX_ATTEMPTS.
    """

    OTP_TTL_MINUTES = 10
    MAX_ATTEMPTS = 5

    class Status(models.TextChoices):
        AWAITING_CODE = "awaiting_code", "Aguardando código"
        CPF_MISMATCH = "cpf_mismatch", "Telefone não pertence ao CPF"
        VERIFIED = "verified", "Verificado"

    user = models.OneToOneField(User, on_delete=models.CASCADE, related_name="phone_verification")
    phone_number = models.CharField(max_length=15)  # so digitos, 55DDDNUMERO
    otp_hash = models.CharField(max_length=128, blank=True)
    expires_at = models.DateTimeField(null=True, blank=True)
    attempts = models.PositiveSmallIntegerField(default=0)
    cpf_ownership_match = models.BooleanField(default=False)
    status = models.CharField(max_length=15, choices=Status.choices, default=Status.AWAITING_CODE)
    verified_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    def is_expired(self) -> bool:
        return not self.expires_at or timezone.now() > self.expires_at
