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
CSRF_TRUSTED_ORIGINS = config("CSRF_TRUSTED_ORIGINS", default="https://*.onrender.com", cast=Csv())

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
STATICFILES_STORAGE = "whitenoise.storage.CompressedManifestStaticFilesStorage"

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

# --- Midia sensivel: nunca publica direto, sempre via S3 assinado ---
DEFAULT_FILE_STORAGE = "storages.backends.s3boto3.S3Boto3Storage"
AWS_ACCESS_KEY_ID = config("AWS_ACCESS_KEY_ID", default="")
AWS_SECRET_ACCESS_KEY = config("AWS_SECRET_ACCESS_KEY", default="")
AWS_STORAGE_BUCKET_NAME = config("AWS_STORAGE_BUCKET_NAME", default="")
AWS_S3_ENDPOINT_URL = config("AWS_S3_ENDPOINT_URL", default="")
AWS_QUERYSTRING_AUTH = True
AWS_QUERYSTRING_EXPIRE = config("AWS_S3_SIGNED_URL_EXPIRE_SECONDS", default=300, cast=int)
AWS_DEFAULT_ACL = None

# --- Seguranca (checklist da skill) ---
SESSION_COOKIE_SECURE = not DEBUG
SESSION_COOKIE_HTTPONLY = True
SESSION_COOKIE_SAMESITE = "Lax"
CSRF_COOKIE_SECURE = not DEBUG
CSRF_COOKIE_HTTPONLY = True
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
CSP_IMG_SRC = ("'self'", "data:", f"https://{AWS_STORAGE_BUCKET_NAME}" if AWS_STORAGE_BUCKET_NAME else "'self'")
# Vídeos de produto (apps.catalog.models.ProductVideo) servidos do mesmo
# bucket privado com URL assinada.
CSP_MEDIA_SRC = ("'self'", f"https://{AWS_STORAGE_BUCKET_NAME}" if AWS_STORAGE_BUCKET_NAME else "'self'")
CSP_SCRIPT_SRC = ("'self'",)
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
# USE_LOCMEM_CACHE=True roda sem Redis (dev/smoke test local) - o throttle
# do DRF usa o cache default, entao sem isso qualquer endpoint com throttle
# quebra na ausencia de Redis. Producao SEMPRE usa Redis.
if config("USE_LOCMEM_CACHE", default=False, cast=bool):
    CACHES = {"default": {"BACKEND": "django.core.cache.backends.locmem.LocMemCache"}}
else:
    CACHES = {
        "default": {
            "BACKEND": "django.core.cache.backends.redis.RedisCache",
            "LOCATION": config("REDIS_URL", default="redis://localhost:6379/0"),
        }
    }

CELERY_BROKER_URL = config("REDIS_URL", default="redis://localhost:6379/0")
CELERY_RESULT_BACKEND = CELERY_BROKER_URL
# True executa tasks inline (sem broker) - so para dev/teste local.
CELERY_TASK_ALWAYS_EAGER = config("CELERY_TASK_ALWAYS_EAGER", default=False, cast=bool)
CELERY_TASK_SERIALIZER = "json"
CELERY_ACCEPT_CONTENT = ["json"]
CELERY_BEAT_SCHEDULE = {
    "poll-active-shipments": {
        "task": "apps.shipping.tasks.poll_active_shipments",
        "schedule": 3600.0,  # a cada hora
    },
    # Libera saldo da vendedora: confirmacao do comprador ou 24h apos a
    # entrega sem contestacao (docs/checkout.md).
    "release-confirmed-deliveries": {
        "task": "apps.shipping.tasks.release_confirmed_deliveries",
        "schedule": 1800.0,  # a cada 30 min
    },
}

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
    },
}

# --- Regras de negocio do projeto (docs/BASE_JURIDICA.md, docs/checkout.md) ---
# Comissao aplicada POR CIMA do valor liquido que a vendedora pede
# (Product.payout_amount) - ela nunca "perde" 30%, o comprador que paga
# a mais. Sem assinatura/mensalidade: navegar, anunciar e comprar sao
# gratuitos - a plataforma só ganha em cima da venda.
PLATFORM_COMMISSION_PERCENT = config("PLATFORM_COMMISSION_PERCENT", default=30, cast=int)
WALLET_RELEASE_DAYS_AFTER_SHIPPING = config("WALLET_RELEASE_DAYS_AFTER_SHIPPING", default=3, cast=int)
# Janela pós-entrega pra comprador confirmar ou contestar antes da liberação
# automática do saldo pra vendedora (docs/checkout.md).
DELIVERY_CONFIRMATION_WINDOW_HOURS = config("DELIVERY_CONFIRMATION_WINDOW_HOURS", default=24, cast=int)
# Embalagem padrão comprada pela plataforma, custo embutido no frete do
# comprador - nunca repassado à vendedora (ver apps.payments.models.Order).
PACKAGING_FEE = config("PACKAGING_FEE", default=Decimal("3.90"), cast=Decimal)
PAYMENT_PROVIDER = config("PAYMENT_PROVIDER", default="asaas")

AGE_KYC_PROVIDER = config("AGE_KYC_PROVIDER", default="idwall")
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

# "correios" (contrato CWS direto) ou "melhor_envio" (recomendado -
# multi-transportadora + pontos de coleta + etiqueta automatica, ver
# docs/checkout.md e apps/shipping/melhor_envio.py).
SHIPPING_PROVIDER = config("SHIPPING_PROVIDER", default="melhor_envio")
MELHOR_ENVIO_TOKEN = config("MELHOR_ENVIO_TOKEN", default="")
MELHOR_ENVIO_SANDBOX = config("MELHOR_ENVIO_SANDBOX", default=True, cast=bool)

CORREIOS_CWS_USER = config("CORREIOS_CWS_USER", default="")
CORREIOS_CWS_PASSWORD = config("CORREIOS_CWS_PASSWORD", default="")
CORREIOS_CONTRACT_NUMBER = config("CORREIOS_CONTRACT_NUMBER", default="")
CORREIOS_CARD_NUMBER = config("CORREIOS_CARD_NUMBER", default="")
CORREIOS_ORIGIN_CEP = config("CORREIOS_ORIGIN_CEP", default="")

# --- E-mail transacional (verificacao de conta, recuperacao de senha) ---
# Sem conteudo explicito no corpo/assunto (docs/BASE_JURIDICA.md). Em DEBUG
# usa o console para nao exigir SMTP local; em producao exige config real.
EMAIL_BACKEND = config(
    "EMAIL_BACKEND",
    default="django.core.mail.backends.console.EmailBackend" if DEBUG else "django.core.mail.backends.smtp.EmailBackend",
)
EMAIL_HOST = config("EMAIL_HOST", default="")
EMAIL_PORT = config("EMAIL_PORT", default=587, cast=int)
EMAIL_HOST_USER = config("EMAIL_HOST_USER", default="")
EMAIL_HOST_PASSWORD = config("EMAIL_HOST_PASSWORD", default="")
EMAIL_USE_TLS = config("EMAIL_USE_TLS", default=True, cast=bool)
DEFAULT_FROM_EMAIL = config("DEFAULT_FROM_EMAIL", default="Renda & Renda <no-reply@rendaerenda.com.br>")

LOGIN_URL = "/contas/login/"
LOGIN_REDIRECT_URL = "/"
ACCOUNT_LOGOUT_REDIRECT_URL = "/"
ACCOUNT_ADAPTER = "apps.accounts.adapter.AgeGatedAccountAdapter"
ACCOUNT_SIGNUP_FORM_CLASS = "apps.accounts.forms.SignupForm"
# django-allauth==65.3.0 usa as chaves de configuracao "legadas" (nao a
# API nova ACCOUNT_LOGIN_METHODS/ACCOUNT_SIGNUP_FIELDS de versoes mais
# recentes) - login/cadastro por e-mail, sem campo de username.
ACCOUNT_AUTHENTICATION_METHOD = "email"
ACCOUNT_EMAIL_REQUIRED = True
ACCOUNT_USERNAME_REQUIRED = False
ACCOUNT_UNIQUE_EMAIL = True
# "optional" ate termos de servico de e-mail transacional estarem contratados;
# trocar para "mandatory" antes do lancamento (docs/BASE_JURIDICA.md nao exige,
# mas reduz cadastro com e-mail invalido).
ACCOUNT_EMAIL_VERIFICATION = config("ACCOUNT_EMAIL_VERIFICATION", default="optional")
ACCOUNT_RATE_LIMITS = {
    "login_failed": "10/5m/ip,10/5m/key",
}
