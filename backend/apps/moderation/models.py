import uuid

from django.conf import settings
from django.contrib.contenttypes.fields import GenericForeignKey
from django.contrib.contenttypes.models import ContentType
from django.db import models
from django.utils import timezone


class ModerationQueueItem(models.Model):
    """
    Toda loja e todo produto passam por aqui antes de ficarem publicos
    (docs/BASE_JURIDICA.md secao 3). Filtros automaticos (regex/OCR
    anti-servico-sexual e anti-contato) rodam antes de cair na revisao
    humana - ver apps.moderation.services.run_automated_filters.
    """

    class TargetType(models.TextChoices):
        STORE = "store", "Loja"
        PRODUCT = "product", "Produto"
        CHAT_MESSAGE = "chat_message", "Mensagem"

    class Decision(models.TextChoices):
        PENDING = "pending", "Pendente"
        APPROVED = "approved", "Aprovado"
        REJECTED = "rejected", "Rejeitado"
        AUTO_FLAGGED = "auto_flagged", "Sinalizado automaticamente"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    target_type = models.CharField(max_length=20, choices=TargetType.choices)
    content_type = models.ForeignKey(ContentType, on_delete=models.CASCADE)
    object_id = models.CharField(max_length=64)
    target = GenericForeignKey("content_type", "object_id")

    decision = models.CharField(max_length=15, choices=Decision.choices, default=Decision.PENDING)
    automated_flags = models.JSONField(default=list, blank=True)
    reviewed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name="moderation_reviews"
    )
    reviewed_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        indexes = [models.Index(fields=["decision", "target_type"])]

    def approve(self, reviewer):
        self.decision = self.Decision.APPROVED
        self.reviewed_by = reviewer
        self.reviewed_at = timezone.now()
        self.save(update_fields=["decision", "reviewed_by", "reviewed_at"])

    def reject(self, reviewer):
        self.decision = self.Decision.REJECTED
        self.reviewed_by = reviewer
        self.reviewed_at = timezone.now()
        self.save(update_fields=["decision", "reviewed_by", "reviewed_at"])


class Report(models.Model):
    """Denúncia - botão obrigatório em toda página de conteúdo."""

    class Reason(models.TextChoices):
        UNDERAGE_SUSPICION = "underage_suspicion", "Suspeita de menor de idade"
        SEXUAL_SERVICE = "sexual_service", "Oferta de serviço sexual"
        SCAM = "scam", "Golpe/fraude"
        ILLEGAL_CONTENT = "illegal_content", "Conteúdo ilegal"
        OTHER = "other", "Outro"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    reporter = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, related_name="reports_made")
    content_type = models.ForeignKey(ContentType, on_delete=models.CASCADE)
    object_id = models.CharField(max_length=64)
    target = GenericForeignKey("content_type", "object_id")
    reason = models.CharField(max_length=25, choices=Reason.choices)
    details = models.TextField(max_length=1000, blank=True)
    # Suspeita de menor: remocao imediata independente de ordem judicial
    # + reporte as autoridades (Lei 15.211/2025 art. sobre exploracao infantil).
    requires_immediate_action = models.BooleanField(default=False)
    resolved_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    def save(self, *args, **kwargs):
        if self.reason == self.Reason.UNDERAGE_SUSPICION:
            self.requires_immediate_action = True
        super().save(*args, **kwargs)
