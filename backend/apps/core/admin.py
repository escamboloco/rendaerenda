from django.contrib import admin

from .models import MarketingSubscriber


@admin.register(MarketingSubscriber)
class MarketingSubscriberAdmin(admin.ModelAdmin):
    list_display = ("email", "name", "is_active", "source", "consented_at", "last_sent_at")
    list_filter = ("is_active", "source")
    search_fields = ("email", "name")
    readonly_fields = ("unsubscribe_token", "consented_at", "created_at")
