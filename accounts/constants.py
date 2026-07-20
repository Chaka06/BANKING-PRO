COUNTRY_PREFIXES = {
    'France': 'FR',
    'Belgique': 'BE',
    'Italie': 'IT',
    'Espagne': 'ES',
    'Allemagne': 'DE',
    'Portugal': 'PT',
    'Suisse': 'CH',
    'Luxembourg': 'LU',
    'Pays-Bas': 'NL',
    'Royaume-Uni': 'GB',
    'États-Unis': 'US',
    'Canada': 'CA',
    'Maroc': 'MA',
    'Sénégal': 'SN',
    "Côte d'Ivoire": 'CI',
    'Cameroun': 'CM',
    'Algérie': 'DZ',
    'Tunisie': 'TN',
}

COUNTRY_CURRENCIES = {
    'France': 'EUR',
    'Belgique': 'EUR',
    'Italie': 'EUR',
    'Espagne': 'EUR',
    'Allemagne': 'EUR',
    'Portugal': 'EUR',
    'Luxembourg': 'EUR',
    'Pays-Bas': 'EUR',
    'Suisse': 'CHF',
    'Royaume-Uni': 'GBP',
    'États-Unis': 'USD',
    'Canada': 'CAD',
    'Maroc': 'MAD',
    'Sénégal': 'XOF',
    "Côte d'Ivoire": 'XOF',
    'Cameroun': 'XAF',
    'Algérie': 'DZD',
    'Tunisie': 'TND',
}

COUNTRY_LIST = sorted(COUNTRY_PREFIXES.keys())

CURRENCY_LIST = sorted(set(COUNTRY_CURRENCIES.values()))
