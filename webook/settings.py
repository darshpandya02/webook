"""Django settings for WeBook.

Configuration comes from environment variables. On Vercel, the Neon integration
provides DATABASE_URL / DATABASE_URL_UNPOOLED; DJANGO_SECRET_KEY is set per project.
"""

import os
from datetime import timedelta
from pathlib import Path
from urllib.parse import parse_qs, unquote, urlparse

BASE_DIR = Path(__file__).resolve().parent.parent


def _load_dotenv(path: Path) -> None:
    if not path.exists():
        return
    for line in path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


_load_dotenv(BASE_DIR / ".env")

DEBUG = os.environ.get("DJANGO_DEBUG", "0") == "1"
ON_VERCEL = bool(os.environ.get("VERCEL"))

SECRET_KEY = os.environ.get("DJANGO_SECRET_KEY", "")
if not SECRET_KEY:
    if ON_VERCEL and os.environ.get("VERCEL_ENV") == "production":
        raise RuntimeError("DJANGO_SECRET_KEY must be set in production")
    SECRET_KEY = "insecure-local-development-key-not-for-production"

ALLOWED_HOSTS = ["localhost", "127.0.0.1", ".vercel.app"]
extra_host = os.environ.get("DJANGO_ALLOWED_HOST")
if extra_host:
    ALLOWED_HOSTS.append(extra_host)
CSRF_TRUSTED_ORIGINS = ["https://*.vercel.app"]
SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")

INSTALLED_APPS = [
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.staticfiles",
    "django.contrib.postgres",
    "rest_framework",
    "drf_spectacular",
    "graphene_django",
    "hotel",
]

MIDDLEWARE = [
    "hotel.middleware.ServerTimingMiddleware",
    "django.middleware.security.SecurityMiddleware",
    "django.middleware.common.CommonMiddleware",
]

ROOT_URLCONF = "webook.urls"
WSGI_APPLICATION = "webook.wsgi.application"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [],
        "APP_DIRS": True,
        "OPTIONS": {"context_processors": ["django.template.context_processors.request"]},
    }
]

# --- Database -----------------------------------------------------------------
# Everything WeBook owns lives in one Postgres schema (default "webook"), so the
# app can share a database with other projects without touching their schemas.
DB_SCHEMA = os.environ.get("WEBOOK_DB_SCHEMA", "webook")


def _database_from_url(url: str) -> dict:
    parsed = urlparse(url)
    query = parse_qs(parsed.query)
    options = {
        # search_path is set as a startup parameter, so every statement,
        # including Django's own tables (auth, migrations), resolves to DB_SCHEMA.
        "options": f"-c search_path={DB_SCHEMA}",
    }
    if "sslmode" in query:
        options["sslmode"] = query["sslmode"][0]
    return {
        "ENGINE": "django.db.backends.postgresql",
        "NAME": unquote(parsed.path.lstrip("/")),
        "USER": unquote(parsed.username or ""),
        "PASSWORD": unquote(parsed.password or ""),
        "HOST": parsed.hostname or "",
        "PORT": parsed.port or "",
        "OPTIONS": options,
        # Fluid compute reuses warm instances; keep a connection for a minute.
        "CONN_MAX_AGE": int(os.environ.get("DB_CONN_MAX_AGE", "60")),
        "CONN_HEALTH_CHECKS": True,
        "TEST": {"NAME": os.environ.get("WEBOOK_TEST_DB", "test_webook")},
    }


# The pooled Neon endpoint (PgBouncer) does not accept the "options" startup
# parameter, so the direct endpoint is preferred when it is available.
_db_url = (
    os.environ.get("DATABASE_URL_UNPOOLED")
    or os.environ.get("POSTGRES_URL_NON_POOLING")
    or os.environ.get("DATABASE_URL")
    or "postgres://postgres@localhost:55432/webook"
)
DATABASES = {"default": _database_from_url(_db_url)}
DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator", "OPTIONS": {"min_length": 8}},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
]

LANGUAGE_CODE = "en-us"
TIME_ZONE = "America/New_York"
USE_I18N = False
USE_TZ = True

# --- Static files / SPA ------------------------------------------------------
# The React build (frontend/dist) is collected into STATIC_ROOT; on Vercel the
# collected files are served from the CDN at /static/.
STATIC_URL = "/static/"
STATIC_ROOT = BASE_DIR / "staticfiles"
SPA_DIST = BASE_DIR / "frontend" / "dist"
STATICFILES_DIRS = [SPA_DIST] if SPA_DIST.exists() else []

# --- REST framework / JWT ------------------------------------------------------
REST_FRAMEWORK = {
    "DEFAULT_AUTHENTICATION_CLASSES": ["rest_framework_simplejwt.authentication.JWTAuthentication"],
    "DEFAULT_PERMISSION_CLASSES": ["rest_framework.permissions.IsAuthenticated"],
    "DEFAULT_RENDERER_CLASSES": ["rest_framework.renderers.JSONRenderer"],
    "DEFAULT_PAGINATION_CLASS": "rest_framework.pagination.LimitOffsetPagination",
    "PAGE_SIZE": 50,
    "DEFAULT_SCHEMA_CLASS": "drf_spectacular.openapi.AutoSchema",
    "EXCEPTION_HANDLER": "hotel.api.errors.exception_handler",
    "DEFAULT_THROTTLE_CLASSES": ["rest_framework.throttling.ScopedRateThrottle"],
    "DEFAULT_THROTTLE_RATES": {"login": "30/min", "register": "10/hour"},
}

SIMPLE_JWT = {
    "ACCESS_TOKEN_LIFETIME": timedelta(minutes=30),
    "REFRESH_TOKEN_LIFETIME": timedelta(days=1),
    "AUTH_HEADER_TYPES": ("Bearer",),
    "UPDATE_LAST_LOGIN": False,
}

SPECTACULAR_SETTINGS = {
    "TITLE": "WeBook API",
    "DESCRIPTION": "Hotel booking management: availability, bookings, room service, billing.",
    "VERSION": "1.0.0",
    "SERVE_INCLUDE_SCHEMA": False,
}

GRAPHENE = {"SCHEMA": "hotel.graphql.schema.schema"}

CACHES = {"default": {"BACKEND": "django.core.cache.backends.locmem.LocMemCache"}}

CRON_SECRET = os.environ.get("CRON_SECRET", "")

LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "handlers": {"console": {"class": "logging.StreamHandler"}},
    "root": {"handlers": ["console"], "level": "WARNING"},
}
