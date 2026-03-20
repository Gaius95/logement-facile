# SMS Dispatcher (option B — webhook)

Petit service séparé : **Logement Facile** appelle cette URL (`SMS_DISPATCH_URL`), ce service envoie le SMS (Twilio, ou relais vers une autre API).

## Fichiers de ce dossier

| Fichier | Rôle |
|---------|------|
| `app.py` | Application Flask (`POST /dispatch`, `GET /health`) |
| `wsgi.py` | Point d’entrée Gunicorn |
| `requirements.txt` | Dépendances Python |
| `Procfile` | Commande de démarrage sur Render |
| `README.md` | Ce guide |

## Déploiement Render (2ᵉ service)

1. Même dépôt Git que Logement Facile.
2. **New +** → **Web Service** → même repo.
3. **Root Directory** : `sms-dispatcher`
4. **Build** : `pip install -r requirements.txt`
5. **Start** : laisser le `Procfile` (ou `gunicorn --bind 0.0.0.0:$PORT --workers 1 --threads 2 --timeout 60 wsgi:app`)
6. **URL obtenue** : ex. `https://sms-dispatcher-xxxx.onrender.com`

## Variables d’environnement (service dispatcher)

| Variable | Obligatoire | Description |
|----------|-------------|-------------|
| `DISPATCH_BEARER_TOKEN` | Recommandé | Même valeur que `SMS_DISPATCH_TOKEN` sur l’app principale. |
| `SMS_MODE` | Non | `auto` (défaut), `twilio`, `upstream`, `echo` |

### Envoi réel avec Twilio

| Variable | Description |
|----------|-------------|
| `TWILIO_ACCOUNT_SID` | |
| `TWILIO_AUTH_TOKEN` | |
| `TWILIO_FROM` | Numéro E.164 |

Optionnel : `SMS_MODE=twilio`

### Relais vers une autre API (opérateur, Make, etc.)

| Variable | Description |
|----------|-------------|
| `SMS_UPSTREAM_URL` | URL qui reçoit `POST` JSON `{"to","message"}` |
| `SMS_UPSTREAM_AUTH_HEADER` | Optionnel, ex. `Authorization: Bearer xyz` |

Optionnel : `SMS_MODE=upstream`

### Mode test (`echo`)

`SMS_MODE=echo` → ne envoie pas de SMS, répond 200 (pour tester la chaîne).

## Sur l’app Logement Facile (1ᵉʳ service)

| Variable | Valeur |
|----------|--------|
| `SMS_DISPATCH_URL` | `https://sms-dispatcher-xxxx.onrender.com/dispatch` |
| `SMS_DISPATCH_TOKEN` | Identique à `DISPATCH_BEARER_TOKEN` du dispatcher |

Ne pas définir les variables `TWILIO_*` sur **Logement Facile** si tu veux tout passer par ce webhook.

## Rappel Git / Render

- **Git** : enregistrer les fichiers (`git add`, `commit`, `push`) — c’est la sauvegarde et l’envoi du code.
- **Render** : lit le dépôt et **met en ligne** ; après un push, le déploiement peut se lancer tout seul selon tes réglages.
