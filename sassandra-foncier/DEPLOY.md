# Mise en ligne (Render)

## Dossier racine du service

` sassandra-foncier ` (à renseigner dans **Root Directory** sur Render).

## Build

```bash
pip install -r requirements.txt
```

## Start

```bash
gunicorn wsgi:app
```

Le `Procfile` à la racine de ce dossier contient déjà cette commande.

## Variables d’environnement

| Variable | Obligatoire | Description |
|----------|-------------|-------------|
| `SECRET_KEY` | Oui (prod) | Chaîne longue et aléatoire (sessions, hash des titres). |
| `DATABASE_URL` | Recommandé | Fournie par une base **PostgreSQL** Render. Sinon SQLite dans `instance/` (disque éphémère : données perdues au redémarrage sans Postgres). |
| `ADMIN_PASSWORD` | Non | Mot de passe du compte `admin@sassandra.ci` au premier déploiement (sinon défaut dans le code de démo). |
| `AGENT_PASSWORD` | Non | Idem pour `agent@sassandra.ci`. |

Si `DATABASE_URL` commence par `postgres://`, l’application la convertit en `postgresql://` pour SQLAlchemy.

## Comptes de démonstration (à changer en production)

Après le premier lancement avec base vide, des comptes et parcelles de démo sont créés :

- **Admin** : `admin@sassandra.ci` — mot de passe via `ADMIN_PASSWORD` ou valeur par défaut du seed.
- **Agent** : `agent@sassandra.ci`
- **Démo** : `demo@sassandra.ci` / `demo1234`

## Images hero

Déposer les fichiers dans `static/hero/` (voir `config.py` et `static/hero/LISEZ-MOI.txt`).

## Domaine

Dans Render : **Settings** → **Custom Domain** si tu utilises un nom de domaine propre.
