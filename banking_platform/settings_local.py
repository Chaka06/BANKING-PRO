"""
Settings de développement local — remplace PostgreSQL par SQLite.
Utilisation : python manage.py <commande> --settings=banking_platform.settings_local
"""
from .settings import *

DATABASES = {
    'default': {
        'ENGINE': 'django.db.backends.sqlite3',
        'NAME': BASE_DIR / 'db_local.sqlite3',
    }
}

# Pas besoin de SSL local
# Pas de cache avancé
CACHES = {
    'default': {
        'BACKEND': 'django.core.cache.backends.locmem.LocMemCache',
    }
}
