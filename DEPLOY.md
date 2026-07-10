# Déploiement — checklist

## Migrations de base de données

Vercel n'exécute **jamais** `python manage.py migrate` automatiquement (ni au
build, ni au runtime). Après toute modification d'un modèle Django, il faut
lancer les migrations manuellement contre la base de production, avant ou
juste après le déploiement du code :

```bash
vercel link                # une seule fois, si le projet n'est pas déjà lié
vercel env pull .env.local # récupère les vraies variables d'env de production
python manage.py migrate   # applique les migrations sur la base de prod
```

Sans cette étape, un déploiement contenant une nouvelle migration plante en
production avec des erreurs "column does not exist" dès qu'une vue touche le
champ concerné.

## Variables d'environnement requises (Production)

| Variable | Rôle | Valeur pour ce projet |
|---|---|---|
| `SECRET_KEY` | clé Django (obligatoire) | — |
| `DEBUG` | doit valoir `False` en production | `False` |
| `ALLOWED_HOSTS` | doit inclure le domaine du site | `royalacces.com,www.royalacces.com` |
| `DB_NAME`, `DB_USER`, `DB_PASSWORD`, `DB_HOST`, `DB_PORT` | connexion PostgreSQL (Supabase) | — |
| `FIELD_ENCRYPTION_KEY` | clé Fernet — obligatoire, sinon le boot plante volontairement | — |
| `SUPABASE_URL`, `SUPABASE_SERVICE_KEY`, `STORAGE_BUCKET_NAME` | stockage des fichiers (logos, cachets) | — |
| `SITE_URL` | URL publique utilisée dans les liens des emails | `https://www.royalacces.com` |
| `DEFAULT_FROM_EMAIL` | adresse expéditrice — doit être identique à `EMAIL_HOST_USER` (les serveurs mutualisés type LWS rejettent un "From" qui ne correspond pas au compte authentifié) | `eservice@virement.net` |
| `EMAIL_HOST` | hôte SMTP | `mail.virement.net` (fallback : `mail16.lwspanel.com`) |
| `EMAIL_PORT` | port SMTP | `465` |
| `EMAIL_USE_SSL` | SSL implicite (port 465) | `True` |
| `EMAIL_USE_TLS` | STARTTLS (port 587) — ignoré si `EMAIL_USE_SSL=True` | `False` |
| `EMAIL_HOST_USER` | identifiant SMTP (boîte mail LWS) | `eservice@virement.net` |
| `EMAIL_HOST_PASSWORD` | mot de passe de la boîte mail LWS | — (secret, à saisir uniquement dans Vercel) |

Email actuellement utilisé pour l'envoi : boîte pro **`eservice@virement.net`**
hébergée sur LWS (`mail.virement.net`, port 465 SSL). Le code est
provider-agnostique (backend SMTP standard Django) — changer de fournisseur
plus tard ne nécessite que de changer ces variables, jamais le code.

**`SENDGRID_API_KEY` et `POSTMARK_API_KEY` ne sont plus utilisées** — le
projet n'utilise plus SendGrid ni Render/Postmark. Ces variables peuvent être
supprimées du dashboard Vercel si elles y sont encore présentes.

## vercel.json

Le fichier `vercel.json` a été modernisé pour suivre la configuration
officiellement documentée par Vercel pour Django (détection automatique de
`manage.py` / `WSGI_APPLICATION`, `collectstatic` automatique au build).
**Tester ce changement via une Preview Deployment avant de le laisser passer
en production**, puisqu'il remplace l'ancien routage `builds`/`routes`
(`api/index.py` a été supprimé, devenu inutile).
