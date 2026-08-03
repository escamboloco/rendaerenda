from django.urls import path

from . import media_views, views

app_name = "core"

urlpatterns = [
    path("", views.age_gate, name="age_gate"),
]

api_urlpatterns = [
    path("cep/<str:cep>/", views.cep_lookup, name="cep_lookup"),
]

page_urlpatterns = [
    path("healthz/", views.healthz, name="healthz"),
    path("robots.txt", views.robots_txt, name="robots_txt"),
    # Prévia de link (Open Graph). Endereço estável e fora do age gate —
    # crawler de card não tem sessão e a URL assinada da mídia expira.
    path("og/anuncio/<slug:store_slug>/<slug:product_slug>.jpg", views.og_product_image, name="og_product"),
    path("og/loja/<slug:slug>.jpg", views.og_store_image, name="og_store"),
    path(
        "media/protegido/<path:path>",
        media_views.protected_product_media,
        name="protected_media",
    ),
    path("termos-de-uso/", views.legal_page, {"doc": "termos-de-uso"}, name="terms"),
    path("privacidade/", views.legal_page, {"doc": "privacidade"}, name="privacy"),
    path("email/descadastrar/<str:token>/", views.marketing_unsubscribe, name="marketing_unsubscribe"),
]
