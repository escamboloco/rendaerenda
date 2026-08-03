from decimal import Decimal
from pathlib import Path
import dj_database_url
from decouple import config, Csv

BASE_DIR = Path(__file__).resolve().parent.parent

SECRET_KEY = config("DJANGO_SECRET_KEY")
DEBUG = config("DJANGO_DEBUG", default=False, cast=bool)
ALLOWED_HOSTS = config("DJANGO_ALLOWED_HOSTS", default="", cast=Csv())
# Render (e qualquer PaaS atras de proxy reverso) termina TLS antes do
# processo Django - sem isso, request.is_secure() sempre da False atras do
# proxy, quebrando SECURE_SSL_REDIRECT (loop de redirect) e o cookie CSRF.
SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
CSRF_TRUSTED_ORIGINS = config(
    "CSRF_TRUSTED_ORIGINS",
    default=(
        "https://rendaerenda.com.br,"
        "https://www.rendaerenda.com.br,"
        "https://*.onrender.com"
    ),
    cast=Csv(),
)

INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "django.contrib.sites",
    "django.contrib.sitemaps",
    "rest_framework",
    "django_htmx",
    "widget_tweaks",
    "allauth",
    "allauth.account",
    "apps.accounts",
    "apps.ambassadors",
    "apps.stores",
    "apps.catalog",
    "apps.subscriptions",
    "apps.payments",
    "apps.wallet",
    "apps.shipping",
    "apps.moderation",
    "apps.offers",
    "apps.reviews",
    "apps.core",
    "apps.backoffice",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "whitenoise.middleware.WhiteNoiseMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
    "csp.middleware.CSPMiddleware",
    "django_htmx.middleware.HtmxMiddleware",
    "allauth.account.middleware.AccountMiddleware",
    "apps.core.middleware.AgeGateMiddleware",
]

SITE_ID = 1
# Usado por django.contrib.sites (allauth referencia isso em e-mails
# transacionais - sem isso, o padrao "example.com" vaza pro usuario).
SITE_DOMAIN = config("SITE_DOMAIN", default="localhost:8000" if DEBUG else "rendaerenda.com.br")
SITE_NAME = config("SITE_NAME", default="Renda & Renda")

AUTHENTICATION_BACKENDS = [
    "django.contrib.auth.backends.ModelBackend",
    "allauth.account.auth_backends.AuthenticationBackend",
]

ROOT_URLCONF = "config.urls"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [BASE_DIR / "templates"],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.debug",
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
                "apps.stores.context_processors.header_store_carousel",
            ],
        },
    },
]

WSGI_APPLICATION = "config.wsgi.application"

DATABASES = {
    "default": dj_database_url.parse(config("DATABASE_URL")),
}

AUTH_USER_MODEL = "accounts.User"

AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator", "OPTIONS": {"min_length": 10}},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]

LANGUAGE_CODE = "pt-br"
TIME_ZONE = "America/Sao_Paulo"
USE_I18N = True
USE_TZ = True

STATIC_URL = "static/"
STATICFILES_DIRS = [BASE_DIR / "static"]
STATIC_ROOT = BASE_DIR / "staticfiles"

MEDIA_URL = "media/"
# Producao no Render: disco persistente montado em /var/data (ver render.yaml).
# Dev local: backend/media/. Nao guardar fotos no Postgres.
MEDIA_ROOT = Path(config("MEDIA_ROOT", default=str(BASE_DIR / "media")))

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

# S3 opcional. Vazio = FileSystemStorage (disco do Render / pasta local).
AWS_ACCESS_KEY_ID = config("AWS_ACCESS_KEY_ID", default="")
AWS_SECRET_ACCESS_KEY = config("AWS_SECRET_ACCESS_KEY", default="")
AWS_STORAGE_BUCKET_NAME = config("AWS_STORAGE_BUCKET_NAME", default="")
AWS_S3_ENDPOINT_URL = config("AWS_S3_ENDPOINT_URL", default="")
AWS_QUERYSTRING_AUTH = True
AWS_QUERYSTRING_EXPIRE = config("AWS_S3_SIGNED_URL_EXPIRE_SECONDS", default=300, cast=int)
AWS_DEFAULT_ACL = None
USE_S3_MEDIA = bool(AWS_STORAGE_BUCKET_NAME)

# Em DEBUG o WhiteNoise reconsulta o disco a cada request. Sem isso ele
# guarda o estatico em memoria na subida do processo e continua servindo a
# versao antiga depois de um `npm run build:css` — erro que custa horas de
# depuracao porque o arquivo em disco esta certo e a tela, errada.
WHITENOISE_AUTOREFRESH = DEBUG
WHITENOISE_MAX_AGE = 0 if DEBUG else 31536000

STORAGES = {
    "default": {
        "BACKEND": (
            "storages.backends.s3boto3.S3Boto3Storage"
            if USE_S3_MEDIA
            else "django.core.files.storage.FileSystemStorage"
        ),
        "OPTIONS": {} if USE_S3_MEDIA else {"location": str(MEDIA_ROOT)},
    },
    "staticfiles": {
        "BACKEND": "whitenoise.storage.CompressedManifestStaticFilesStorage",
    },
}

# --- Seguranca (checklist da skill) ---
SESSION_COOKIE_SECURE = not DEBUG
SESSION_COOKIE_HTTPONLY = True
SESSION_COOKIE_SAMESITE = "Lax"
SESSION_COOKIE_AGE = 60 * 60 * 12
SESSION_SAVE_EVERY_REQUEST = True
CSRF_COOKIE_SECURE = not DEBUG
# False: o JS do checkout precisa ler o cookie csrftoken pro header X-CSRFToken.
# O cookie CSRF nao e segredo de sessao; SameSite=Lax + Secure em producao.
CSRF_COOKIE_HTTPONLY = False
CSRF_COOKIE_SAMESITE = "Lax"
SECURE_SSL_REDIRECT = not DEBUG
SECURE_HSTS_SECONDS = 31536000 if not DEBUG else 0
SECURE_HSTS_INCLUDE_SUBDOMAINS = True
SECURE_HSTS_PRELOAD = True
X_FRAME_OPTIONS = "DENY"
SECURE_REFERRER_POLICY = "strict-origin-when-cross-origin"
SECURE_CONTENT_TYPE_NOSNIFF = True

# CSP restritiva. Tailwind, HTMX e Alpine sao compilados/vendorizados
# localmente (ver backend/package.json e static/vendor/) - zero dependencia
# de CDN externo, tanto por seguranca (CSP sem excecoes) quanto por
# privacidade (nenhuma requisicao de terceiro no navegador da compradora).
CSP_DEFAULT_SRC = ("'self'",)
CSP_IMG_SRC = ("'self'", "data:", f"https://{AWS_STORAGE_BUCKET_NAME}" if USE_S3_MEDIA else "'self'")
CSP_MEDIA_SRC = ("'self'", f"https://{AWS_STORAGE_BUCKET_NAME}" if USE_S3_MEDIA else "'self'")
# 'unsafe-eval' e exigido pelo Alpine.js (build padrao, nao o build "csp")
# pra avaliar expressoes como x-show/x-data - sem isso, TODA diretiva
# Alpine falha silenciosamente (fica no estado inicial: x-cloak nunca vira
# x-show, modais somem ou ficam presos visiveis). O script em si continua
# restrito a 'self' - nao abre brecha pra script de terceiro, so pra eval
# do proprio JS que ja roda na pagina.
CSP_SCRIPT_SRC = ("'self'", "'unsafe-eval'")
CSP_STYLE_SRC = ("'self'", "'unsafe-inline'")
CSP_FONT_SRC = ("'self'",)
CSP_CONNECT_SRC = ("'self'",)
CSP_FRAME_ANCESTORS = ("'none'",)
CSP_BASE_URI = ("'self'",)
CSP_FORM_ACTION = ("'self'",)

# --- Nunca logar dados sensiveis ---
LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "filters": {
        "redact_sensitive": {
            "()": "apps.core.logging_filters.RedactSensitiveDataFilter",
        },
    },
    "handlers": {
        "console": {
            "class": "logging.StreamHandler",
            "filters": ["redact_sensitive"],
        },
    },
    "root": {"handlers": ["console"], "level": "INFO"},
}

# --- Rate limiting ---
RATELIMIT_ENABLE = True
RATELIMIT_USE_CACHE = "default"
# Cache no proprio Postgres (tabela django_cache) - sem custo extra de um
# servico Redis no Render. USE_LOCMEM_CACHE=True pula ate o banco (dev
# rapido/smoke test); nunca usar isso em producao (cache nao seria
# compartilhado entre workers do gunicorn).
if config("USE_LOCMEM_CACHE", default=False, cast=bool):
    CACHES = {"default": {"BACKEND": "django.core.cache.backends.locmem.LocMemCache"}}
else:
    CACHES = {
        "default": {
            "BACKEND": "django.core.cache.backends.db.DatabaseCache",
            "LOCATION": "django_cache",
        }
    }

# Sem worker/broker dedicado no Render (custo) - toda task Celery roda
# sincrona, no mesmo processo do gunicorn/manage.py que a disparou.
# ".delay(...)" continua funcionando normalmente nesse modo. As duas
# tarefas periodicas (rastreio de envio + liberacao de saldo) rodam via
# Render Cron Job chamando os management commands `poll_shipments` e
# `release_deliveries` (ver render.yaml) em vez de um Celery beat.
CELERY_BROKER_URL = "memory://"
CELERY_TASK_ALWAYS_EAGER = True
CELERY_TASK_EAGER_PROPAGATES = True
CELERY_TASK_SERIALIZER = "json"
CELERY_ACCEPT_CONTENT = ["json"]

REST_FRAMEWORK = {
    "DEFAULT_AUTHENTICATION_CLASSES": [
        "rest_framework.authentication.SessionAuthentication",
    ],
    "DEFAULT_PERMISSION_CLASSES": [
        "rest_framework.permissions.IsAuthenticated",
    ],
    "DEFAULT_THROTTLE_CLASSES": [
        "rest_framework.throttling.ScopedRateThrottle",
    ],
    "DEFAULT_THROTTLE_RATES": {
        "checkout": "10/min",
        "withdrawal": "5/min",
        "login": "10/min",
        "report": "10/min",
        "phone": "5/min",
        "offers": "10/min",
        "freight": "20/min",
        # A tela de pagamento consulta o status a cada 4s enquanto o Pix
        # nao cai; precisa de folga bem maior que o resto.
        "order_status": "60/min",
        "cart": "60/min",
    },
}

# --- Regras de negocio do projeto (docs/BASE_JURIDICA.md, docs/checkout.md) ---
# Comissao aplicada POR CIMA do valor liquido que a vendedora pede
# (Product.payout_amount) - ela nunca "perde" a comissao; o comprador que paga
# a mais. Sem assinatura/mensalidade: navegar, anunciar e comprar sao
# gratuitos - a plataforma só ganha em cima da venda.
PLATFORM_COMMISSION_PERCENT = config("PLATFORM_COMMISSION_PERCENT", default=Decimal("20"), cast=Decimal)
WALLET_RELEASE_DAYS_AFTER_SHIPPING = config("WALLET_RELEASE_DAYS_AFTER_SHIPPING", default=3, cast=int)

# --- Programa de embaixadoras (apps.ambassadors) ---
# As 20 primeiras vendedoras a entrar ganham 10% do platform_amount (lucro
# da plataforma, não o valor do item) de cada venda de quem elas indicarem,
# pelos primeiros 60 dias da loja indicada. Ver docs/checkout.md § 8 sobre
# por que isso é lançado como bônus de venda indicada, não como repasse de
# comissão — e docs/BASE_JURIDICA.md sobre o que ainda precisa de validação
# jurídica/contábil antes do lançamento.
AMBASSADOR_PROGRAM_MAX_SEATS = config("AMBASSADOR_PROGRAM_MAX_SEATS", default=20, cast=int)
AMBASSADOR_REVENUE_SHARE_PERCENT = config(
    "AMBASSADOR_REVENUE_SHARE_PERCENT", default=Decimal("10"), cast=Decimal
)
AMBASSADOR_REWARD_WINDOW_DAYS = config("AMBASSADOR_REWARD_WINDOW_DAYS", default=60, cast=int)

# --- Custódia (o dinheiro fica com a plataforma até a entrega) ---
# É a promessa central da vitrine: o comprador não paga direto na mão de
# ninguém. O crédito da venda nasce retido e só vira sacável quando o
# comprador confirma o recebimento ou a janela de contestação vence.
ESCROW_ENABLED = config("ESCROW_ENABLED", default=True, cast=bool)
# Janela pós-entrega para confirmar ou contestar antes da liberação
# automática do saldo para a vendedora.
DELIVERY_CONFIRMATION_WINDOW_HOURS = config("DELIVERY_CONFIRMATION_WINDOW_HOURS", default=168, cast=int)
# Conteúdo digital não tem entrega para rastrear: libera por prazo.
DIGITAL_RELEASE_HOURS = config("DIGITAL_RELEASE_HOURS", default=24, cast=int)
# Teto de retenção: mesmo sem confirmação nem rastreio, o valor não fica
# preso para sempre.
ESCROW_MAX_HOLD_DAYS = config("ESCROW_MAX_HOLD_DAYS", default=30, cast=int)
# Prazo do comprador para abrir disputa depois de receber.
DISPUTE_WINDOW_DAYS = config("DISPUTE_WINDOW_DAYS", default=7, cast=int)
# Pix automático no momento da LIBERAÇÃO da custódia.
AUTO_PAYOUT_ON_RELEASE = config("AUTO_PAYOUT_ON_RELEASE", default=True, cast=bool)
# Legado — modelo simplificado nao soma embalagem (frete inteiro pra vendedora).
PACKAGING_FEE = config("PACKAGING_FEE", default=Decimal("0.00"), cast=Decimal)
# Soft-launch: checkout sem cotacao de frete (frete R$ 0, serviço pac).
CHECKOUT_FREE_SHIPPING = config("CHECKOUT_FREE_SHIPPING", default=False, cast=bool)
# Frete usado quando nao ha contrato de transportadora configurado (ou a
# cotacao falha). Sem isso, uma indisponibilidade da SuperFrete derrubaria TODA
# venda. Ajuste para o custo medio real de uma postagem sua.
SHIPPING_FLAT_RATE = config("SHIPPING_FLAT_RATE", default=Decimal("0.00"), cast=Decimal)
# Quanto tempo o pedido segura o estoque esperando o Pix. Passou disso, o
# management command expire_orders devolve o item para a vitrine.
ORDER_PAYMENT_TTL_MINUTES = config("ORDER_PAYMENT_TTL_MINUTES", default=60, cast=int)
# Validade da cobranca no Asaas (dueDate). Com 0 o QR morre a meia-noite.
PIX_DUE_DAYS = config("PIX_DUE_DAYS", default=3, cast=int)
# True (padrao): plataforma compra a etiqueta SuperFrete com o frete do
# comprador; vendedora so imprime e posta. False: frete inteiro vai pra ela.
PLATFORM_BUYS_SHIPPING_LABEL = config("PLATFORM_BUYS_SHIPPING_LABEL", default=True, cast=bool)
# Pix da EMBALAGEM NEUTRA para a vendedora na confirmacao do pagamento
# (compra a caixa sem tirar do bolso). Com etiqueta pela plataforma, o
# valor da transportadora NAO e repassado — fica para comprar a etiqueta.
AUTO_PAYOUT_SHIPPING_ON_PAYMENT = config("AUTO_PAYOUT_SHIPPING_ON_PAYMENT", default=True, cast=bool)
# Remetente discreto na etiqueta (nao usa o nome da loja / apelido).
SHIPPING_SENDER_NAME = config("SHIPPING_SENDER_NAME", default="")
SHIPPING_SENDER_DOCUMENT = config("SHIPPING_SENDER_DOCUMENT", default="")  # CNPJ da plataforma
SHIPPING_SENDER_EMAIL = config("SHIPPING_SENDER_EMAIL", default="")
SHIPPING_SENDER_PHONE = config("SHIPPING_SENDER_PHONE", default="")
SHIPPING_SENDER_STREET = config("SHIPPING_SENDER_STREET", default="")
SHIPPING_SENDER_NUMBER = config("SHIPPING_SENDER_NUMBER", default="")
SHIPPING_SENDER_DISTRICT = config("SHIPPING_SENDER_DISTRICT", default="")
SHIPPING_SENDER_CITY = config("SHIPPING_SENDER_CITY", default="")
SHIPPING_SENDER_STATE = config("SHIPPING_SENDER_STATE", default="")
# Precos da embalagem neutra por faixa de tamanho, em JSON. Os padroes de
# apps/shipping/packaging.py sao REFERENCIA, nao cotacao oficial dos
# Correios — confira antes de vender de verdade.
NEUTRAL_BOX_PRICES = config("NEUTRAL_BOX_PRICES", default="")
# Pix pago por CPF diferente do titular do pedido: estornar automaticamente.
# E uma trava de idade (so adulto identificado compra), nao antifraude.
REFUND_ON_PAYER_CPF_MISMATCH = config("REFUND_ON_PAYER_CPF_MISMATCH", default=True, cast=bool)
REQUIRE_PAYER_DOCUMENT = config("REQUIRE_PAYER_DOCUMENT", default=True, cast=bool)
# True forcaria KYC biometrico no checkout. Padrao False: a trava e o
# CPF do Pix bater com o cadastrado (REFUND_ON_PAYER_CPF_MISMATCH).
REQUIRE_VERIFIED_BUYER_AGE = config(
    "REQUIRE_VERIFIED_BUYER_AGE", default=False, cast=bool
)
ENABLE_STORE_PLAN_SALES = config("ENABLE_STORE_PLAN_SALES", default=False, cast=bool)
PAYMENT_PROVIDER = config("PAYMENT_PROVIDER", default="asaas")
ASAAS_API_KEY = config("ASAAS_API_KEY", default="")
ASAAS_API_URL = config("ASAAS_API_URL", default="https://api.asaas.com/v3")
ASAAS_WEBHOOK_TOKEN = config("ASAAS_WEBHOOK_TOKEN", default="")
# "pf" = conta pessoa fisica (sem subconta/split: cobra tudo e repassa Pix).
# "pj" = conta CNPJ com split + subcontas (modelo definitivo).
ASAAS_ACCOUNT_TYPE = config("ASAAS_ACCOUNT_TYPE", default="pf").lower()
# Pix imediato na confirmacao do pagamento. So vale com ESCROW_ENABLED=False —
# com custodia ligada, o repasse acontece na liberacao (AUTO_PAYOUT_ON_RELEASE).
AUTO_PAYOUT_ON_PAYMENT = config("AUTO_PAYOUT_ON_PAYMENT", default=False, cast=bool)
# Soft-launch: abrir loja sem KYC aprovado (ainda exige idade +18 no site).
REQUIRE_SELLER_KYC = config("REQUIRE_SELLER_KYC", default=True, cast=bool)

# --- Verificacao de idade por biometria (Lei 15.211/2025) ---
# Cada bureau tem endpoint proprio, entao a URL e explicita — nunca
# derivada do nome do provider. Sem URL + chave, o fluxo fica desligado:
# a API responde 503 e o webhook nao aceita ninguem (ver apps.accounts).
AGE_KYC_PROVIDER = config("AGE_KYC_PROVIDER", default="idwall")
AGE_KYC_API_URL = config("AGE_KYC_API_URL", default="")
AGE_KYC_API_KEY = config("AGE_KYC_API_KEY", default="")

# Bureau que confirma se a linha movel pertence ao CPF (Serpro Datavalid,
# idwall etc.) - obrigatorio antes do OTP por SMS (apps.accounts.phone).
PHONE_CPF_BUREAU_URL = config("PHONE_CPF_BUREAU_URL", default="")
PHONE_CPF_BUREAU_API_KEY = config("PHONE_CPF_BUREAU_API_KEY", default="")
# Provider de envio de SMS (Zenvia, Twilio, AWS SNS...)
SMS_PROVIDER_URL = config("SMS_PROVIDER_URL", default="")
SMS_PROVIDER_API_KEY = config("SMS_PROVIDER_API_KEY", default="")

# NFS-e da PLATAFORMA (comissao, assinaturas, planos, boosts - nunca o item,
# que e vendido pela vendedora). Provider padrao: Focus NFe.
NFSE_PROVIDER_URL = config("NFSE_PROVIDER_URL", default="https://api.focusnfe.com.br/v2/nfse")
NFSE_PROVIDER_API_KEY = config("NFSE_PROVIDER_API_KEY", default="")
PLATFORM_LEGAL_NAME = config("PLATFORM_LEGAL_NAME", default="")   # razao social neutra (cobranca discreta)
PLATFORM_CNPJ = config("PLATFORM_CNPJ", default="")
PLATFORM_MUNICIPAL_SERVICE_CODE = config("PLATFORM_MUNICIPAL_SERVICE_CODE", default="")

# "correios" (contrato CWS direto) ou "superfrete" (recomendado -
# multi-transportadora + etiqueta automatica, ver
# docs/checkout.md e apps/shipping/superfrete.py).
SHIPPING_PROVIDER = config("SHIPPING_PROVIDER", default="superfrete")
SUPERFRETE_TOKEN = config("SUPERFRETE_TOKEN", default="")
SUPERFRETE_SANDBOX = config("SUPERFRETE_SANDBOX", default=True, cast=bool)
# Serviços: Mini Envios primeiro (pacote pequeno/barato), depois PAC/SEDEX/Jadlog.
# Loggi é controlada nas configurações do token SuperFrete; J&T exige telefone.
SUPERFRETE_SERVICES = config("SUPERFRETE_SERVICES", default="17,1,2,3")
SUPERFRETE_USER_AGENT = config(
    "SUPERFRETE_USER_AGENT",
    default=f"{SITE_NAME}/1.0 (suporte@{SITE_DOMAIN})",
)

CORREIOS_CWS_USER = config("CORREIOS_CWS_USER", default="")
CORREIOS_CWS_PASSWORD = config("CORREIOS_CWS_PASSWORD", default="")
CORREIOS_CONTRACT_NUMBER = config("CORREIOS_CONTRACT_NUMBER", default="")
CORREIOS_CARD_NUMBER = config("CORREIOS_CARD_NUMBER", default="")
CORREIOS_ORIGIN_CEP = config("CORREIOS_ORIGIN_CEP", default="")

# --- E-mail transacional (verificacao de conta, recuperacao de senha) ---
# Sem conteudo explicito no corpo/assunto (docs/BASE_JURIDICA.md). Em DEBUG
# usa o console. Em producao, SMTP so se EMAIL_HOST + USER estiverem setados;
# senao cai no console pra nao quebrar o cadastro com 500.
EMAIL_HOST = config("EMAIL_HOST", default="")
EMAIL_PORT = config("EMAIL_PORT", default=587, cast=int)
EMAIL_HOST_USER = config("EMAIL_HOST_USER", default="")
EMAIL_HOST_PASSWORD = config("EMAIL_HOST_PASSWORD", default="")
EMAIL_USE_TLS = config("EMAIL_USE_TLS", default=True, cast=bool)
DEFAULT_FROM_EMAIL = config("DEFAULT_FROM_EMAIL", default="Renda & Renda <no-reply@rendaerenda.com.br>")
# Caixa que recebe alerta de contestação e outros casos que exigem decisão
# humana. Vazio = ninguém é avisado (só fica no log).
MODERATION_ALERT_EMAIL = config("MODERATION_ALERT_EMAIL", default="")

# Nome que aparece no extrato do cartao/Pix de quem compra. Quem define de
# fato e o cadastro da conta Asaas (razao social / nome do titular) — esta
# variavel serve para o site MOSTRAR ao comprador o mesmo nome que ele vai
# ver na fatura. Preencha com exatamente o que o Asaas exibe.
STATEMENT_DESCRIPTOR = config("STATEMENT_DESCRIPTOR", default="")
_EMAIL_CONFIGURED = bool(EMAIL_HOST and EMAIL_HOST_USER)
EMAIL_BACKEND = config(
    "EMAIL_BACKEND",
    default=(
        "django.core.mail.backends.smtp.EmailBackend"
        if (not DEBUG and _EMAIL_CONFIGURED)
        else "django.core.mail.backends.console.EmailBackend"
    ),
)

LOGIN_URL = "/contas/login/"
LOGIN_REDIRECT_URL = "/"
ACCOUNT_LOGOUT_REDIRECT_URL = "/"
# Logout só via POST (formulário com CSRF) — evita CSRF por link GET.
ACCOUNT_LOGOUT_ON_GET = False
BACKOFFICE_LOGIN_URL = "/gestao/entrar/"
ACCOUNT_ADAPTER = "apps.accounts.adapter.AgeGatedAccountAdapter"
ACCOUNT_SIGNUP_FORM_CLASS = "apps.accounts.forms.SignupForm"
# django-allauth==65.3.0 usa as chaves de configuracao "legadas" (nao a
# API nova ACCOUNT_LOGIN_METHODS/ACCOUNT_SIGNUP_FIELDS de versoes mais
# recentes) - login/cadastro por e-mail, sem campo de username.
ACCOUNT_AUTHENTICATION_METHOD = "email"
ACCOUNT_EMAIL_REQUIRED = True
ACCOUNT_USERNAME_REQUIRED = False
ACCOUNT_UNIQUE_EMAIL = True
# Sem SMTP configurado: "none" (allauth com "optional" ainda TENTA enviar
# e-mail e o SMTP quebrado vira Server Error 500 no /contas/signup/).
# Com SMTP ok: "optional". Trocar para "mandatory" no lancamento se quiser.
ACCOUNT_EMAIL_VERIFICATION = config(
    "ACCOUNT_EMAIL_VERIFICATION",
    default="optional" if _EMAIL_CONFIGURED else "none",
)
ACCOUNT_RATE_LIMITS = {
    "login_failed": "10/5m/ip,10/5m/key",
}

# Chave Pix opcional da antiga loja smoke (seed_payment_test).
PIX_TEST_KEY = config("PIX_TEST_KEY", default="")
# Se True no build/deploy, roda seed_demo (20+ lojas / 70+ produtos / fotos).
SEED_PAYMENT_TEST = config("SEED_PAYMENT_TEST", default=False, cast=bool)
