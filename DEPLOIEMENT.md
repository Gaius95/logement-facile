# Partager Logement Facile en ligne (lien public)

Suis ces étapes pour obtenir un **lien web** que tu pourras envoyer à tes amis (ex. : `https://logement-facile-xxxx.onrender.com`).

---

## Étape 1 : Créer un compte GitHub (si tu n’en as pas)

1. Va sur **https://github.com**
2. Clique sur **Sign up** et crée un compte (gratuit).

---

## Étape 2 : Mettre ton projet sur GitHub

1. Va sur **https://github.com** et connecte-toi.
2. Clique sur le **+** en haut à droite → **New repository**.
3. Donne un nom au dépôt, par exemple : **logement-facile**.
4. Laisse **Public** coché, ne coche pas "Add a README".
5. Clique sur **Create repository**.

Ensuite, sur ton PC, ouvre **PowerShell** ou **Invite de commandes** et exécute :

```powershell
cd "c:\Users\angie\OneDrive\Bureau\LOGEMENT FACILE"
git init
git add .
git commit -m "Première version Logement Facile"
git branch -M main
git remote add origin https://github.com/TON-PSEUDO-GITHUB/logement-facile.git
git push -u origin main
```

Remplace **TON-PSEUDO-GITHUB** par ton vrai pseudo GitHub.  
Si on te demande de te connecter à GitHub, utilise ton pseudo et un **Personal Access Token** (mot de passe) au lieu de ton mot de passe GitHub :  
Paramètres GitHub → Developer settings → Personal access tokens → Generate new token.

---

## Étape 3 : Déployer sur Render (gratuit)

1. Va sur **https://render.com** et crée un compte (gratuit), ou connecte-toi avec GitHub.
2. Clique sur **New +** → **Web Service**.
3. Choisis ton dépôt **logement-facile** (connecte GitHub si besoin).
4. Remplis :
   - **Name** : `logement-facile` (ou un autre nom).
   - **Region** : la plus proche (ex. Frankfurt).
   - **Build Command** : `pip install -r requirements.txt`
   - **Start Command** : `gunicorn -c gunicorn.conf.py wsgi:app` (déjà dans le `Procfile`)
   - **Environment** : ajoute **`SECRET_KEY`** (longue valeur aléatoire). Sans elle, l’app ne démarre pas en production. Détails : `PRODUCTION.md`.
5. Clique sur **Create Web Service**.

Render va construire et lancer ton site. À la fin, tu auras une URL du type :

**https://logement-facile-xxxx.onrender.com**

C’est **ton lien à partager** : envoie-le à tes amis, ils pourront ouvrir le site depuis n’importe quel pays.

---

## Résumé

| Étape | Où | Résultat |
|-------|-----|----------|
| 1 | github.com | Compte GitHub |
| 2 | Ton PC + GitHub | Code en ligne dans un dépôt |
| 3 | render.com | Lien public du type https://logement-facile-xxxx.onrender.com |

Une fois le lien obtenu, tu peux l’envoyer par WhatsApp, email, etc. pour avoir les retours de tes amis.
