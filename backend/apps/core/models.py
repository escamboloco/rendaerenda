import secrets
import uuid

from django.db import models
from django.utils import timezone


class MarketingSubscriber(models.Model):
    """
    Lista de e-mail marketing com opt-in explicito (LGPD).
    Sem conteudo explicito nos disparos — so novidades genericas da plataforma.
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    email = models.EmailField(unique=True, db_index=True)
    name = models.CharField(max_length=150, blank=True)
    is_active = models.BooleanField(default=True)
    consented_at = models.DateTimeField()
    unsubscribed_at = models.DateTimeField(null=True, blank=True)
    unsubscribe_token = models.CharField(max_length=64, unique=True, db_index=True)
    source = models.CharField(max_length=40, default="checkout")
    last_sent_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        indexes = [
            models.Index(fields=["is_active", "last_sent_at"], name="core_mkt_active_sent_idx"),
        ]

    def __str__(self):
        return self.email

    @classmethod
    def subscribe(cls, *, email: str, name: str = "", source: str = "checkout"):
        email = (email or "").strip().lower()
        if not email:
            return None
        token = secrets.token_urlsafe(32)
        obj, created = cls.objects.get_or_create(
            email=email,
            defaults={
                "name": (name or "").strip()[:150],
                "consented_at": timezone.now(),
                "unsubscribe_token": token,
                "source": source,
                "is_active": True,
            },
        )
        if not created and not obj.is_active:
            obj.is_active = True
            obj.consented_at = timezone.now()
            obj.unsubscribed_at = None
            obj.name = (name or obj.name or "").strip()[:150]
            obj.source = source
            obj.save(
                update_fields=[
                    "is_active", "consented_at", "unsubscribed_at", "name", "source",
                ]
            )
        return obj

    def unsubscribe(self):
        self.is_active = False
        self.unsubscribed_at = timezone.now()
        self.save(update_fields=["is_active", "unsubscribed_at"])
