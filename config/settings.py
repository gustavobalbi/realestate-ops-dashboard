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

# The application reads/writes directly against a copy of the SQLite base supplied for
# the test (data_cambara.sqlite3). Business tables are modelled with managed=False so
# Django never alters their schema; only Django's own session table is migrated.
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

SESSION_ENGINE = "django.contrib.sessions.backends.db"
SESSION_COOKIE_AGE = 60 * 60 * 8  # 8h

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"
