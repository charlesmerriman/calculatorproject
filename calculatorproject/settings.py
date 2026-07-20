from pathlib import Path
import os
import dj_database_url
from dotenv import load_dotenv
# reverse_lazy (NOT reverse) is required in the UNFOLD sidebar: settings.py is
# imported before the URLconf is loaded, so eager reverse() would raise. The
# lazy variant resolves the URL only when the sidebar is rendered.
from django.urls import reverse_lazy
from django.utils.translation import gettext_lazy as _

load_dotenv()

BASE_DIR = Path(__file__).resolve().parent.parent

SECRET_KEY = os.getenv("DJANGO_SECRET_KEY", "change-me-in-production")

DEBUG = os.getenv("DEBUG", "False") == "True"

ALLOWED_HOSTS = os.getenv("DJANGO_ALLOWED_HOSTS", "localhost,127.0.0.1").split(",")

INSTALLED_APPS = [
    # django-unfold must come BEFORE django.contrib.admin so its templates
    # override the stock admin's (Django resolves app templates in order).
    "unfold",
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "rest_framework",
    "rest_framework.authtoken",
    "drf_spectacular",
    "corsheaders",
    "storages",
    "calculatorapi",
]

# django-unfold (admin theme) configuration. Branding here mirrors the
# admin.site.* values in calculatorapi/admin.py, which unfold's templates
# fall back to; the sidebar keeps the default auto-generated app list.
# Per-item sidebar visibility. Unlike unfold's auto-generated app list, a
# hardcoded SIDEBAR is NOT permission-aware by default — every staff user would
# see every link. This gate hides an item from anyone lacking the given model
# permission, so the "Content editors" group never sees the user-management
# section. When all of a group's items are hidden, unfold hides the group too.
def _requires_perm(codename):
    return lambda request: request.user.has_perm(codename)


UNFOLD = {
    "SITE_TITLE": "Uma Calculator Admin",
    "SITE_HEADER": "Uma Calculator",
    "SITE_SUBHEADER": "Content management",
    # Material Symbols icon shown in the sidebar header. Using a built-in icon
    # (rather than a logo image) avoids shipping a brand asset we don't have.
    "SITE_SYMBOL": "calculate",
    "SHOW_HISTORY": True,
    "SHOW_VIEW_ON_SITE": True,
    # A small "Production"/"Local" badge in the header so the client can never
    # confuse the live admin with a local one. Callback lives in admin_dashboard.
    "ENVIRONMENT": "calculatorapi.admin_dashboard.environment_callback",
    # Populates the landing page with headline stat cards (see custom_index.html).
    "DASHBOARD_CALLBACK": "calculatorapi.admin_dashboard.dashboard_callback",
    # Header dropdown of quick links (view the live site, jump to analytics).
    "SITE_DROPDOWN": [
        {
            "icon": "open_in_new",
            "title": _("View live site"),
            "link": "/",
        },
        {
            "icon": "monitoring",
            "title": _("Analytics dashboard"),
            "link": reverse_lazy("admin-analytics"),
        },
    ],
    # Brand palette. Unfold injects each shade as `--color-primary-<n>` and uses
    # it directly (buttons, links, active nav), so any valid CSS color works.
    # This gold ramp is anchored on the frontend's brand accent (#E6D28A at 300);
    # 600–800 are darkened enough to keep white button text readable.
    "COLORS": {
        "primary": {
            "50": "#fbf8ef",
            "100": "#f6eed2",
            "200": "#ecdea5",
            "300": "#e6d28a",  # frontend --color-brand
            "400": "#d6bc5c",
            "500": "#c29e34",
            "600": "#a07f20",
            "700": "#7d621c",
            "800": "#644f1b",
            "900": "#54421a",
            "950": "#30250d",
        },
    },
    # Curated left-hand navigation. Replaces unfold's auto-generated app list so
    # the ~17 models are grouped into task-based sections with icons. NOTE: a new
    # model must be added here or it won't appear in the sidebar (it's still
    # reachable by URL). Icons are Material Symbols names.
    "SIDEBAR": {
        "show_search": True,
        "show_all_applications": False,
        "navigation": [
            {
                "title": _("Overview"),
                "items": [
                    {
                        "title": _("Dashboard"),
                        "icon": "dashboard",
                        "link": reverse_lazy("admin:index"),
                    },
                    {
                        "title": _("Analytics"),
                        "icon": "monitoring",
                        "link": reverse_lazy("admin-analytics"),
                    },
                ],
            },
            {
                "title": _("Banners"),
                "separator": True,
                "collapsible": True,
                "items": [
                    {
                        "title": _("Timelines"),
                        "icon": "calendar_month",
                        "link": reverse_lazy("admin:calculatorapi_bannertimeline_changelist"),
                    },
                    {
                        "title": _("Uma banners"),
                        "icon": "sprint",
                        "link": reverse_lazy("admin:calculatorapi_banneruma_changelist"),
                    },
                    {
                        "title": _("Support banners"),
                        "icon": "style",
                        "link": reverse_lazy("admin:calculatorapi_bannersupport_changelist"),
                    },
                ],
            },
            {
                "title": _("Events & competitions"),
                "separator": True,
                "collapsible": True,
                "items": [
                    {
                        "title": _("Game events"),
                        "icon": "event",
                        "link": reverse_lazy("admin:calculatorapi_gameevent_changelist"),
                    },
                    {
                        "title": _("Event rewards"),
                        "icon": "redeem",
                        "link": reverse_lazy("admin:calculatorapi_eventreward_changelist"),
                    },
                    {
                        "title": _("Champions Meetings"),
                        "icon": "emoji_events",
                        "link": reverse_lazy("admin:calculatorapi_championsmeeting_changelist"),
                    },
                    {
                        "title": _("League of Heroes"),
                        "icon": "military_tech",
                        "link": reverse_lazy("admin:calculatorapi_leagueofheroes_changelist"),
                    },
                ],
            },
            {
                "title": _("Characters"),
                "separator": True,
                "collapsible": True,
                "items": [
                    {
                        "title": _("Umas"),
                        "icon": "directions_run",
                        "link": reverse_lazy("admin:calculatorapi_uma_changelist"),
                    },
                    {
                        "title": _("Support cards"),
                        "icon": "cards",
                        "link": reverse_lazy("admin:calculatorapi_supportcard_changelist"),
                    },
                ],
            },
            {
                "title": _("Income tables"),
                "separator": True,
                "collapsible": True,
                "items": [
                    {
                        "title": _("Club ranks"),
                        "icon": "groups",
                        "link": reverse_lazy("admin:calculatorapi_clubrank_changelist"),
                    },
                    {
                        "title": _("Team Trials ranks"),
                        "icon": "diversity_3",
                        "link": reverse_lazy("admin:calculatorapi_teamtrialsrank_changelist"),
                    },
                    {
                        "title": _("Champions Meeting ranks"),
                        "icon": "emoji_events",
                        "link": reverse_lazy("admin:calculatorapi_championsmeetingrank_changelist"),
                    },
                    {
                        "title": _("League of Heroes ranks"),
                        "icon": "military_tech",
                        "link": reverse_lazy("admin:calculatorapi_leagueofheroesrank_changelist"),
                    },
                ],
            },
            {
                "title": _("Site content"),
                "separator": True,
                "collapsible": True,
                "items": [
                    {
                        "title": _("Changelog"),
                        "icon": "history",
                        "link": reverse_lazy("admin:calculatorapi_changelogentry_changelist"),
                    },
                ],
            },
            {
                "title": _("Users & access"),
                "separator": True,
                "collapsible": True,
                "items": [
                    {
                        "title": _("Users"),
                        "icon": "person",
                        "link": reverse_lazy("admin:calculatorapi_customuser_changelist"),
                        "permission": _requires_perm("calculatorapi.view_customuser"),
                    },
                    {
                        "title": _("Planned banners"),
                        "icon": "checklist",
                        "link": reverse_lazy("admin:calculatorapi_userplannedbanner_changelist"),
                        "permission": _requires_perm("calculatorapi.view_userplannedbanner"),
                    },
                    {
                        "title": _("Groups"),
                        "icon": "shield_person",
                        "link": reverse_lazy("admin:auth_group_changelist"),
                        "permission": _requires_perm("auth.view_group"),
                    },
                ],
            },
        ],
    },
}

REST_FRAMEWORK = {
    "DEFAULT_AUTHENTICATION_CLASSES": (
        "rest_framework.authentication.TokenAuthentication",
    ),
    "DEFAULT_PERMISSION_CLASSES": [
        "rest_framework.permissions.IsAuthenticated",
    ],
    "DEFAULT_SCHEMA_CLASS": "drf_spectacular.openapi.AutoSchema",
}

CORS_ALLOW_ALL_ORIGINS = False
CORS_ALLOWED_ORIGINS = os.getenv("CORS_ORIGIN_WHITELIST", "http://localhost:5173").split(",")

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "whitenoise.middleware.WhiteNoiseMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "corsheaders.middleware.CorsMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

ROOT_URLCONF = "calculatorproject.urls"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [],
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

WSGI_APPLICATION = "calculatorproject.wsgi.application"

DATABASE_URL = os.getenv("DATABASE_URL")

if DATABASE_URL:
    DATABASES = {
        "default": dj_database_url.config(conn_max_age=600)
    }
else:
    DATABASES = {
        "default": {
            "ENGINE": "django.db.backends.sqlite3",
            "NAME": BASE_DIR / "db.sqlite3",
        }
    }

AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator"},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]

LANGUAGE_CODE = "en-us"
TIME_ZONE = "UTC"
USE_I18N = True
USE_TZ = True

STATIC_URL = "static/"
STATIC_ROOT = BASE_DIR / "staticfiles"

# django-storages: media files go to DigitalOcean Spaces; static files stay on whitenoise.
# STORAGES replaces the old STATICFILES_STORAGE setting (deprecated in Django 4.2+).
STORAGES = {
    "default": {
        "BACKEND": "storages.backends.s3boto3.S3Boto3Storage",
        "OPTIONS": {
            "access_key": os.getenv("DO_SPACES_ACCESS_KEY"),
            "secret_key": os.getenv("DO_SPACES_SECRET_KEY"),
            "bucket_name": os.getenv("DO_SPACES_BUCKET_NAME"),
            # Base Spaces endpoint (not the CDN) — boto3 uses this for API calls.
            "endpoint_url": os.getenv("DO_SPACES_ENDPOINT_URL"),
            # CDN domain used to build public-facing image URLs (no https:// prefix).
            "custom_domain": os.getenv("DO_SPACES_CDN_DOMAIN"),
            "default_acl": "public-read",
            "file_overwrite": False,
            # Disable signed query params so CDN URLs are clean and cacheable.
            "querystring_auth": False,
        },
    },
    "staticfiles": {
        "BACKEND": "whitenoise.storage.CompressedManifestStaticFilesStorage",
    },
}

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

AUTH_USER_MODEL = "calculatorapi.CustomUser"

SPECTACULAR_SETTINGS = {
    "TITLE": "Calculator API",
    "DESCRIPTION": "API for the calculator capstone",
    "VERSION": "1.0.0",
}

WHITENOISE_STATIC_PREFIX = '/static/'

# Log all Django errors to stdout so DigitalOcean runtime logs capture tracebacks.
# Without this, Django silently swallows 500 errors when DEBUG=False.
LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "handlers": {
        "console": {
            "class": "logging.StreamHandler",
        },
    },
    "loggers": {
        "django": {
            "handlers": ["console"],
            "level": "WARNING",
        },
        "django.request": {
            "handlers": ["console"],
            "level": "ERROR",
            "propagate": False,
        },
    },
}
