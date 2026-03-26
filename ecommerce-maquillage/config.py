import os
from datetime import timedelta

# NOTE:
# - Remplace les prix et médias dans ce fichier quand tu me donnes les valeurs exactes.
# - Le paiement se fait à la réception (cash ou mobile money).

APP_NAME = os.environ.get("APP_NAME", "Maquillage Pro")

#
# Images produits (on les sert via une route /media/* qui pointe vers tes images existantes)
#
PRODUCTS = [
    {
        "id": 1,
        "slug": "makeup-pen-4en1",
        "name": "Crayon Maquillage 4 en 1",
        "subtitle": "Contour + teint + lèvres (selon utilisation)",
        "price_gnf": 150000,
        "original_price_gnf": 250000,
        "offer_label": "Offre spéciale",
        "main_image": "p1-main.png",
        "gallery": [
            "p1-main.png",
        ],
        "highlights": [
            "Finition pratique au quotidien",
            "Application rapide",
            "Idéal pour retouches",
        ],
        "details": "Ajoute ici une description plus détaillée (ingrédients, bénéfices, conseils d’utilisation).",
    },
    {
        "id": 2,
        "slug": "fond-de-teint",
        "name": "Fond de teint (teintes)",
        "subtitle": "Tenue & fini uniforme",
        "price_gnf": 150000,
        "original_price_gnf": 250000,
        "offer_label": "Offre spéciale",
        "main_image": "p2-main.png",
        "gallery": [
            "p2-main.png",
            "p2-g2.png",
        ],
        "highlights": [
            "Texture agréable",
            "Uniformise le teint",
            "Look naturel",
        ],
        "details": "Ajoute ici une description plus détaillée (mode d’emploi, promesse, etc.).",
    },
]

TESTIMONIALS = [
    {
        "name": "Awa M.",
        "city": "Conakry",
        "text": "J’ai commandé pendant que le compte à rebours tournait. J’ai reçu rapidement mon produit. Merci !",
    },
    {
        "name": "Fatou S.",
        "city": "Kaloum",
        "text": "J’ai vu le prix barré (250.000FG) puis le prix spécial (150.000FG). Le compte à rebours m’a motivée. Produit top !",
    },
    {
        "name": "Mariama K.",
        "city": "Conakry",
        "text": "Paiement à la réception (cash ou Mobile Money) comme promis. J’ai reçu exactement ce qui était annoncé.",
    },
]

# Pack promo (les 2 produits ensemble)
BUNDLE_TWO_PIECES_LABEL = os.environ.get("BUNDLE_TWO_PIECES_LABEL", "Pack 2 pièces")
BUNDLE_TWO_PIECES_SPECIAL_GNF = int(os.environ.get("BUNDLE_TWO_PIECES_SPECIAL_GNF", "200000"))
BUNDLE_TWO_PIECES_ORIGINAL_GNF = int(os.environ.get("BUNDLE_TWO_PIECES_ORIGINAL_GNF", "300000"))  # 150.000 + 150.000

#
# Offres / compte à rebours
#
OFFER_DURATION_MINUTES = int(os.environ.get("OFFER_DURATION_MINUTES", "45"))

#
# Livraison
#
# Conakry: gratuit
# Hors Conakry: à la charge du client
#
SHIPPING_OUTSIDE_CONAKRY_NOTE = os.environ.get(
    "SHIPPING_OUTSIDE_CONAKRY_NOTE",
    "Hors Conakry : la livraison est à la charge du client (montant confirmé après appel).",
)

#
# Facebook Pixel
#
FB_PIXEL_ID = os.environ.get("FB_PIXEL_ID", "").strip()
FB_PIXEL_EVENT = os.environ.get("FB_PIXEL_EVENT", "Lead").strip() or "Lead"

#
# Contact (pour WhatsApp / appel)
#
CONTACT_PHONE = os.environ.get("CONTACT_PHONE", "+224613303250")
CONTACT_PHONE_PRETTY = os.environ.get("CONTACT_PHONE_PRETTY", "+224 61 33 03 25 0")
CONTACT_EMAIL = os.environ.get("CONTACT_EMAIL", "contact@example.com")

#
# Vidéo d'accroche (page d'accueil)
#
# Met un lien YouTube/Vimeo en format embed, ex:
# - YouTube: https://www.youtube.com/embed/VIDEO_ID
#
HERO_VIDEO_EMBED_URL = os.environ.get("HERO_VIDEO_EMBED_URL", "").strip()
HERO_VIDEO_TITLE = os.environ.get("HERO_VIDEO_TITLE", "Regardez la démonstration en 30 secondes")
HERO_VIDEO_SUBTITLE = os.environ.get(
    "HERO_VIDEO_SUBTITLE",
    "Cliquez ensuite sur « Accéder au catalogue » pour réserver au prix spécial (150.000FG).",
)

# Vidéo locale (fichier sur l'ordinateur)
HERO_VIDEO_LOCAL_PATH = os.environ.get(
    "HERO_VIDEO_LOCAL_PATH",
    r"c:\Users\angie\Downloads\WhatsApp Video 2026-03-26 at 09.32.24.mp4",
).strip()

