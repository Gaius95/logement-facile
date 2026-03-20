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

### Vérification d’identité (KYC)

| Variable | Rôle |
|----------|------|
| `ADMIN_EMAILS` | Emails autorisés à valider les dossiers (séparés par des virgules), ex. `toi@mail.com,admin@mail.com` |
| `KYC_MAX_FILE_MB` | Taille max par fichier image (défaut `5`) |
| `MAX_UPLOAD_MB` | Taille max de la requête HTTP pour le formulaire (défaut `16`) |

- **Nouveaux comptes** : après inscription, ils doivent envoyer **pièce d’identité + selfie** ; la publication n’est possible qu’après **approbation** (manuelle via `/admin/kyc` pour les emails listés dans `ADMIN_EMAILS`).
- **Comptes déjà existants** (`kyc_status` vide en base) : **non bloqués** (comportement legacy).
- **Stockage fichiers** : dossier `uploads/kyc/` sur le serveur. **Sur Render**, le disque est **éphémère** : les fichiers peuvent disparaître au redémarrage. Pour une prod sérieuse, prévoir **S3 / Cloudflare R2 / autre stockage objet** + URL signées.
- **« Face ID » automatique** (comparaison biométrique document ↔ selfie) : non inclus ; il faut un **prestataire** (Onfido, Sumsub, Smile ID pour l’Afrique, etc.). Le flux actuel permet la **vérification humaine** par ton équipe.

### SMS (codes de vérification téléphone)

**Sans configuration SMS, aucun SMS n’est envoyé** : l’app affiche alors « envoi SMS indisponible » en production (le code n’est pas affiché à l’écran pour des raisons de sécurité).

Configure **au moins une** des options suivantes sur Render (**Environment**) :

#### Option A — Twilio (simple)

| Variable | Rôle |
|----------|------|
| `TWILIO_ACCOUNT_SID` | Identifiant du compte Twilio |
| `TWILIO_AUTH_TOKEN` | Jeton API |
| `TWILIO_FROM` | Numéro Twilio expéditeur (format E.164, ex. `+1234567890`) |

*(Alias accepté : `TWILIO_PHONE_NUMBER` à la place de `TWILIO_FROM`.)*

- Crée un compte sur [twilio.com](https://www.twilio.com), achète un numéro capable d’envoyer des SMS.
- Pour la Guinée (`+224`), vérifie chez Twilio la **couverture** et les règles (parfois un numéro local ou un profil business est requis).

#### Option B — Webhook HTTP générique

**Important** : ne définis **pas** les variables `TWILIO_*` si tu veux utiliser uniquement ce webhook (sinon Twilio est essayé en premier).

Sur Render (**Environment**), mets :

| Variable | Obligatoire | Valeur |
|----------|-------------|--------|
| `SMS_DISPATCH_URL` | **Oui** | L’URL **HTTPS** de ton endpoint (ex. `https://ton-serveur.com/api/send-sms` ou URL fournie par Make / Zapier / n8n). |
| `SMS_DISPATCH_TOKEN` | Non | Un secret que **toi** tu choisis ; la même valeur doit être vérifiée côté webhook. Si tu la remplis, l’app envoie l’en-tête ci-dessous. |

**Ce que Logement Facile envoie** (à chaque code SMS) :

- **Méthode** : `POST`
- **En-têtes** : `Content-Type: application/json`, `User-Agent: LogementFacile/1.0`  
  + si `SMS_DISPATCH_TOKEN` est défini : `Authorization: Bearer <la même valeur que sur Render>`
- **Corps JSON** (exemple) :
  ```json
  {
    "to": "+224621234567",
    "message": "Logement Facile - votre code de verification est: 123456. Expire dans 10 min."
  }
  ```

**Ce que ton endpoint doit faire** :

1. Lire `to` et `message` depuis le JSON.
2. Appeler ton fournisseur SMS (API opérateur, service local, module Make « SMS », etc.).
3. Répondre avec un code HTTP **200–299** si l’envoi est OK ; sinon l’app considère que le SMS a échoué.

**Test manuel** (remplace l’URL et le token) :

```bash
curl -sS -X POST "https://TON_WEBHOOK_URL" \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer TON_TOKEN_SECRET" \
  -d "{\"to\":\"+224621234567\",\"message\":\"Test Logement Facile\"}"
```

Si ton outil (Make, etc.) n’accepte pas `Bearer`, laisse `SMS_DISPATCH_TOKEN` **vide** et sécurise l’URL (secret dans le chemin ou IP allowlist).

#### Autres

| Variable | Défaut | Rôle |
|----------|--------|------|
| `SMS_CODE_TTL_MINUTES` | `10` | Durée de validité du code |

**Test** : après `git push` + redéployement Render, inscris-toi avec un numéro au format international **`+224…`** et vérifie les exécutions de ton webhook (ou les logs Twilio si option A).

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
