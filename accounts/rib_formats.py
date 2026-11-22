"""
Formats de RIB / IBAN par pays.

Chaque pays a une structure (BBAN) décrite par une suite de segments :
    <champ><longueur><jeu de caractères>
  champ : b = code banque, g = code guichet / agence, c = n° de compte, k = clé
  jeu   : n = chiffres, a = lettres majuscules, c = alphanumérique,
          i = code ISO du pays (ex : « SN » dans les RIB UEMOA)

Plusieurs segments peuvent alimenter le même champ (ex : HU a deux clés).

Stockage (BankAccount.rib) : CC + 2 chiffres de contrôle ISO 13616 (mod 97)
+ BBAN, pour TOUS les pays — c'est un IBAN valide pour les pays qui utilisent
l'IBAN, et un identifiant international de même forme pour les autres
(États-Unis, Chine, Japon…), dont le BBAN suit le format bancaire national.

Les anciens RIB (27 caractères au format français, quel que soit le pays)
restent lisibles : si la longueur ne correspond pas au format du pays, on les
découpe à l'ancienne (5/5/11/2).
"""
import hashlib
import re
import secrets
import string

from django.utils.translation import gettext_lazy as _

# ── Pays utilisant l'IBAN (registre SWIFT + IBAN nationaux africains) ──────
IBAN_FORMATS = {
    'AD': 'b4n g4n c12c',
    'AE': 'b3n c16n',
    'AL': 'b3n g4n k1n c16c',
    'AO': 'b4n g4n c11n k2n',
    'AT': 'b5n c11n',
    'AZ': 'b4a c20c',
    'BA': 'b3n g3n c8n k2n',
    'BE': 'b3n c7n k2n',
    'BF': 'b2i b3n g5n c12n k2n',
    'BG': 'b4a g4n c10c',
    'BH': 'b4a c14c',
    'BI': 'b5n g5n c11n k2n',
    'BJ': 'b2i b3n g5n c12n k2n',
    'BR': 'b8n g5n c10n c1a c1c',
    'BY': 'b4c g4n c16c',
    'CF': 'b5n g5n c11n k2n',
    'CG': 'b5n g5n c11n k2n',
    'CH': 'b5n c12c',
    'CI': 'b2i b3n g5n c12n k2n',
    'CM': 'b5n g5n c11n k2n',
    'CR': 'b4n c14n',
    'CV': 'b4n g4n c11n k2n',
    'CY': 'b3n g5n c16c',
    'CZ': 'b4n c16n',
    'DE': 'b8n c10n',
    'DJ': 'b5n g5n c11n k2n',
    'DK': 'b4n c9n k1n',
    'DO': 'b4c c20n',
    'DZ': 'b3n g5n c12n k2n',
    'EE': 'b2n c14n',
    'EG': 'b4n g4n c17n',
    'ES': 'b4n g4n k2n c10n',
    'FI': 'b3n c11n',
    'FR': 'b5n g5n c11c k2n',
    'GA': 'b5n g5n c11n k2n',
    'GB': 'b4a g6n c8n',
    'GE': 'b2a c16n',
    'GQ': 'b5n g5n c11n k2n',
    'GR': 'b3n g4n c16c',
    'GT': 'b4c c20c',
    'GW': 'b2i b2n g5n c10n k2n',
    'HN': 'b4a c20n',
    'HR': 'b7n c10n',
    'HU': 'b3n g4n k1n c15n k1n',
    'IE': 'b4a g6n c8n',
    'IL': 'b3n g3n c13n',
    'IQ': 'b4a g3n c12n',
    'IR': 'b4n c18n',
    'IS': 'b4n c18n',
    'IT': 'k1a b5n g5n c12c',
    'JO': 'b4a g4n c18c',
    'KM': 'b5n g5n c11n k2n',
    'KW': 'b4a c22c',
    'KZ': 'b3n c13c',
    'LB': 'b4n c20c',
    'LC': 'b4a c24c',
    'LI': 'b5n c12c',
    'LT': 'b5n c11n',
    'LU': 'b3n c13c',
    'LV': 'b4a c13c',
    'LY': 'b3n g3n c15n',
    'MA': 'b3n g3n c16n k2n',
    'MC': 'b5n g5n c11c k2n',
    'MD': 'b2c c18c',
    'ME': 'b3n c13n k2n',
    'MG': 'b5n g5n c11n k2n',
    'MK': 'b3n c10c k2n',
    'ML': 'b2i b3n g5n c12n k2n',
    'MN': 'b4n c12n',
    'MR': 'b5n g5n c11n k2n',
    'MT': 'b4a g5n c18c',
    'MU': 'b4a b2n g2n c12n c3n c3a',
    'MZ': 'b4n g4n c11n k2n',
    'NE': 'b2i b3n g5n c12n k2n',
    'NI': 'b4a c20n',
    'NL': 'b4a c10n',
    'NO': 'b4n c6n k1n',
    'OM': 'b3n c16c',
    'PK': 'b4a c16c',
    'PL': 'b3n g4n k1n c16n',
    'PS': 'b4a c21c',
    'PT': 'b4n g4n c11n k2n',
    'QA': 'b4a c21c',
    'RO': 'b4a c16c',
    'RS': 'b3n c13n k2n',
    'RU': 'b9n g5n c15c',
    'SA': 'b2n c18c',
    'SC': 'b4a b2n g2n c16n c3a',
    'SD': 'b2n c12n',
    'SE': 'b3n c17n',
    'SI': 'b5n c8n k2n',
    'SK': 'b4n c16n',
    'SM': 'k1a b5n g5n c12c',
    'SN': 'b2i b3n g5n c12n k2n',
    'SO': 'b4n g3n c12n',
    'ST': 'b4n g4n c11n k2n',
    'SV': 'b4a c20n',
    'TD': 'b5n g5n c11n k2n',
    'TG': 'b2i b3n g5n c12n k2n',
    'TL': 'b3n c14n k2n',
    'TN': 'b2n g3n c13n k2n',
    'TR': 'b5n c17c',
    'UA': 'b6n c19c',
    'VA': 'b3n c15n',
    'XK': 'b4n c10n k2n',
    'YE': 'b4a g4n c18c',
}

# ── Pays sans IBAN : format bancaire national ──────────────────────────────
NATIONAL_FORMATS = {
    'US': 'b9n c12n',            # ABA routing number + account number
    'CA': 'g5n b3n c12n',        # transit + institution + compte
    'AU': 'b6n c9n',             # BSB + compte
    'NZ': 'b2n g4n c7n c3n',     # banque + agence + compte + suffixe
    'JP': 'b4n g3n c7n',
    'CN': 'c19n',
    'IN': 'b4a b1n b6c c14n',    # IFSC (4 lettres + 0 + 6) + compte
    'HK': 'b3n g3n c9n',
    'MO': 'b3n c13n',
    'SG': 'b4n g3n c10n',
    'KR': 'b3n c14n',
    'TW': 'b3n g4n c14n',
    'MX': 'b3n g3n c11n k1n',    # CLABE (18 chiffres)
    'AR': 'b3n g4n k1n c13n k1n',  # CBU (22 chiffres)
    'ZA': 'g6n c11n',            # branch code + compte
    'NG': 'b3n c10n',            # code banque + NUBAN
    'GH': 'b3n g3n c13n',
    'KE': 'b2n g3n c13n',
    'CO': 'b4n c11n',
    'PE': 'b3n g3n c12n k2n',    # CCI (20 chiffres)
    'CL': 'b3n c12n',
    'TH': 'b3n g3n c10n',
    'MY': 'b4n c14n',
    'ID': 'b3n c13n',
    'PH': 'b4n c12n',
    'VN': 'b3n c14n',
}

DEFAULT_FORMAT = 'b4n g4n c12n'

# Pays dont la clé finale est une clé RIB à la française (mod 97).
FRENCH_RIB_KEY = {
    'FR', 'MC', 'BF', 'BJ', 'CI', 'ML', 'NE', 'SN', 'TG', 'GW',
    'CF', 'CG', 'CM', 'GA', 'GQ', 'TD', 'MG', 'KM', 'MR', 'BI', 'DJ', 'MA', 'DZ',
}

# Libellés des composants
DEFAULT_LABELS = {
    'b': _('Code banque'),
    'g': _('Code guichet'),
    'c': _('N° de compte'),
    'k': _('Clé de contrôle'),
}
LABEL_OVERRIDES = {
    'US': {'b': _('Routing number (ABA)'), 'c': _('Account number')},
    'CA': {'b': _('Institution'), 'g': _('Transit')},
    'AU': {'b': 'BSB'},
    'IN': {'b': 'IFSC'},
    'GB': {'g': _('Sort code')},
    'IE': {'g': _('Sort code')},
    'ZA': {'g': _('Branch code')},
    'IT': {'k': 'CIN'},
    'SM': {'k': 'CIN'},
    'ES': {'g': _('Code agence'), 'k': 'DC'},
    'PT': {'g': _('Code agence')},
    'JP': {'g': _('Code agence')},
    'HK': {'g': _('Code agence')},
    'SG': {'g': _('Code agence')},
    'TW': {'g': _('Code agence')},
    'MX': {'c': _('N° de compte (CLABE)')},
    'AR': {'c': _('N° de compte (CBU)')},
}

FIELD_ORDER = ('b', 'g', 'c', 'k')
_TOKEN = re.compile(r'^([bgck])(\d+)([naci])$')
_CHARSETS = {
    'n': string.digits,
    'a': string.ascii_uppercase,
    'c': string.digits + string.ascii_uppercase,
}


def parse_spec(spec):
    tokens = []
    for raw in spec.split():
        m = _TOKEN.match(raw)
        if not m:
            raise ValueError(f"Segment de format invalide : {raw}")
        tokens.append((m.group(1), int(m.group(2)), m.group(3)))
    return tokens


def get_spec(iso):
    return IBAN_FORMATS.get(iso) or NATIONAL_FORMATS.get(iso) or DEFAULT_FORMAT


def get_tokens(iso):
    return parse_spec(get_spec(iso))


def uses_iban(iso):
    return iso in IBAN_FORMATS


def bban_length(iso):
    return sum(length for _f, length, _c in get_tokens(iso))


def total_length(iso):
    return 4 + bban_length(iso)


def field_lengths(iso):
    """{champ: longueur totale} pour les champs présents dans ce pays."""
    out = {}
    for f, length, _c in get_tokens(iso):
        out[f] = out.get(f, 0) + length
    return out


def field_label(iso, field):
    return LABEL_OVERRIDES.get(iso, {}).get(field) or (
        _('Clé RIB') if field == 'k' and iso in FRENCH_RIB_KEY else DEFAULT_LABELS[field]
    )


# ── Calculs de contrôle ────────────────────────────────────────────────────

def _letters_to_digits(s):
    return ''.join(str(int(ch, 36)) for ch in s)


def iban_check_digits(iso, bban):
    """Chiffres de contrôle ISO 13616 (mod 97)."""
    numeric = _letters_to_digits(bban + iso + '00')
    return f"{98 - int(numeric) % 97:02d}"


def is_valid_iban(iban):
    iban = iban.replace(' ', '').upper()
    if len(iban) < 5 or not iban.isalnum():
        return False
    return int(_letters_to_digits(iban[4:] + iban[:4])) % 97 == 1


_RIB_LETTERS = {}
for _digit, _letters in enumerate(['', 'AJ', 'BKS', 'CLT', 'DMU', 'ENV', 'FOW', 'GPX', 'HQY', 'IRZ']):
    for _l in _letters:
        _RIB_LETTERS[_l] = str(_digit)


def _rib_digits(s):
    return ''.join(_RIB_LETTERS.get(ch, ch) for ch in s.upper())


def french_rib_key(banque, guichet, compte):
    """Clé RIB française : 97 - ((89·banque + 15·guichet + 3·compte) mod 97)."""
    b, g, c = int(_rib_digits(banque) or 0), int(_rib_digits(guichet) or 0), int(_rib_digits(compte) or 0)
    return f"{97 - (89 * b + 15 * g + 3 * c) % 97:02d}"


def belgian_key(banque, compte):
    r = int(banque + compte) % 97
    return f"{r or 97:02d}"


def aba_check_digit(first8):
    weights = [3, 7, 1] * 3
    total = sum(int(d) * w for d, w in zip(first8, weights))
    return str((10 - total % 10) % 10)


# ── Composition / décomposition ────────────────────────────────────────────

def _random(length, charset, iso):
    if charset == 'i':
        return iso[:length]
    if charset == 'c':
        # Alphanumérique autorisé, mais les comptes réels sont quasi toujours numériques
        charset = 'n'
    return ''.join(secrets.choice(_CHARSETS[charset]) for _ in range(length))


def _deterministic(seed, length, charset, iso):
    """Valeur stable dérivée d'une graine (code banque identique pour tous les
    comptes d'une même banque dans un même pays)."""
    if charset == 'i':
        return iso[:length]
    chars = _CHARSETS[charset]
    digest = hashlib.sha256(seed.encode()).digest()
    out, i = [], 0
    while len(out) < length:
        if i >= len(digest):
            digest = hashlib.sha256(digest).digest()
            i = 0
        out.append(chars[digest[i] % len(chars)])
        i += 1
    return ''.join(out)


def compute_key(iso, fields):
    """Clé recalculée quand l'algorithme national est connu, sinon None."""
    k_len = field_lengths(iso).get('k', 0)
    if not k_len:
        return None
    if iso in FRENCH_RIB_KEY and k_len == 2:
        return french_rib_key(fields.get('b', ''), fields.get('g', ''), fields.get('c', ''))
    if iso == 'BE':
        return belgian_key(fields.get('b', ''), fields.get('c', ''))
    return None


def assemble(iso, fields):
    """Recompose l'identifiant complet (CC + contrôle + BBAN) à partir des
    valeurs par champ, en respectant l'ordre des segments du pays."""
    remaining = dict(fields)
    bban = ''
    for f, length, _c in get_tokens(iso):
        value = remaining.get(f, '')
        bban += value[:length]
        remaining[f] = value[length:]
    return f"{iso}{iban_check_digits(iso, bban)}{bban}"


def split(iso, rib):
    """Décompose un RIB stocké en {champ: valeur}. Retourne None si le RIB
    ne suit pas le format du pays (ancien format)."""
    rib = (rib or '').replace(' ', '').upper()
    if not rib.startswith(iso) or len(rib) != total_length(iso):
        return None
    pos = 4
    fields = {f: '' for f in field_lengths(iso)}
    for f, length, charset in get_tokens(iso):
        segment = rib[pos:pos + length]
        # Chaque segment doit respecter son jeu de caractères : distingue un
        # ancien RIB de même longueur (ex : ancien RIB italien de 27 car.,
        # chiffre là où le nouveau format attend la lettre CIN).
        allowed = iso if charset == 'i' else _CHARSETS[charset]
        if charset == 'i' and segment != iso[:length]:
            return None
        if any(ch not in allowed for ch in segment):
            return None
        fields[f] += segment
        pos += length
    return fields


def split_legacy(rib):
    rib = rib or ''
    return {'b': rib[4:9], 'g': rib[9:14], 'c': rib[14:25], 'k': rib[25:27]}


def components(iso, rib):
    """Liste ordonnée [(champ, libellé, valeur)] pour l'affichage (PDF, tableau
    de bord, admin). Gère les RIB à l'ancien format."""
    fields = split(iso, rib)
    if fields is None:
        legacy = split_legacy(rib)
        labels = {'b': _('Code banque'), 'g': _('Code guichet'), 'c': _('N° de compte'), 'k': _('Clé RIB')}
        return [(f, labels[f], legacy[f]) for f in FIELD_ORDER if legacy[f]]
    return [(f, field_label(iso, f), fields[f]) for f in FIELD_ORDER if f in fields]


def generate(iso, bank_code, keep=None):
    """Génère un nouvel identifiant pour le pays.
    - code banque : stable par (banque, pays) ; pour la France, le code
      banque réel de l'établissement s'il est numérique ;
    - guichet et compte : aléatoires ;
    - clé : calculée si l'algorithme est connu, aléatoire sinon ;
    - keep : champs à conserver (compte secondaire : tout sauf le n° de compte).
    """
    keep = keep or {}
    lengths = field_lengths(iso)
    tokens = get_tokens(iso)
    fields = {}
    for f in lengths:
        if f in keep:
            fields[f] = keep[f]
            continue
        value = ''
        for idx, (tf, length, charset) in enumerate(tokens):
            if tf != f:
                continue
            if f == 'b':
                code = (bank_code or '').strip().upper()
                if charset == 'n' and code.isdigit() and len(code) <= length and iso in ('FR', 'MC'):
                    value += code.zfill(length)
                else:
                    value += _deterministic(f"{code}:{iso}:{idx}", length, charset, iso)
            else:
                value += _random(length, charset, iso)
        fields[f] = value

    if iso == 'US':
        fields['b'] = fields['b'][:8] + aba_check_digit(fields['b'][:8])
    if iso == 'IN':
        fields['b'] = fields['b'][:4] + '0' + fields['b'][5:]
    if iso == 'MU':   # … + 3 chiffres réservés « 000 » + devise
        fields['c'] = fields['c'][:12] + '000MUR'
    if iso == 'SC':   # … + devise
        fields['c'] = fields['c'][:16] + 'SCR'

    key = compute_key(iso, fields)
    if key is not None:
        fields['k'] = key
    return assemble(iso, fields)
