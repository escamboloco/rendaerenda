from django.urls import path

from . import views

app_name = "catalog"

urlpatterns = [
    path("vendedora/anunciar/", views.product_create_page, name="create"),
    path("vendedora/meus-anuncios/", views.seller_products_page, name="seller_products"),
    path("vendedora/perguntas/", views.seller_questions_page, name="seller_questions"),
    path("loja/<slug:store_slug>/item/<slug:product_slug>/", views.product_detail, name="detail"),
    path("pedido/<str:token>/arquivo/<uuid:asset_id>/", views.download_asset, name="download_asset"),
]

api_urlpatterns = [
    path("vendedora/anuncios/", views.ProductCreateView.as_view(), name="api_create"),
    path("vendedora/anuncios/<uuid:product_id>/", views.ProductUpdateView.as_view(), name="api_update"),
    path(
        "vendedora/anuncios/<uuid:product_id>/pausar/",
        views.ProductPauseView.as_view(),
        name="api_pause",
    ),
    path(
        "vendedora/anuncios/<uuid:product_id>/publicar/",
        views.ProductResumeView.as_view(),
        name="api_resume",
    ),
    path(
        "anuncios/<uuid:product_id>/perguntas/",
        views.ProductQuestionCreateView.as_view(),
        name="question_create",
    ),
    path(
        "anuncios/perguntas/<uuid:question_id>/responder/",
        views.ProductAnswerView.as_view(),
        name="question_answer",
    ),
]
