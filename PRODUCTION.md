# Logement Facile — guide production (sécurité & montée en charge)

Ce document résume ce qui est en place dans le code et ce qu’il faut configurer pour un déploiement **professionnel, sécurisé et scalable**.

## Variables d’environnement obligatoires (Render / VPS)

| Variable | Rôle |
|----------|------|
| `SECRET_KEY` | **Obligatoire en production** (longue chaîne aléatoire). Génération : `openssl rand -hex 32` |
| `DATABASE_URL` | PostgreSQL en prod (Render fournit l’URL). Ne pas utiliser SQLite en multi-instances. |
| `RENDER=true` | Détecté automatiquement par Render ; active le mode production (cookies sécurisés, etc.). |

Optionnel mais recommandé pour la charge :

| Variable | Défaut | Rôle |
|----------|--------|------|
| `WEB_CONCURRENCY` | auto (2–4) | Nombre de workers Gunicorn |
| `GUNICORN_THREADS` | `4` | Threads par worker (`gthread`) |
| `GUNICORN_TIMEOUT` | `120` | Timeout requêtes (paiements / APIs) |
| `DB_POOL_SIZE` | `5` | Taille du pool SQLAlchemy (PostgreSQL) |
| `DB_MAX_OVERFLOW` | `10` | Connexions supplémentaires au-delà du pool |
| `DB_POOL_RECYCLE` | `280` | Recycler les connexions avant timeout PG |

Clés paiement / providers : selon ta config actuelle (LengoPay, CinetPay, Stripe).

## Sécurité déjà intégrée

- **CSRF** (Flask-WTF) sur tous les formulaires POST utilisateurs ; **exempt** uniquement pour les webhooks externes (Stripe, CinetPay, LengoPay).
- **Cookies de session** : `HttpOnly`, `SameSite=Lax`, `Secure` en HTTPS (production).
- **En-têtes HTTP** : `X-Content-Type-Options`, `X-Frame-Options`, `Referrer-Policy`, `Permissions-Policy`, **HSTS** en production.
- **`SECRET_KEY`** : refus de démarrer en production si absent ou valeur par défaut.
- **Fichiers statiques** `/conakry-media/` : noms de fichiers validés (pas de `..`).
- **Route `/cursor-assets/`** : désactivée en production (développement local uniquement).
- **Mots de passe** : minimum **8 caractères** à l’inscription.

## Scalabilité & observabilité

- **Gunicorn** : `gunicorn.conf.py` avec workers × threads, timeouts, `max_requests` (limitation fuites mémoire).
- **Sondes** :
  - `GET /health` — liveness (pas de DB).
  - `GET /health/ready` — readiness (ping SQL `SELECT 1`).
- **PostgreSQL** : pool avec `pool_pre_ping` et paramètres ajustables.

## Prochaines étapes possibles (niveau “grande capacité”)

1. **CDN** pour `static images/` et assets (Cloudflare, S3 + CloudFront, etc.).
2. **Redis** + sessions serveur-side si plusieurs régions / besoin de déconnexion centralisée.
3. **Flask-Migrate (Alembic)** pour versions de schéma DB sans `create_all` manuel.
4. **Rate limiting** (Flask-Limiter) sur `/connexion`, `/inscription`, `/contact`.
5. **Journalisation structurée** (JSON) vers un agrégateur (Datadog, Grafana Loki, etc.).
6. **WAF / pare-feu applicatif** en frontal (Cloudflare Pro, etc.).

## Déploiement Render

- **Start Command** : `gunicorn -c gunicorn.conf.py wsgi:app` (déjà dans le `Procfile`).
- Après changement de dépendances : `pip install -r requirements.txt` puis redéployer.
