import os
import secrets
from datetime import datetime, timezone

import requests
import stripe
from dotenv import load_dotenv
from flask import Flask, abort, flash, jsonify, redirect, render_template, request, url_for
from flask_login import LoginManager, UserMixin, current_user, login_required, login_user, logout_user
from flask_sqlalchemy import SQLAlchemy
from werkzeug.security import check_password_hash, generate_password_hash

load_dotenv()

app = Flask(__name__)
app.config["SECRET_KEY"] = os.environ.get("SECRET_KEY", "change-me-in-production")

# DB: SQLite en local, Postgres via DATABASE_URL en prod (Render)
db_url = os.environ.get("DATABASE_URL", "sqlite:///logement_facile.db")
if db_url.startswith("postgres://"):
    db_url = db_url.replace("postgres://", "postgresql://", 1)
app.config["SQLALCHEMY_DATABASE_URI"] = db_url
app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False

db = SQLAlchemy(app)

login_manager = LoginManager()
login_manager.login_view = "connexion"
login_manager.init_app(app)


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class User(db.Model, UserMixin):
    id = db.Column(db.Integer, primary_key=True)
    email = db.Column(db.String(255), unique=True, nullable=False, index=True)
    password_hash = db.Column(db.String(255), nullable=False)
    created_at = db.Column(db.DateTime(timezone=True), default=utcnow, nullable=False)

    listings = db.relationship("Maison", back_populates="owner", lazy="dynamic")

    def set_password(self, password: str) -> None:
        self.password_hash = generate_password_hash(password)

    def check_password(self, password: str) -> bool:
        return check_password_hash(self.password_hash, password)


class Maison(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    owner_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False, index=True)
    commune = db.Column(db.String(120), nullable=False, index=True)
    prix = db.Column(db.String(80), nullable=False)
    description = db.Column(db.Text, nullable=False)
    latitude = db.Column(db.Float, nullable=False, default=9.6412)
    longitude = db.Column(db.Float, nullable=False, default=-13.5784)
    status = db.Column(
        db.String(30),
        nullable=False,
        default="draft",  # draft -> pending_payment -> published
        index=True,
    )
    created_at = db.Column(db.DateTime(timezone=True), default=utcnow, nullable=False, index=True)

    owner = db.relationship("User", back_populates="listings")
    payments = db.relationship("Payment", back_populates="listing", lazy="dynamic")


class Payment(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    listing_id = db.Column(db.Integer, db.ForeignKey("maison.id"), nullable=False, index=True)
    user_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False, index=True)
    provider = db.Column(db.String(20), nullable=False, default="stripe")  # stripe|cinetpay
    amount_gnf = db.Column(db.Integer, nullable=False)
    currency = db.Column(db.String(10), nullable=False, default="GNF")
    status = db.Column(db.String(30), nullable=False, default="created", index=True)  # created/paid/failed
    stripe_session_id = db.Column(db.String(255), unique=True, nullable=True, index=True)
    cinetpay_transaction_id = db.Column(db.String(80), unique=True, nullable=True, index=True)
    cinetpay_payment_url = db.Column(db.String(512), unique=False, nullable=True)
    lengopay_pay_id = db.Column(db.String(80), unique=True, nullable=True, index=True)
    lengopay_payment_url = db.Column(db.String(512), unique=False, nullable=True)
    created_at = db.Column(db.DateTime(timezone=True), default=utcnow, nullable=False)
    paid_at = db.Column(db.DateTime(timezone=True), nullable=True)

    listing = db.relationship("Maison", back_populates="payments")


@login_manager.user_loader
def load_user(user_id: str):
    try:
        uid = int(user_id)
    except ValueError:
        return None
    return db.session.get(User, uid)


with app.app_context():
    db.create_all()
    # Note: on évite les ALTER TABLE au démarrage (surtout avec SQLite sur
    # environnements éphémères comme Render). `db.create_all()` suffit
    # pour créer la structure à partir des modèles.


def published_listings(limit: int = 24):
    return (
        Maison.query.filter_by(status="published")
        .order_by(Maison.created_at.desc())
        .limit(limit)
        .all()
    )


LISTING_FEE_GNF = int(os.environ.get("LISTING_FEE_GNF", "10000"))  # frais pour publier
STRIPE_SECRET_KEY = os.environ.get("STRIPE_SECRET_KEY")
STRIPE_WEBHOOK_SECRET = os.environ.get("STRIPE_WEBHOOK_SECRET")
stripe.api_key = STRIPE_SECRET_KEY

# Paiement local Guinée (Mobile Money)
# - LengoPay: idéal pour la Guinée (GNF) avec callback sur serveur
# - CinetPay: alternative si LengoPay n'est pas configuré

# LengoPay
LENGOPAY_LICENSE_KEY = os.environ.get("LENGOPAY_LICENSE_KEY")
LENGOPAY_WEBSITE_ID = os.environ.get("LENGOPAY_WEBSITE_ID")
LENGOPAY_BASE_URL = os.environ.get("LENGOPAY_BASE_URL", "https://sandbox.lengopay.com/api/v1")

# CinetPay
CINETPAY_API_KEY = os.environ.get("CINETPAY_API_KEY")
CINETPAY_SITE_ID = os.environ.get("CINETPAY_SITE_ID")


def payment_provider() -> str:
    # Priorité LengoPay si configuré
    if LENGOPAY_LICENSE_KEY and LENGOPAY_WEBSITE_ID:
        return "lengopay"
    if CINETPAY_API_KEY and CINETPAY_SITE_ID:
        return "cinetpay"
    if STRIPE_SECRET_KEY:
        return "stripe"
    return "none"


def lengopay_init_payment(pay_amount_gnf: int, *, description: str, callback_url: str, return_url: str) -> dict | None:
    if not LENGOPAY_LICENSE_KEY or not LENGOPAY_WEBSITE_ID:
        return None

    payload = {
        "websiteid": LENGOPAY_WEBSITE_ID,
        "amount": float(pay_amount_gnf),
        "currency": "GNF",
        "return_url": return_url,
        "callback_url": callback_url,
        # LengoPay v1 PaymentRequest ne prévoit pas de champ "description" dans le SDK.
        # On passe donc l'info dans le return/callback via le site lui-même si nécessaire.
    }

    r = requests.post(
        f"{LENGOPAY_BASE_URL}/payments",
        json=payload,
        headers={
            "Accept": "application/json",
            "Content-Type": "application/json",
            "Authorization": f"Basic {LENGOPAY_LICENSE_KEY}",
            "User-Agent": "LogementFacile/1.0",
        },
        timeout=25,
    )
    if r.status_code != 200:
        return None
    return r.json()


def lengopay_check_status(pay_id: str) -> dict | None:
    if not LENGOPAY_LICENSE_KEY or not LENGOPAY_WEBSITE_ID:
        return None

    payload = {"pay_id": pay_id, "websiteid": LENGOPAY_WEBSITE_ID}
    r = requests.post(
        f"{LENGOPAY_BASE_URL}/transaction/status",
        json=payload,
        headers={
            "Accept": "application/json",
            "Content-Type": "application/json",
            "Authorization": f"Basic {LENGOPAY_LICENSE_KEY}",
            "User-Agent": "LogementFacile/1.0",
        },
        timeout=25,
    )
    if r.status_code != 200:
        return None
    return r.json()

def cinetpay_init_payment(transaction_id: str, *, amount_gnf: int, description: str, notify_url: str, return_url: str) -> dict | None:
    if not CINETPAY_API_KEY or not CINETPAY_SITE_ID:
        return None
    payload = {
        "apikey": CINETPAY_API_KEY,
        "site_id": CINETPAY_SITE_ID,
        "transaction_id": transaction_id,
        "amount": int(amount_gnf),
        "currency": "GNF",
        "description": description,
        "notify_url": notify_url,
        "return_url": return_url,
        "channels": "MOBILE_MONEY",
        "lang": "FR",
        "metadata": transaction_id,
    }
    r = requests.post(
        "https://api-checkout.cinetpay.com/v2/payment",
        json=payload,
        headers={"Content-Type": "application/json", "User-Agent": "LogementFacile/1.0"},
        timeout=25,
    )
    if r.status_code != 200:
        return None
    return r.json()


def cinetpay_check(transaction_id: str) -> dict | None:
    if not CINETPAY_API_KEY or not CINETPAY_SITE_ID:
        return None
    payload = {"transaction_id": transaction_id, "site_id": CINETPAY_SITE_ID, "apikey": CINETPAY_API_KEY}
    r = requests.post(
        "https://api-checkout.cinetpay.com/v2/payment/check",
        json=payload,
        headers={"Content-Type": "application/json", "User-Agent": "LogementFacile/1.0"},
        timeout=25,
    )
    if r.status_code != 200:
        return None
    return r.json()


def safe_next_url() -> str | None:
    nxt = request.args.get("next")
    if not nxt:
        return None
    # Sécurité: uniquement des chemins internes
    if nxt.startswith("/"):
        return nxt
    return None


@app.route("/")
def accueil():
    return render_template("index.html", maisons=published_listings())


@app.route("/connexion", methods=["GET", "POST"])
def connexion():
    if request.method == "POST":
        email = request.form.get("email", "").strip().lower()
        password = request.form.get("password", "")
        user = User.query.filter_by(email=email).first()
        if not user or not user.check_password(password):
            flash("Email ou mot de passe invalide.", "error")
            return render_template("connexion.html"), 401
        login_user(user)
        return redirect(safe_next_url() or url_for("dashboard"))
    return render_template("connexion.html")


@app.route("/inscription", methods=["GET", "POST"])
def inscription():
    if request.method == "POST":
        email = request.form.get("email", "").strip().lower()
        password = request.form.get("password", "")
        password2 = request.form.get("password2", "")

        if not email or "@" not in email:
            flash("Email invalide.", "error")
            return render_template("inscription.html"), 400
        if len(password) < 6:
            flash("Mot de passe trop court (min 6).", "error")
            return render_template("inscription.html"), 400
        if password != password2:
            flash("Les mots de passe ne correspondent pas.", "error")
            return render_template("inscription.html"), 400
        if User.query.filter_by(email=email).first():
            flash("Un compte existe déjà avec cet email.", "error")
            return render_template("inscription.html"), 400

        u = User(email=email)
        u.set_password(password)
        db.session.add(u)
        db.session.commit()
        login_user(u)
        return redirect(safe_next_url() or url_for("dashboard"))

    return render_template("inscription.html")


@app.route("/deconnexion")
@login_required
def deconnexion():
    logout_user()
    return redirect(url_for("accueil"))


@app.route("/dashboard")
@login_required
def dashboard():
    my_listings = (
        Maison.query.filter_by(owner_id=current_user.id)
        .order_by(Maison.created_at.desc())
        .all()
    )
    return render_template(
        "dashboard.html",
        listings=my_listings,
        fee_gnf=LISTING_FEE_GNF,
        stripe_enabled=bool(STRIPE_SECRET_KEY),
        flw_enabled=False,
        provider=payment_provider(),
    )


@app.route("/ajouter")
def ajouter():
    return redirect(url_for("publier"))


@app.route("/avis")
def avis():
    return render_template("avis.html")


@app.route("/maisons")
def maisons_page():
    rows = published_listings(limit=200)
    maisons_data = [
        {
            "id": m.id,
            "commune": m.commune,
            "prix": m.prix,
            "description": m.description,
            "latitude": m.latitude,
            "longitude": m.longitude,
        }
        for m in rows
    ]
    return render_template("maisons.html", maisons=rows, maisons_data=maisons_data)


@app.route("/contact", methods=["GET", "POST"])
def contact():
    if request.method == "POST":
        # TODO: enregistrer ou envoyer le message
        return redirect(url_for("accueil"))
    return render_template("contact.html")


@app.route("/publier", methods=["GET", "POST"])
@login_required
def publier():
    if request.method == "POST":
        commune = request.form.get("commune", "").strip()
        prix = request.form.get("prix", "").strip()
        description = request.form.get("description", "").strip()
        try:
            latitude = float(request.form.get("latitude", "9.6412"))
        except ValueError:
            latitude = 9.6412
        try:
            longitude = float(request.form.get("longitude", "-13.5784"))
        except ValueError:
            longitude = -13.5784

        if commune and prix and description:
            maison = Maison(
                owner_id=current_user.id,
                commune=commune,
                prix=prix,
                description=description,
                latitude=latitude,
                longitude=longitude,
                status="pending_payment",
            )
            db.session.add(maison)
            db.session.commit()

            flash("Annonce créée. Paiement requis pour la rendre visible.", "info")
            return redirect(url_for("checkout", listing_id=maison.id))

    return render_template("publier.html")


@app.route("/checkout/<int:listing_id>", methods=["GET", "POST"])
@login_required
def checkout(listing_id: int):
    listing = Maison.query.filter_by(id=listing_id, owner_id=current_user.id).first_or_404()
    if listing.status == "published":
        flash("Cette annonce est déjà publiée.", "info")
        return redirect(url_for("dashboard"))

    provider = payment_provider()
    # CinetPay exige un montant multiple de 5.
    fee_gnf = LISTING_FEE_GNF - (LISTING_FEE_GNF % 5)
    if fee_gnf <= 0:
        fee_gnf = 5
    if provider == "none":
        # Mode démo si aucun provider n'est configuré.
        return render_template(
            "paiement.html",
            listing=listing,
            fee_gnf=fee_gnf,
            stripe_enabled=False,
            flw_enabled=False,
            provider=provider,
        )

    if provider == "lengopay":
        if request.method == "POST":
            callback_url = url_for("lengopay_webhook", _external=True)
            return_url = url_for("lengopay_return", listing_id=listing.id, _external=True)
            resp = lengopay_init_payment(
                fee_gnf,
                description="Publication d'annonce — Logement Facile",
                callback_url=callback_url,
                return_url=return_url,
            )
            payment_url = (resp.get("payment_url") or resp.get("paymentUrl")) if resp else None
            pay_id_tmp = resp.get("pay_id") or resp.get("payId") if resp else None
            if not resp or not payment_url or not pay_id_tmp:
                flash("Impossible de démarrer le paiement LengoPay. Réessaie.", "error")
                return render_template(
                    "paiement.html",
                    listing=listing,
                    fee_gnf=fee_gnf,
                    stripe_enabled=bool(STRIPE_SECRET_KEY),
                    flw_enabled=False,
                    provider=provider,
                ), 502

            pay_id = pay_id_tmp

            payment = Payment(
                listing_id=listing.id,
                user_id=current_user.id,
                provider="lengopay",
                amount_gnf=fee_gnf,
                currency="GNF",
                status="created",
                lengopay_pay_id=str(pay_id),
                lengopay_payment_url=str(payment_url),
            )
            db.session.add(payment)
            db.session.commit()
            return redirect(payment_url)

        return render_template(
            "paiement.html",
            listing=listing,
            fee_gnf=fee_gnf,
            stripe_enabled=bool(STRIPE_SECRET_KEY),
            flw_enabled=False,
            provider=provider,
        )

    if provider == "cinetpay":
        if request.method == "POST":
            tx_id = f"LF-{listing.id}-{current_user.id}-{secrets.token_hex(6)}"
            notify_url = url_for("cinetpay_notify", _external=True)
            return_url = url_for("cinetpay_return", listing_id=listing.id, _external=True)
            resp = cinetpay_init_payment(
                tx_id,
                amount_gnf=fee_gnf,
                description="Publication d'annonce — Logement Facile",
                notify_url=notify_url,
                return_url=return_url,
            )
            if not resp or str(resp.get("code")) not in {"201", "00"}:
                flash("Impossible de démarrer le paiement Mobile Money. Réessaie.", "error")
                return render_template(
                    "paiement.html",
                    listing=listing,
                    fee_gnf=fee_gnf,
                    stripe_enabled=bool(STRIPE_SECRET_KEY),
                    flw_enabled=False,
                    provider=provider,
                ), 502
            payment_url = (resp.get("data") or {}).get("payment_url")
            if not payment_url:
                flash("Réponse CinetPay invalide.", "error")
                return render_template(
                    "paiement.html",
                    listing=listing,
                    fee_gnf=LISTING_FEE_GNF,
                    stripe_enabled=bool(STRIPE_SECRET_KEY),
                    flw_enabled=False,
                    provider=provider,
                ), 502

            payment = Payment(
                listing_id=listing.id,
                user_id=current_user.id,
                provider="cinetpay",
                amount_gnf=fee_gnf,
                currency="GNF",
                status="created",
                cinetpay_transaction_id=tx_id,
                cinetpay_payment_url=payment_url,
            )
            db.session.add(payment)
            db.session.commit()
            return redirect(payment_url)

        return render_template(
            "paiement.html",
            listing=listing,
            fee_gnf=fee_gnf,
            stripe_enabled=bool(STRIPE_SECRET_KEY),
            flw_enabled=False,
            provider=provider,
        )

    # Stripe (fallback)
    if request.method == "POST":
        success_url = url_for("paiement_succes", listing_id=listing.id, _external=True)
        cancel_url = url_for("paiement_annule", listing_id=listing.id, _external=True)

        # Stripe: GNF est une devise "zero-decimal" (pas de centimes)
        session = stripe.checkout.Session.create(
            mode="payment",
            payment_method_types=["card"],
            line_items=[
                {
                    "price_data": {
                        "currency": "gnf",
                        "unit_amount": LISTING_FEE_GNF,
                        "product_data": {"name": "Publication d'annonce — Logement Facile"},
                    },
                    "quantity": 1,
                }
            ],
            metadata={"listing_id": str(listing.id), "user_id": str(current_user.id)},
            success_url=success_url + "?session_id={CHECKOUT_SESSION_ID}",
            cancel_url=cancel_url,
        )

        payment = Payment(
            listing_id=listing.id,
            user_id=current_user.id,
            amount_gnf=LISTING_FEE_GNF,
            currency="GNF",
            status="created",
            stripe_session_id=session.id,
        )
        db.session.add(payment)
        db.session.commit()
        return redirect(session.url)

    return render_template(
        "paiement.html",
        listing=listing,
        fee_gnf=LISTING_FEE_GNF,
        stripe_enabled=True,
        flw_enabled=False,
        provider=provider,
    )


@app.route("/paiement/succes/<int:listing_id>")
@login_required
def paiement_succes(listing_id: int):
    listing = Maison.query.filter_by(id=listing_id, owner_id=current_user.id).first_or_404()
    return render_template("paiement_succes.html", listing=listing)


@app.route("/paiement/annule/<int:listing_id>")
@login_required
def paiement_annule(listing_id: int):
    listing = Maison.query.filter_by(id=listing_id, owner_id=current_user.id).first_or_404()
    return render_template("paiement_annule.html", listing=listing, fee_gnf=LISTING_FEE_GNF)

@app.route("/paiement/cinetpay/retour/<int:listing_id>")
@login_required
def cinetpay_return(listing_id: int):
    listing = Maison.query.filter_by(id=listing_id, owner_id=current_user.id).first_or_404()
    flash("Paiement en cours de confirmation. Si tout est OK, l'annonce sera publiée automatiquement.", "info")
    return redirect(url_for("dashboard"))


@app.route("/paiement/lengopay/retour/<int:listing_id>")
@login_required
def lengopay_return(listing_id: int):
    _listing = Maison.query.filter_by(id=listing_id, owner_id=current_user.id).first_or_404()
    flash("Paiement en cours de confirmation. Si tout est OK, l'annonce sera publiée automatiquement.", "info")
    return redirect(url_for("dashboard"))


@app.route("/webhooks/lengopay", methods=["POST"])
def lengopay_webhook():
    payload = request.get_json(silent=True) or {}
    if not payload:
        # Certains providers envoient du form-urlencoded
        payload = request.form.to_dict()  # type: ignore[assignment]

    pay_id = payload.get("pay_id") or payload.get("payId") or payload.get("payID")
    if not pay_id:
        return "OK", 200

    payment = Payment.query.filter_by(lengopay_pay_id=str(pay_id)).first()
    if not payment:
        return "OK", 200
    if payment.status == "paid":
        return "OK", 200

    verified = lengopay_check_status(str(pay_id))
    if not verified:
        return "OK", 200

    status = str(verified.get("status") or "").upper()
    amount = int(float(verified.get("amount") or 0))

    if status == "SUCCESS" and amount == int(payment.amount_gnf):
        payment.status = "paid"
        payment.paid_at = utcnow()
        listing = db.session.get(Maison, payment.listing_id)
        if listing:
            listing.status = "published"
        db.session.commit()
    else:
        # Pour info: si status n'est pas SUCCESS, on laisse l'annonce non publiée.
        payment.status = "failed"
        db.session.commit()

    return "OK", 200


@app.route("/webhooks/cinetpay", methods=["GET", "POST"])
def cinetpay_notify():
    # CinetPay ping en GET + notifie en POST (form-urlencoded)
    if request.method == "GET":
        return "OK", 200

    tx_id = (request.form.get("cpm_trans_id") or "").strip()
    if not tx_id:
        return "OK", 200

    payment = Payment.query.filter_by(cinetpay_transaction_id=tx_id).first()
    if not payment:
        return "OK", 200
    if payment.status == "paid":
        return "OK", 200

    ver = cinetpay_check(tx_id)
    if not ver or str(ver.get("code")) != "00":
        return "OK", 200
    data = ver.get("data") or {}
    status = (data.get("status") or "").upper()
    currency = (data.get("currency") or "").upper()
    amount = int(float(data.get("amount") or 0))

    # ACCEPTED = payé, WAITING_FOR_CUSTOMER = en attente
    # Vérifier avec les valeurs enregistrées (plus fiable).
    if status == "ACCEPTED" and currency == (payment.currency or "").upper() and amount == int(payment.amount_gnf):
        payment.status = "paid"
        payment.paid_at = utcnow()
        listing = db.session.get(Maison, payment.listing_id)
        if listing:
            listing.status = "published"
        db.session.commit()

    return "OK", 200


@app.route("/webhooks/stripe", methods=["POST"])
def stripe_webhook():
    if not STRIPE_WEBHOOK_SECRET:
        return jsonify({"error": "Webhook secret not configured"}), 400

    payload = request.get_data(as_text=True)
    sig_header = request.headers.get("Stripe-Signature", "")
    try:
        event = stripe.Webhook.construct_event(payload, sig_header, STRIPE_WEBHOOK_SECRET)
    except Exception:
        return jsonify({"error": "Invalid signature"}), 400

    if event["type"] == "checkout.session.completed":
        session = event["data"]["object"]
        session_id = session.get("id")
        if session_id:
            payment = Payment.query.filter_by(stripe_session_id=session_id).first()
            if payment and payment.status != "paid":
                payment.status = "paid"
                payment.paid_at = utcnow()
                listing = db.session.get(Maison, payment.listing_id)
                if listing:
                    listing.status = "published"
                db.session.commit()

    return jsonify({"received": True})


@app.route("/dev/publier-sans-payer/<int:listing_id>", methods=["POST"])
@login_required
def dev_publish_without_pay(listing_id: int):
    if os.environ.get("FLASK_ENV") == "production":
        abort(404)
    listing = Maison.query.filter_by(id=listing_id, owner_id=current_user.id).first_or_404()
    listing.status = "published"
    db.session.commit()
    flash("Annonce publiée en mode démo (sans paiement).", "info")
    return redirect(url_for("dashboard"))


if __name__ == "__main__":
    app.run(debug=True, port=5000)
