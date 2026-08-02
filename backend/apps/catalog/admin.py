from django.contrib import admin

from .models import (
    Category,
    Product,
    ProductAddon,
    ProductAsset,
    ProductImage,
    ProductQuestion,
    ProductVideo,
)


@admin.register(Category)
class CategoryAdmin(admin.ModelAdmin):
    list_display = ("name", "slug", "has_page_text")
    prepopulated_fields = {"slug": ("name",)}

    @admin.display(boolean=True, description="Texto próprio")
    def has_page_text(self, obj):
        """
        Sem `description`, /categorias/<slug>/ cai num texto genérico igual
        ao das outras — e categoria sem texto próprio não ranqueia. Esta
        coluna é para enxergar de relance o que falta escrever.
        """
        return bool(obj.description)


class ProductImageInline(admin.TabularInline):
    model = ProductImage
    extra = 1


class ProductVideoInline(admin.TabularInline):
    model = ProductVideo
    extra = 0


class ProductAddonInline(admin.TabularInline):
    """Adicionais pagos do anúncio — o preço é derivado do payout no save()."""

    model = ProductAddon
    extra = 0
    readonly_fields = ("price",)


class ProductAssetInline(admin.TabularInline):
    """Arquivos entregues em anúncio de conteúdo digital."""

    model = ProductAsset
    extra = 0


@admin.register(Product)
class ProductAdmin(admin.ModelAdmin):
    list_display = ("title", "store", "kind", "category", "price", "status", "stock", "sold_count")
    list_filter = ("status", "kind", "category", "visibility")
    search_fields = ("title", "store__display_name")
    readonly_fields = ("price", "views_count", "sold_count", "created_at")
    inlines = [ProductImageInline, ProductVideoInline, ProductAddonInline, ProductAssetInline]


@admin.register(ProductQuestion)
class ProductQuestionAdmin(admin.ModelAdmin):
    """Fila de perguntas — dá para moderar e responder pelo admin."""

    list_display = ("product", "question", "answered", "is_public", "created_at")
    list_filter = ("is_public",)
    search_fields = ("question", "answer", "product__title")

    @admin.display(boolean=True, description="Respondida")
    def answered(self, obj):
        return bool(obj.answer)
