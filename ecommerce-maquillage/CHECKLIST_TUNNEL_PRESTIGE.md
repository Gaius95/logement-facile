# Checklist tunnel type « prestige » (ecommerce-maquillage uniquement)

## Objectif

Rapprocher le tunnel (Facebook / COD) d’un modèle type [prestigehommes.online](https://prestigehommes.online/) : promesse claire, confiance, prix visibles, **coordonnées complètes** (nom, téléphone, ville, adresse).

---

## 1. Fichiers concernés (déjà alignés ou à peaufiner)

| Fichier | Rôle |
|---------|------|
| `app.py` | Modèle `OrderLead`, `CheckoutForm`, route `/checkout`, migration `_migrate_order_leads_columns` |
| `templates/checkout.html` | Ordre des champs + libellés « tunnel » |
| `templates/thankyou.html` | Récap client avec ville + adresse |
| `templates/admin_commandes.html` | Colonnes Ville, Adresse pour le suivi |
| `static/script.js` | Plus de masquage de l’adresse selon la zone (adresse toujours demandée) |
| `static/styles.css` | Thème clair, prix barrés / promo (déjà en place) |
| `templates/base.html` | Bandeau promo + barre de confiance |
| `templates/index.html` / `product.html` | Landing / fiche produit (titres, CTA) |
| `config.py` | Textes promo, prix, noms produits |

---

## 2. Ordre des champs au checkout (implémenté)

1. **Nom complet** (`nom_prenom`)
2. **Téléphone** (`telephone`) — WhatsApp possible
3. **Ville** (`ville`)
4. **Zone de livraison** — Conakry / hors Conakry (`zone_livraison`)
5. **Adresse complète** (`adresse_complete`) — quartier, repère, etc.
6. **Moyen de paiement** à la réception (`payment_method`)

Les champs UTM restent en champs cachés (tracking Meta).

---

## 3. Base de données (`order_leads`)

| Colonne | Description |
|---------|-------------|
| `nom_prenom` | Nom complet |
| `telephone` | Téléphone normalisé |
| `ville` | **Nouveau** — ville (texte) |
| `adresse_complete` | **Nouveau** — adresse de livraison (jusqu’à 500 car.) |
| `zone_livraison` | `conakry` \| `outside` |
| `adresse_hors_conakry` | Conservé pour **anciennes commandes** ; les nouvelles utilisent `adresse_complete` |
| … | `payment_method`, totaux, `items_json`, UTM, etc. |

Au **premier démarrage** après mise à jour, `_migrate_order_leads_columns()` exécute un `ALTER TABLE` si les colonnes manquent (SQLite et PostgreSQL).

**Render / PostgreSQL :** après déploiement, un redémarrage du service suffit pour appliquer la migration automatique.

**Local (SQLite) :** idem au lancement de l’app.

---

## 4. Pistes optionnelles (pas encore codées)

- Bloc « 4 avantages » encore plus proche du site de référence (icônes + textes courts) sur `index.html`.
- Bandeau **répété** (header + sous le hero) avec la même phrase d’offre.
- Libellés produits / collections façon « Premier / Deuxième classement » si tu ajoutes des catégories en config.
- A/B test d’une page checkout **une colonne** sur mobile uniquement (CSS `@media`).

---

## 5. Déploiement

1. Commit / push des fichiers sous `ecommerce-maquillage/`.
2. Render : **Deploy latest commit** (root directory `ecommerce-maquillage`).
3. Tester une commande test : vérifier **admin** `/admin/commandes?cle=…` pour **Ville** et **Adresse**.

---

## 6. Vérification rapide

- [ ] Checkout affiche : nom → téléphone → ville → zone → adresse → paiement  
- [ ] Page merci affiche ville + adresse  
- [ ] Admin liste ville + adresse  
- [ ] Anciennes commandes : ville/adresse vides possibles ; adresse ancienne peut rester dans `adresse_hors_conakry` si tu avais des données historiques  
