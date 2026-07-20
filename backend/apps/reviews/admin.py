from django.contrib import admin

from .models import Review


@admin.register(Review)
class ReviewAdmin(admin.ModelAdmin):
    list_display = ("store", "buyer", "rating", "created_at")
    list_filter = ("rating",)
    search_fields = ("store__display_name", "buyer__cpf", "comment")
