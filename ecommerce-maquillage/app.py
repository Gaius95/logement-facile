import json
import os
from datetime import datetime, timedelta, timezone

from flask import (
    Flask,
    abort,
    flash,
    redirect,
    render_template,
    request,
    send_file,
    session,
    url_for,
)
from flask_sqlalchemy import SQLAlchemy
from flask_wtf import FlaskForm, CSRFProtect
from flask_wtf.csrf import CSRFError
from sqlalchemy import func
from wtforms import IntegerField, RadioField, StringField, TelField, TextAreaField, HiddenField
from wtforms.validators import DataRequired, Length, NumberRange, Optional, Regexp
import config as app_config

BASE_DIR = os.path.dirname(os.path.abspath(__file__))

# On sert les médias depuis un dossier du projet.
# Rend compatible Render (pas de chemins Windows locaux).
MEDIA_DIR = os.path.join(BASE_DIR, "static", "media")

app = Flask(__name__, template_folder="templates", static_folder="static")
app.config["SECRET_KEY"] = os.environ.get("SECRET_KEY", "dev-secret-change-me")

_db_url = os.environ.get("DATABASE_URL", "").strip()
if not _db_url:
    _db_url = f"sqlite:///{os.path.join(BASE_DIR, 'ecommerce_maquillage.db')}"
elif _db_url.startswith("postgres://"):
    # SQLAlchemy / Render : l’URL fournie commence souvent par postgres://
    _db_url = "postgresql://" + _db_url[len("postgres://") :]
app.config["SQLALCHEMY_DATABASE_URI"] = _db_url
app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False

# Cookies de session cohérents avec HTTPS (Render, etc.)
if os.environ.get("RENDER") or os.environ.get("FLASK_ENV", "").lower() == "production":
    app.config["SESSION_COOKIE_SECURE"] = True
    app.config["SESSION_COOKIE_HTTPONLY"] = True
    app.config["SESSION_COOKIE_SAMESITE"] = "Lax"

db = SQLAlchemy(app)
csrf = CSRFProtect(app)


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def format_gnf(amount_gnf: int) -> str:
    # Format pro lisible (ex: 45 000)
    try:
        amount = int(amount_gnf)
    except Exception:
        amount = 0
    # Marketing: 250.000FG (selon ton exemple)
    s = f"{amount:,}".replace(",", ".")
    return f"{s}FG"


app.jinja_env.globals["format_gnf"] = format_gnf

PRODUCTS_BY_ID = {p["id"]: p for p in app_config.PRODUCTS}
ALLOWED_MEDIA = set()
for p in app_config.PRODUCTS:
    ALLOWED_MEDIA.add(p["main_image"])
    for img in p.get("gallery", []):
        ALLOWED_MEDIA.add(img)


def offer_expires_at() -> datetime:
    key = "offer_expires_at_iso"
    iso = session.get(key)
    if not iso:
        expires = utcnow() + timedelta(minutes=app_config.OFFER_DURATION_MINUTES)
        session[key] = expires.isoformat()
        return expires
    try:
        expires_at = datetime.fromisoformat(iso)
        # Si l'offre a expiré côté serveur, on la réinitialise
        # pour que le front affiche toujours un compte à rebours actif.
        if expires_at <= utcnow():
            expires = utcnow() + timedelta(minutes=app_config.OFFER_DURATION_MINUTES)
            session[key] = expires.isoformat()
            return expires
        return expires_at
    except Exception:
        expires = utcnow() + timedelta(minutes=app_config.OFFER_DURATION_MINUTES)
        session[key] = expires.isoformat()
        return expires


def cart_get() -> dict:
    # Cart: {product_id(str): qty(int)}
    return session.get("cart", {}) or {}


def cart_set(cart: dict) -> None:
    # Store keys as strings to avoid JSON issues
    session["cart"] = {str(k): int(v) for k, v in cart.items() if int(v) > 0}


def cart_items():
    cart = cart_get()
    items = []
    subtotal_regular = 0
    for product_id_str, qty in cart.items():
        product_id = int(product_id_str)
        product = PRODUCTS_BY_ID.get(product_id)
        if not product:
            continue
        price = int(product["price_gnf"])
        subtotal_regular += price * qty
        items.append(
            {
                "product": product,
                "qty": qty,
                "line_total_gnf": price * qty,
            }
        )

    # Remise pack "les deux pieces"
    # Règle: 1 pack = 1 unité de chaque produit (id=1 et id=2).
    qty1 = int(cart.get("1", 0) or 0)
    qty2 = int(cart.get("2", 0) or 0)
    bundles = min(qty1, qty2)
    subtotal_after = subtotal_regular
    bundle_original_total = int(app_config.BUNDLE_TWO_PIECES_ORIGINAL_GNF) * bundles
    bundle_special_total = int(app_config.BUNDLE_TWO_PIECES_SPECIAL_GNF) * bundles
    # On calcule la réduction comme "original - special"
    discount_amount = max(0, bundle_original_total - bundle_special_total)
    subtotal_after = subtotal_regular - discount_amount

    return items, subtotal_after, {
        "bundles": bundles,
        "discount_amount_gnf": discount_amount,
        "bundle_original_total_gnf": bundle_original_total,
        "bundle_special_total_gnf": bundle_special_total,
    }


class OrderLead(db.Model):
    __tablename__ = "order_leads"
    id = db.Column(db.Integer, primary_key=True)
    created_at = db.Column(db.DateTime(timezone=True), server_default=func.now())

    status = db.Column(db.String(30), nullable=False, default="new")  # new|confirmed|cancelled

    nom_prenom = db.Column(db.String(120), nullable=False)
    telephone = db.Column(db.String(30), nullable=False)

    zone_livraison = db.Column(db.String(30), nullable=False, default="conakry")  # conakry|outside
    adresse_hors_conakry = db.Column(db.String(240), nullable=True)

    payment_method = db.Column(db.String(30), nullable=False)  # cash|mobile_money

    items_json = db.Column(db.Text, nullable=False)  # [{product_id, qty}]
    subtotal_gnf = db.Column(db.Integer, nullable=False, default=0)
    delivery_gnf = db.Column(db.Integer, nullable=False, default=0)
    grand_total_gnf = db.Column(db.Integer, nullable=False, default=0)

    offer_expires_at = db.Column(db.DateTime(timezone=True), nullable=True)

    utm_source = db.Column(db.String(120), nullable=True)
    utm_campaign = db.Column(db.String(120), nullable=True)
    utm_content = db.Column(db.String(120), nullable=True)
    utm_term = db.Column(db.String(120), nullable=True)


with app.app_context():
    db.create_all()


class CartAddForm(FlaskForm):
    qty = IntegerField("Quantite", validators=[DataRequired(), NumberRange(min=1, max=10)])


class CartUpdateForm(FlaskForm):
    product_id = HiddenField(validators=[DataRequired()])
    qty = IntegerField("Quantite", validators=[DataRequired(), NumberRange(min=1, max=10)])


class CheckoutForm(FlaskForm):
    nom_prenom = StringField("Nom et prenom", validators=[DataRequired(), Length(max=120)])
    telephone = TelField(
        "Numero de telephone",
        filters=[lambda x: "".join((x or "").split()) if x is not None else None],
        validators=[
            DataRequired(),
            Regexp(r"^[0-9+]{8,22}$", message="Numero invalide (chiffres et + uniquement, min. 8)"),
            Length(max=30),
        ],
    )

    zone_livraison = RadioField(
        "Zone de livraison",
        choices=[("conakry", "Conakry (livraison gratuite)"), ("outside", "Hors Conakry (a la charge du client)")],
        default="conakry",
        validators=[DataRequired()],
    )
    adresse_hors_conakry = TextAreaField("Adresse (obligatoire si Hors Conakry)", validators=[Optional(), Length(max=240)])

    payment_method = RadioField(
        "Moyen de paiement a la reception",
        choices=[("cash", "Cash"), ("mobile_money", "Mobile Money")],
        default="mobile_money",
        validators=[DataRequired()],
    )

    utm_source = HiddenField()
    utm_campaign = HiddenField()
    utm_content = HiddenField()
    utm_term = HiddenField()

    def validate(self, extra_validators=None):
        ok = super().validate(extra_validators=extra_validators)
        if not ok:
            return False
        # Hors Conakry : livraison à la charge du client.
        # On ne force pas l'adresse (tu as demandé seulement Nom + Téléphone).
        return True


@app.context_processor
def inject_common():
    expires = offer_expires_at()
    return {
        "app_name": app_config.APP_NAME,
        "offer_expires_at_iso": expires.isoformat(),
        "offer_minutes": app_config.OFFER_DURATION_MINUTES,
        "testimonials": app_config.TESTIMONIALS,
        "fb_pixel_id": app_config.FB_PIXEL_ID,
        "fb_pixel_event": app_config.FB_PIXEL_EVENT,
        "contact_phone": app_config.CONTACT_PHONE,
        "contact_phone_pretty": app_config.CONTACT_PHONE_PRETTY,
        "contact_email": app_config.CONTACT_EMAIL,
        "hero_video_embed_url": app_config.HERO_VIDEO_EMBED_URL,
        "hero_video_local_url": url_for("hero_video_local"),
        "hero_video_title": app_config.HERO_VIDEO_TITLE,
        "hero_video_subtitle": app_config.HERO_VIDEO_SUBTITLE,
        "shipping_outside_note": app_config.SHIPPING_OUTSIDE_CONAKRY_NOTE,
    }


@app.route("/media/<path:filename>")
def media(filename: str):
    # Sécurité: on limite aux images connues côté config.
    fn = os.path.basename(filename)
    # Comme les fichiers sont déjà “safe”, on compare en exact avec la config.
    if fn not in ALLOWED_MEDIA:
        abort(404)
    from flask import send_from_directory

    return send_from_directory(MEDIA_DIR, fn)


@app.route("/media/local-hero-video")
def hero_video_local():
    # La vidéo est désormais stockée dans le dossier du projet (Render compatible).
    video_path = os.path.join(MEDIA_DIR, "hero-promo.mp4")
    if not os.path.isfile(video_path):
        abort(404)
    return send_file(video_path, mimetype="video/mp4")


@app.route("/__debug/video")
def debug_video():
    video_path = app_config.HERO_VIDEO_LOCAL_PATH
    exists = bool(video_path and os.path.isfile(video_path))
    return {
        "video_path": video_path,
        "exists": exists,
    }


@app.route("/")
def index():
    # Petite logique "pro"
    items, subtotal, _bundle_info = cart_items()
    featured = app_config.PRODUCTS
    return render_template(
        "index.html",
        products=featured,
        cart_items_count=sum(i["qty"] for i in items),
        cart_subtotal_gnf=subtotal,
    )


@app.route("/catalogue")
def catalogue():
    items, subtotal, _bundle_info = cart_items()
    return render_template(
        "catalog.html",
        products=app_config.PRODUCTS,
        cart_items_count=sum(i["qty"] for i in items),
        cart_subtotal_gnf=subtotal,
    )


@app.route("/produit/<slug>")
def product(slug: str):
    product_obj = next((p for p in app_config.PRODUCTS if p["slug"] == slug), None)
    if not product_obj:
        abort(404)
    items, subtotal, _bundle_info = cart_items()
    # Galerie: main + autres
    return render_template(
        "product.html",
        product=product_obj,
        cart_items_count=sum(i["qty"] for i in items),
        cart_subtotal_gnf=subtotal,
    )


@app.route("/cart")
def cart():
    items, subtotal, bundle_info = cart_items()
    return render_template(
        "cart.html",
        cart_items=items,
        cart_subtotal_gnf=subtotal,
        bundle_info=bundle_info,
    )


@app.route("/cart/add/<int:product_id>", methods=["POST"])
def cart_add(product_id: int):
    form = CartAddForm()
    if not form.validate_on_submit():
        flash("Quantité invalide.", "error")
        return redirect(request.referrer or url_for("catalogue"))

    product = PRODUCTS_BY_ID.get(product_id)
    if not product:
        abort(404)

    cart = cart_get()
    qty = int(form.qty.data or 1)
    cart[str(product_id)] = cart.get(str(product_id), 0) + qty
    cart_set(cart)
    flash("Ajouté au panier.", "info")
    return redirect(url_for("cart"))


@app.route("/cart/update", methods=["POST"])
def cart_update():
    form = CartUpdateForm()
    if not form.validate_on_submit():
        flash("Mise à jour du panier impossible.", "error")
        return redirect(url_for("cart"))

    cart = cart_get()
    product_id = int(form.product_id.data)
    qty = int(form.qty.data)
    if qty <= 0:
        cart.pop(str(product_id), None)
    else:
        cart[str(product_id)] = qty
    cart_set(cart)
    flash("Panier mis à jour.", "info")
    return redirect(url_for("cart"))


@app.route("/cart/remove/<int:product_id>", methods=["POST"])
def cart_remove(product_id: int):
    cart = cart_get()
    cart.pop(str(product_id), None)
    cart_set(cart)
    flash("Article retiré du panier.", "info")
    return redirect(url_for("cart"))


@app.route("/checkout", methods=["GET", "POST"])
def checkout():
    items, subtotal, bundle_info = cart_items()
    if not items:
        flash("Votre panier est vide.", "error")
        return redirect(url_for("catalogue"))

    default_utm = {
        "utm_source": request.args.get("utm_source", ""),
        "utm_campaign": request.args.get("utm_campaign", ""),
        "utm_content": request.args.get("utm_content", ""),
        "utm_term": request.args.get("utm_term", ""),
    }

    form = CheckoutForm()
    form.utm_source.data = default_utm["utm_source"]
    form.utm_campaign.data = default_utm["utm_campaign"]
    form.utm_content.data = default_utm["utm_content"]
    form.utm_term.data = default_utm["utm_term"]

    # Hors Conakry: montant confirmé après appel, donc on ne l'inclut pas dans le total.
    delivery_fee = 0
    shipping_zone = "conakry"
    if request.method == "POST" and form.validate_on_submit():
        shipping_zone = form.zone_livraison.data

    if form.validate_on_submit():
        # Build order
        offer_exp = offer_expires_at()

        items_payload = [
            {"product_id": int(i["product"]["id"]), "qty": int(i["qty"])}
            for i in items
        ]

        grand_total = subtotal + delivery_fee

        order = OrderLead(
            status="new",
            nom_prenom=form.nom_prenom.data.strip(),
            telephone=form.telephone.data.strip(),
            zone_livraison=form.zone_livraison.data,
            adresse_hors_conakry=(form.adresse_hors_conakry.data or "").strip() or None,
            payment_method=form.payment_method.data,
            items_json=json.dumps(items_payload, ensure_ascii=False),
            subtotal_gnf=subtotal,
            delivery_gnf=delivery_fee,
            grand_total_gnf=grand_total,
            offer_expires_at=offer_exp,
            utm_source=form.utm_source.data.strip() or None,
            utm_campaign=form.utm_campaign.data.strip() or None,
            utm_content=form.utm_content.data.strip() or None,
            utm_term=form.utm_term.data.strip() or None,
        )
        db.session.add(order)
        db.session.commit()

        # Clear cart
        session.pop("cart", None)
        flash("Commande envoyée. Nous vous contactons rapidement.", "success")

        return redirect(url_for("thankyou", order_id=order.id))

    return render_template(
        "checkout.html",
        form=form,
        cart_items=items,
        cart_subtotal_gnf=subtotal,
        bundle_info=bundle_info,
        delivery_fee=delivery_fee,
        shipping_zone=shipping_zone,
    )


@app.route("/merci/<int:order_id>")
def thankyou(order_id: int):
    order = OrderLead.query.filter_by(id=order_id).first_or_404()
    # Parse items
    items_payload = json.loads(order.items_json or "[]")
    resolved_items = []
    qty1 = 0
    qty2 = 0
    for entry in items_payload:
        pid = int(entry.get("product_id"))
        qty = int(entry.get("qty", 1))
        product = PRODUCTS_BY_ID.get(pid)
        if not product:
            continue
        if pid == 1:
            qty1 = qty
        if pid == 2:
            qty2 = qty
        price = int(product["price_gnf"])
        resolved_items.append(
            {
                "product": product,
                "qty": qty,
                "line_total_gnf": price * qty,
            }
        )

    bundles = min(int(qty1 or 0), int(qty2 or 0))
    bundle_original_total_gnf = int(app_config.BUNDLE_TWO_PIECES_ORIGINAL_GNF) * bundles
    bundle_special_total_gnf = int(app_config.BUNDLE_TWO_PIECES_SPECIAL_GNF) * bundles
    discount_amount_gnf = max(0, bundle_original_total_gnf - bundle_special_total_gnf)
    bundle_info = {
        "bundles": bundles,
        "discount_amount_gnf": discount_amount_gnf,
        "bundle_original_total_gnf": bundle_original_total_gnf,
        "bundle_special_total_gnf": bundle_special_total_gnf,
    }

    # TTL countdown for UI
    expires_iso = order.offer_expires_at.isoformat() if order.offer_expires_at else offer_expires_at().isoformat()
    return render_template(
        "thankyou.html",
        order=order,
        items=resolved_items,
        offer_expires_at_iso=expires_iso,
        bundle_info=bundle_info,
    )


@app.errorhandler(CSRFError)
def handle_csrf_error(_e):
    flash("Session expirée ou formulaire incomplet. Réessayez depuis la page produit ou le panier.", "error")
    return redirect(request.referrer or url_for("index"))


@app.route("/admin/commandes")
def admin_commandes():
    """Liste des commandes : définir ADMIN_ORDERS_SECRET sur Render, puis
    https://ton-site.onrender.com/admin/commandes?cle=VOTRE_SECRET
    """
    key = os.environ.get("ADMIN_ORDERS_SECRET", "").strip()
    if not key or request.args.get("cle") != key:
        abort(404)
    orders = OrderLead.query.order_by(OrderLead.created_at.desc()).limit(300).all()
    return render_template("admin_commandes.html", orders=orders)


@app.errorhandler(404)
def not_found(_e):
    return render_template("404.html"), 404


if __name__ == "__main__":
    debug = os.environ.get("DEBUG", "0").lower() in {"1", "true", "yes", "on"}
    # use_reloader uniquement en debug, sinon on évite les doublons de process.
    host = "127.0.0.1" if debug else "0.0.0.0"
    app.run(debug=debug, use_reloader=debug, host=host, port=int(os.environ.get("PORT", "5000")))

