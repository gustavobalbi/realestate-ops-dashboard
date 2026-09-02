"""
Django settings for the Cambará Empreendimentos technical test project.
"""

import os
from pathlib import Path

from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent.parent

load_dotenv(BASE_DIR / ".env")

SECRET_KEY = os.environ.get(
    "DJANGO_SECRET_KEY",
    "django-insecure-kecx!7^d@4s&cxtg75tum1os%%f5tvradd++&qgy-!g(ime#rv",
)

DEBUG = os.environ.get("DJANGO_DEBUG", "1") == "1"

ALLOWED_HOSTS = ["*"] if DEBUG else os.environ.get("DJANGO_ALLOWED_HOSTS", "").split(",")

if not DEBUG:
    if SECRET_KEY.startswith("django-insecure-"):
        raise RuntimeError(
            "DJANGO_DEBUG=0 mas DJANGO_SECRET_KEY não foi definida -- configure uma chave "
            "própria (variável de ambiente no serviço de hospedagem) antes de rodar em "
            "produção."
        )
    # PaaS como Render ficam atrás de um proxy que termina o TLS e encaminha a requisição
    # por HTTP internamente, sinalizando o esquema original via X-Forwarded-Proto. Sem
    # isso o Django acha que toda requisição é HTTP e o CSRF do login/formulários falha.
    SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
    CSRF_TRUSTED_ORIGINS = [f"https://{host}" for host in ALLOWED_HOSTS if host]

# GEMINI_API_KEY powers the natural-language question assistant (negocio/nl_assistant.py).
# Free tier from https://aistudio.google.com/apikey is enough for a demo.
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", "")
GEMINI_MODEL = os.environ.get("GEMINI_MODEL", "gemini-3.1-flash-lite")

INSTALLED_APPS = [
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "negocio",
]

# No django.contrib.auth / admin: authentication is implemented directly against the
# existing `usuarios` table (see negocio/auth.py). This matches the brief's request for
# a simple, non-production auth layer built from the data that is already in the base.
MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "whitenoise.middleware.WhiteNoiseMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
    "negocio.auth.CurrentUserMiddleware",
]

ROOT_URLCONF = "config.urls"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [BASE_DIR / "templates"],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.request",
                "django.contrib.messages.context_processors.messages",
                "negocio.auth.current_user_context",
            ],
        },
    },
]

WSGI_APPLICATION = "config.wsgi.application"

# The application reads/writes against a copy of the SQLite base supplied for the test
# (data_cambara.sqlite3) by default. Business tables are modelled with managed=False so
# Django never alters their schema; only Django's own session table is migrated -- this
# holds regardless of which engine below is active.
#
# Set AZURE_SQL_SERVER (+ AZURE_SQL_DATABASE/_USER/_PASSWORD) to switch to Azure SQL
# Database in production (Azure App Service) without touching local dev at all, which
# keeps using SQLite exactly as documented in the README.
if os.environ.get("AZURE_SQL_SERVER"):
    DATABASES = {
        "default": {
            "ENGINE": "mssql",
            "NAME": os.environ["AZURE_SQL_DATABASE"],
            "USER": os.environ["AZURE_SQL_USER"],
            "PASSWORD": os.environ["AZURE_SQL_PASSWORD"],
            "HOST": os.environ["AZURE_SQL_SERVER"],
            "PORT": os.environ.get("AZURE_SQL_PORT", "1433"),
            "OPTIONS": {
                "driver": "ODBC Driver 18 for SQL Server",
                "extra_params": "Encrypt=yes;TrustServerCertificate=no;Connection Timeout=30;",
            },
        }
    }
else:
    DATABASES = {
        "default": {
            "ENGINE": "django.db.backends.sqlite3",
            "NAME": BASE_DIR / "data_cambara.sqlite3",
            "OPTIONS": {"timeout": 20},
        }
    }

LANGUAGE_CODE = "pt-br"
TIME_ZONE = "America/Sao_Paulo"
USE_I18N = True
USE_TZ = True
USE_THOUSAND_SEPARATOR = True  # ex.: R$ 129.810.520,86 em vez de R$ 129810520,86

STATIC_URL = "static/"
STATICFILES_DIRS = [BASE_DIR / "static"]

if not DEBUG:
    # Só em produção: exige "manage.py collectstatic" ter rodado (ver startup.sh) para
    # existir o manifesto que essa storage usa. Em dev local, DEBUG=True, o servidor de
    # desenvolvimento já serve STATICFILES_DIRS diretamente -- nada disso é tocado.
    STATIC_ROOT = BASE_DIR / "staticfiles"
    STORAGES = {
        "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
        "staticfiles": {"BACKEND": "whitenoise.storage.CompressedManifestStaticFilesStorage"},
    }

SESSION_ENGINE = "django.contrib.sessions.backends.db"
SESSION_COOKIE_AGE = 60 * 60 * 8  # 8h

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

# O logging padrão do Django só imprime traceback de erro 500 no console quando
# DEBUG=True (o handler "console" embutido tem um filtro require_debug_true) -- em
# produção (DEBUG=False) o erro fica mudo por padrão, mesmo indo para o log do serviço de
# hospedagem. Isso sobrescreve só o suficiente para sempre logar erro 500 com traceback no
# stdout/stderr, que é o que a Render (e a maioria dos PaaS) captura como log do serviço --
# sem isso, um erro em produção é invisível até alguém reproduzir localmente com DEBUG=True.
LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "handlers": {
        "console": {"class": "logging.StreamHandler"},
    },
    "loggers": {
        "django.request": {
            "handlers": ["console"],
            "level": "ERROR",
            "propagate": False,
        },
    },
}
