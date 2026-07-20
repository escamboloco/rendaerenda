from django.contrib import admin

from .models import ModerationQueueItem, Report


@admin.register(ModerationQueueItem)
class ModerationQueueItemAdmin(admin.ModelAdmin):
    list_display = ("target_type", "target", "decision", "reviewed_by", "reviewed_at")
    list_filter = ("target_type", "decision")
    actions = ["approve_selected", "reject_selected"]

    @admin.action(description="Aprovar selecionados")
    def approve_selected(self, request, queryset):
        for item in queryset:
            item.approve(reviewer=request.user)

    @admin.action(description="Rejeitar selecionados")
    def reject_selected(self, request, queryset):
        for item in queryset:
            item.reject(reviewer=request.user)


@admin.register(Report)
class ReportAdmin(admin.ModelAdmin):
    list_display = ("target", "reason", "requires_immediate_action", "resolved_at", "created_at")
    list_filter = ("reason", "requires_immediate_action")
