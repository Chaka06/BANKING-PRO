"""
Chiffrement symétrique Fernet pour les champs sensibles en base de données.
Utilisé pour stocker plain_password de manière sécurisée (non lisible directement en DB).
Requiert FIELD_ENCRYPTION_KEY dans les variables d'environnement.
"""
from cryptography.fernet import Fernet, InvalidToken
from django.conf import settings


def _get_fernet() -> Fernet | None:
    key = getattr(settings, 'FIELD_ENCRYPTION_KEY', '')
    if not key:
        return None
    return Fernet(key.encode() if isinstance(key, str) else key)


def encrypt_field(value: str) -> str:
    """Chiffre une valeur texte. Retourne la valeur en clair si la clé est absente (dev)."""
    if not value:
        return ''
    fernet = _get_fernet()
    if fernet is None:
        return value
    return fernet.encrypt(value.encode()).decode()


def decrypt_field(token: str) -> str:
    """Déchiffre un token Fernet. Retourne '(réinitialisé)' si échec."""
    if not token:
        return ''
    fernet = _get_fernet()
    if fernet is None:
        return token  # clé absente en dev → valeur déjà en clair
    try:
        return fernet.decrypt(token.encode()).decode()
    except (InvalidToken, Exception):
        return '(réinitialisé)'
