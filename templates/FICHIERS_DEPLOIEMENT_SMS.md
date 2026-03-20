# Git vs Render (rappel)

| Outil | À quoi ça sert |
|--------|----------------|
| **Git** (commit + push) | Enregistrer tes modifications et les envoyer sur **GitHub** (historique, sauvegarde). |
| **Render** | Prend le code sur GitHub et **met le site en ligne** (souvent auto après chaque push). |

Tu ne « uploades » pas les fichiers à la main sur Render si ton service est lié à GitHub : tu **pushes** le dépôt, Render rebuild.

---

## Fichiers à avoir en ligne pour l’option B (dispatcher SMS)

Ajoute **tout le dossier** suivant dans ton projet (puis `git add`, `commit`, `push`) :

```
sms-dispatcher/
├── app.py
├── wsgi.py
├── requirements.txt
├── Procfile
└── README.md
```

**Optionnel** (documentation seulement, pas obligatoire pour que ça tourne) :

- `FICHIERS_DEPLOIEMENT_SMS.md` (ce fichier)
- `PRODUCTION.md` / `DEPLOIEMENT.md` (déjà dans le repo)

L’app principale **Logement Facile** utilise toujours les fichiers à la racine (`app.py`, `wsgi.py`, `Procfile`, `templates/`, etc.) — rien à dupliquer.

---

## Sur Render : 2 services

1. **Service 1** (existant) — racine du repo → ton site Logement Facile.  
   Variables : `SMS_DISPATCH_URL` = `https://TON-DISPATCHER.onrender.com/dispatch`  
   et `SMS_DISPATCH_TOKEN` = un secret (ex. chaîne longue aléatoire).

2. **Service 2** (nouveau) — **Root Directory** : `sms-dispatcher`  
   Variables : `DISPATCH_BEARER_TOKEN` = **la même valeur** que `SMS_DISPATCH_TOKEN`  
   + Twilio **ou** `SMS_UPSTREAM_URL` (voir `sms-dispatcher/README.md`).

Détail pas à pas : **`sms-dispatcher/README.md`**.
