from pathlib import Path
from dotenv import load_dotenv
import os

load_dotenv()

BASE_DIR = Path(__file__).resolve().parent.parent

_secret_key = os.getenv('SECRET_KEY')
if not _secret_key:
    raise ValueError("SECRET_KEY n'est pas définie. Ajoutez-la dans .env ou dans les variables d'environnement.")
SECRET_KEY = _secret_key

DEBUG = os.getenv('DEBUG', 'False') == 'True'
ALLOWED_HOSTS = os.getenv('ALLOWED_HOSTS', 'localhost,127.0.0.1').split(',')

# Vercel — ajoute automatiquement le domaine de déploiement preview
_vercel_url = os.getenv('VERCEL_URL')
if _vercel_url and _vercel_url not in ALLOWED_HOSTS:
    ALLOWED_HOSTS.append(_vercel_url)

# Accepte tous les sous-domaines *.vercel.app pour les previews
ALLOWED_HOSTS += [h for h in ['.vercel.app'] if h not in ALLOWED_HOSTS]

INSTALLED_APPS = [
    'django.contrib.admin',
    'django.contrib.auth',
    'django.contrib.contenttypes',
    'django.contrib.sessions',
    'django.contrib.messages',
    'whitenoise.runserver_nostatic',
    'django.contrib.staticfiles',
    'banks',
    'accounts',
    'transactions',
    'notifications',
]

MIDDLEWARE = [
    'django.middleware.security.SecurityMiddleware',
    'whitenoise.middleware.WhiteNoiseMiddleware',
    'django.contrib.sessions.middleware.SessionMiddleware',
    'django.middleware.common.CommonMiddleware',
    'django.middleware.csrf.CsrfViewMiddleware',
    'django.contrib.auth.middleware.AuthenticationMiddleware',
    'django.contrib.messages.middleware.MessageMiddleware',
    'django.middleware.clickjacking.XFrameOptionsMiddleware',
]

ROOT_URLCONF = 'banking_platform.urls'

TEMPLATES = [
    {
        'BACKEND': 'django.template.backends.django.DjangoTemplates',
        'DIRS': [BASE_DIR / 'templates'],
        'APP_DIRS': True,
        'OPTIONS': {
            'context_processors': [
                'django.template.context_processors.debug',
                'django.template.context_processors.request',
                'django.contrib.auth.context_processors.auth',
                'django.contrib.messages.context_processors.messages',
            ],
        },
    },
]

WSGI_APPLICATION = 'banking_platform.wsgi.application'

DATABASES = {
    'default': {
        'ENGINE': 'django.db.backends.postgresql',
        'NAME': os.getenv('DB_NAME', 'postgres'),
        'USER': os.getenv('DB_USER', 'postgres'),
        'PASSWORD': os.getenv('DB_PASSWORD', ''),
        'HOST': os.getenv('DB_HOST', 'localhost'),
        'PORT': os.getenv('DB_PORT', '5432'),
        'OPTIONS': {'sslmode': 'require'},
        'CONN_MAX_AGE': 0,                    # Serverless : pas de connexions persistantes
        'DISABLE_SERVER_SIDE_CURSORS': True,  # Requis pour le pooler Supabase (mode transaction)
    }
}

AUTH_PASSWORD_VALIDATORS = [
    {'NAME': 'django.contrib.auth.password_validation.UserAttributeSimilarityValidator'},
    {'NAME': 'django.contrib.auth.password_validation.MinimumLengthValidator', 'OPTIONS': {'min_length': 8}},
    {'NAME': 'django.contrib.auth.password_validation.CommonPasswordValidator'},
    {'NAME': 'django.contrib.auth.password_validation.NumericPasswordValidator'},
]

LANGUAGE_CODE = 'fr-fr'
TIME_ZONE = 'Europe/Paris'
USE_I18N = True
USE_TZ = True

STATIC_URL = '/static/'
STATICFILES_DIRS = [BASE_DIR / 'static']
STATIC_ROOT = BASE_DIR / 'staticfiles'
STATICFILES_STORAGE = 'whitenoise.storage.CompressedManifestStaticFilesStorage'

MEDIA_URL = '/media/'
MEDIA_ROOT = BASE_DIR / 'media'

# ── Storage fichiers media — Supabase Storage (S3) en production ──────────
_supabase_ref = 'xdlaoyyokxsetknjvaru'
_storage_key = os.getenv('STORAGE_ACCESS_KEY', '')
if not DEBUG and _storage_key:
    DEFAULT_FILE_STORAGE = 'storages.backends.s3boto3.S3Boto3Storage'
    AWS_ACCESS_KEY_ID = _storage_key
    AWS_SECRET_ACCESS_KEY = os.getenv('STORAGE_SECRET_KEY', '')
    AWS_STORAGE_BUCKET_NAME = os.getenv('STORAGE_BUCKET_NAME', 'media')
    AWS_S3_ENDPOINT_URL = f'https://{_supabase_ref}.supabase.co/storage/v1/s3'
    AWS_S3_REGION_NAME = 'eu-west-1'
    AWS_DEFAULT_ACL = 'public-read'
    AWS_S3_FILE_OVERWRITE = False
    AWS_QUERYSTRING_AUTH = False
    MEDIA_URL = f'https://{_supabase_ref}.supabase.co/storage/v1/object/public/{os.getenv("STORAGE_BUCKET_NAME", "media")}/'

DEFAULT_AUTO_FIELD = 'django.db.models.BigAutoField'

AUTH_USER_MODEL = 'accounts.BankUser'

# ── Email ──────────────────────────────────────────────────────────────────
POSTMARK_API_KEY = os.getenv('POSTMARK_API_KEY', '')
DEFAULT_FROM_EMAIL = os.getenv('DEFAULT_FROM_EMAIL', 'noreply@bank.com')
SITE_URL = os.getenv('SITE_URL', 'http://localhost:8000')

# ── Chiffrement champs sensibles (Fernet) ─────────────────────────────────
FIELD_ENCRYPTION_KEY = os.getenv('FIELD_ENCRYPTION_KEY', '')

# ── Session ────────────────────────────────────────────────────────────────
SESSION_COOKIE_AGE = 3600          # 1h d'inactivité
SESSION_EXPIRE_AT_BROWSER_CLOSE = True
SESSION_COOKIE_HTTPONLY = True
SESSION_COOKIE_SAMESITE = 'Lax'

# ── Sécurité production ────────────────────────────────────────────────────
if not DEBUG:
    # Vercel termine le SSL en amont — Django lit le header X-Forwarded-Proto
    SECURE_PROXY_SSL_HEADER = ('HTTP_X_FORWARDED_PROTO', 'https')
    SECURE_SSL_REDIRECT = True
    SECURE_HSTS_SECONDS = 31536000
    SECURE_HSTS_INCLUDE_SUBDOMAINS = True
    SECURE_HSTS_PRELOAD = True
    SESSION_COOKIE_SECURE = True
    CSRF_COOKIE_SECURE = True
    SECURE_BROWSER_XSS_FILTER = True
    SECURE_CONTENT_TYPE_NOSNIFF = True
    X_FRAME_OPTIONS = 'DENY'

# ── Logging ────────────────────────────────────────────────────────────────
_log_handlers = ['console']
_handlers_config: dict = {
    'console': {
        'class': 'logging.StreamHandler',
        'formatter': 'verbose',
    },
}

if DEBUG:
    _log_handlers.append('file')
    _handlers_config['file'] = {
        'class': 'logging.handlers.RotatingFileHandler',
        'filename': BASE_DIR / 'logs' / 'banking.log',
        'maxBytes': 10 * 1024 * 1024,
        'backupCount': 5,
        'formatter': 'verbose',
    }

LOGGING = {
    'version': 1,
    'disable_existing_loggers': False,
    'formatters': {
        'verbose': {
            'format': '[{asctime}] {levelname} {name} — {message}',
            'style': '{',
        },
    },
    'handlers': _handlers_config,
    'loggers': {
        'banking': {
            'handlers': _log_handlers,
            'level': 'INFO',
            'propagate': False,
        },
        'django.security': {
            'handlers': _log_handlers,
            'level': 'WARNING',
        },
    },
}

# ── Cache (local memory pour le dev) ──────────────────────────────────────
CACHES = {
    'default': {
        'BACKEND': 'django.core.cache.backends.locmem.LocMemCache',
        'LOCATION': 'banking-platform',
    }
}
