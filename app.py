import os
import re
import secrets
import uuid
from datetime import datetime, timezone

import requests
import stripe
from dotenv import load_dotenv
from flask import Flask, abort, flash, jsonify, redirect, render_template, request, send_file, url_for
from flask_login import LoginManager, UserMixin, current_user, login_required, login_user, logout_user
from flask_sqlalchemy import SQLAlchemy
from flask_wtf.csrf import CSRFError, CSRFProtect
from sqlalchemy import inspect, text
from werkzeug.security import check_password_hash, generate_password_hash
from werkzeug.utils import secure_filename

load_dotenv()


def is_production() -> bool:
    return (
        os.environ.get("RENDER", "").lower() == "true"
        or os.environ.get("FLASK_ENV", "").lower() == "production"
        or os.environ.get("ENVIRONMENT", "").lower() == "production"
    )


app = Flask(__name__)

_secret = (os.environ.get("SECRET_KEY") or "").strip()
if is_production():
    if not _secret or _secret == "change-me-in-production":
        raise RuntimeError(
            "SECRET_KEY doit être défini en production (variable d’environnement Render). "
            "Génère une valeur longue et aléatoire (ex. openssl rand -hex 32)."
        )
    app.config["SECRET_KEY"] = _secret
else:
    app.config["SECRET_KEY"] = _secret or "change-me-in-production"

# Cookies de session (HTTPS sur Render)
app.config["SESSION_COOKIE_HTTPONLY"] = True
app.config["SESSION_COOKIE_SAMESITE"] = "Lax"
app.config["SESSION_COOKIE_SECURE"] = is_production()

# CSRF sur tous les POST (webhooks exclus ci-dessous)
app.config["WTF_CSRF_TIME_LIMIT"] = None
app.config["WTF_CSRF_SSL_STRICT"] = is_production()
# Uploads KYC (pièce + selfie) — limite taille requête HTTP
app.config["MAX_CONTENT_LENGTH"] = int(os.environ.get("MAX_UPLOAD_MB", "16")) * 1024 * 1024

csrf = CSRFProtect(app)

# Serve local Guinea imagery from a folder with spaces: "static images/"
CONAKRY_MEDIA_DIR = os.path.join(app.root_path, "static images")

# Fichiers KYC (hors web public) — sur Render le disque est éphémère : prévoir S3 plus tard (voir PRODUCTION.md)
KYC_UPLOAD_ROOT = os.path.join(app.root_path, "uploads", "kyc")
KYC_ALLOWED_EXT = frozenset({".jpg", ".jpeg", ".png", ".webp"})
KYC_MAX_FILE_BYTES = int(os.environ.get("KYC_MAX_FILE_MB", "5")) * 1024 * 1024

# Emails admin (séparés par des virgules) pour valider les dossiers KYC : ADMIN_EMAILS=toi@mail.com,autre@mail.com
ADMIN_EMAILS = frozenset(
    e.strip().lower() for e in os.environ.get("ADMIN_EMAILS", "").split(",") if e.strip()
)

# Noms de fichiers autorisés pour /conakry-media/ (évite lecture arbitraire)
_MEDIA_NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,180}$")


def _safe_media_basename(filename: str) -> str | None:
    name = os.path.basename(filename or "")
    if not name or not _MEDIA_NAME_RE.match(name):
        return None
    return name


@app.route("/conakry-media/<path:filename>")
def conakry_media(filename: str):
    safe_name = _safe_media_basename(filename)
    if not safe_name:
        abort(404)
    file_path = os.path.join(CONAKRY_MEDIA_DIR, safe_name)
    if not os.path.isfile(file_path):
        abort(404)
    return send_file(file_path)


# Serve uploaded example images stored in Cursor workspace.
# This is only for design previews (homepage hero background).
CURSOR_ASSETS_DIR = os.path.abspath(
    os.path.join(
        app.root_path,
        "..",
        "..",
        "..",
        ".cursor",
        "projects",
        "c-Users-angie-OneDrive-Bureau-LOGEMENT-FACILE",
        "assets",
    )
)


@app.route("/cursor-assets/<path:filename>")
def cursor_asset(filename: str):
    if is_production():
        abort(404)
    # Prevent path traversal: only allow files inside CURSOR_ASSETS_DIR.
    safe_name = os.path.basename(filename)
    file_path = os.path.join(CURSOR_ASSETS_DIR, safe_name)
    if os.path.isfile(file_path):
        return send_file(file_path)

    # Fallback so production still renders the homepage.
    fallback_path = os.path.join(CONAKRY_MEDIA_DIR, "conakry.jpg")
    if os.path.isfile(fallback_path):
        return send_file(fallback_path)
    abort(404)

# DB: SQLite en local, Postgres via DATABASE_URL en prod (Render)
db_url = os.environ.get("DATABASE_URL", "sqlite:///logement_facile.db")
if db_url.startswith("postgres://"):
    db_url = db_url.replace("postgres://", "postgresql://", 1)
app.config["SQLALCHEMY_DATABASE_URI"] = db_url
app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False
if db_url.startswith("postgresql"):
    app.config["SQLALCHEMY_ENGINE_OPTIONS"] = {
        "pool_pre_ping": True,
        "pool_recycle": int(os.environ.get("DB_POOL_RECYCLE", "280")),
        "pool_size": int(os.environ.get("DB_POOL_SIZE", "5")),
        "max_overflow": int(os.environ.get("DB_MAX_OVERFLOW", "10")),
    }

db = SQLAlchemy(app)

login_manager = LoginManager()
login_manager.login_view = "connexion"
login_manager.init_app(app)


@app.after_request
def _security_headers(response):
    response.headers.setdefault("X-Content-Type-Options", "nosniff")
    response.headers.setdefault("X-Frame-Options", "SAMEORIGIN")
    response.headers.setdefault("Referrer-Policy", "strict-origin-when-cross-origin")
    response.headers.setdefault(
        "Permissions-Policy",
        "geolocation=(self), microphone=(), camera=()",
    )
    if is_production():
        response.headers.setdefault(
            "Strict-Transport-Security",
            "max-age=31536000; includeSubDomains",
        )
    return response


@app.route("/health")
def health():
    """Sonde liveness (load balancer / Render) — ne touche pas à la DB."""
    return jsonify(status="ok", service="logement-facile"), 200


@app.route("/health/ready")
def health_ready():
    """Sonde readiness : vérifie la connexion DB."""
    try:
        db.session.execute(text("SELECT 1"))
    except Exception:
        return jsonify(status="not_ready"), 503
    return jsonify(status="ready"), 200


@app.errorhandler(404)
def _not_found(_e):
    return render_template("errors/404.html"), 404


@app.errorhandler(500)
def _server_error(_e):
    return render_template("errors/500.html"), 500


@app.errorhandler(CSRFError)
def _csrf_error(_e):
    flash("Session expirée ou formulaire invalide. Recharge la page puis réessaie.", "error")
    return redirect(request.referrer or url_for("accueil")), 303


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class User(db.Model, UserMixin):
    id = db.Column(db.Integer, primary_key=True)
    email = db.Column(db.String(255), unique=True, nullable=False, index=True)
    password_hash = db.Column(db.String(255), nullable=False)
    created_at = db.Column(db.DateTime(timezone=True), default=utcnow, nullable=False)

    # KYC / identité (NULL = comptes créés avant cette fonctionnalité : publication autorisée)
    full_name = db.Column(db.String(200), nullable=True)
    id_document_type = db.Column(db.String(40), nullable=True)  # passport, national_id, driving_license, other
    id_document_number = db.Column(db.String(120), nullable=True)
    kyc_status = db.Column(db.String(32), nullable=True, index=True)
    # documents_required → pending_review → approved | rejected
    kyc_submitted_at = db.Column(db.DateTime(timezone=True), nullable=True)
    kyc_reviewed_at = db.Column(db.DateTime(timezone=True), nullable=True)
    kyc_rejection_reason = db.Column(db.Text, nullable=True)
    kyc_doc_front = db.Column(db.String(255), nullable=True)  # chemin relatif uploads/kyc/<user_id>/...
    kyc_doc_back = db.Column(db.String(255), nullable=True)
    kyc_selfie = db.Column(db.String(255), nullable=True)  # photo du visage (comparaison manuelle ou API tierce)

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
    try:
        return db.session.get(User, uid)
    except Exception:
        # Cas fréquent après déploiement : colonnes KYC manquantes dans la table `user`.
        # Tentative de migration “à chaud”, puis retry.
        try:
            _migrate_user_kyc_columns()
            return db.session.get(User, uid)
        except Exception:
            return None


def _migrate_user_kyc_columns() -> None:
    """Ajoute les colonnes KYC sur une base existante (SQLite / PostgreSQL)."""
    try:
        insp = inspect(db.engine)
        # Tables et noms peuvent être sensibles / réservés, donc on se base sur get_columns.
        existing = {c["name"] for c in insp.get_columns("user")}
        dialect = db.engine.dialect.name
        qtable = '"user"'  # quote systématique du nom

        def add_col(name: str, sql_type_sqlite: str, sql_type_pg: str) -> None:
            if name in existing:
                return
            typ = sql_type_pg if dialect == "postgresql" else sql_type_sqlite
            stmt = text(f"ALTER TABLE {qtable} ADD COLUMN {name} {typ}")
            try:
                with db.engine.begin() as conn:
                    conn.execute(stmt)
            except Exception:
                pass

        add_col("full_name", "VARCHAR(200)", "VARCHAR(200)")
        add_col("id_document_type", "VARCHAR(40)", "VARCHAR(40)")
        add_col("id_document_number", "VARCHAR(120)", "VARCHAR(120)")
        add_col("kyc_status", "VARCHAR(32)", "VARCHAR(32)")
        add_col("kyc_submitted_at", "DATETIME", "TIMESTAMP WITH TIME ZONE")
        add_col("kyc_reviewed_at", "DATETIME", "TIMESTAMP WITH TIME ZONE")
        add_col("kyc_rejection_reason", "TEXT", "TEXT")
        add_col("kyc_doc_front", "VARCHAR(255)", "VARCHAR(255)")
        add_col("kyc_doc_back", "VARCHAR(255)", "VARCHAR(255)")
        add_col("kyc_selfie", "VARCHAR(255)", "VARCHAR(255)")
    except Exception:
        # On évite de faire planter l'app : migration best-effort.
        pass


def user_kyc_allows_publish(user: "User") -> bool:
    """Comptes legacy (kyc_status NULL) : inchangé. Nouveaux comptes : identité approuvée requise."""
    if user.kyc_status is None:
        return True
    return user.kyc_status == "approved"


def is_kyc_admin(user: User) -> bool:
    return bool(user.email and user.email.strip().lower() in ADMIN_EMAILS)


def _save_kyc_image(file_storage, user_id: int, prefix: str) -> str | None:
    if not file_storage or not getattr(file_storage, "filename", None):
        return None
    raw = secure_filename(file_storage.filename)
    ext = os.path.splitext(raw)[1].lower()
    if ext not in KYC_ALLOWED_EXT:
        return None
    file_storage.seek(0, os.SEEK_END)
    size = file_storage.tell()
    file_storage.seek(0)
    if size <= 0 or size > KYC_MAX_FILE_BYTES:
        return None
    uid_dir = os.path.join(KYC_UPLOAD_ROOT, str(user_id))
    os.makedirs(uid_dir, exist_ok=True)
    out_name = f"{prefix}_{uuid.uuid4().hex}{ext}"
    out_path = os.path.join(uid_dir, out_name)
    file_storage.save(out_path)
    return f"{user_id}/{out_name}"


@app.context_processor
def inject_publish_nav():
    """Menu : si identité non validée, le bouton mène à la page KYC au lieu de /publier."""
    if not current_user.is_authenticated:
        return {
            "nav_publish_url": url_for("publier"),
            "nav_publish_label": "Publier un logement",
        }
    if user_kyc_allows_publish(current_user):
        return {
            "nav_publish_url": url_for("publier"),
            "nav_publish_label": "Publier un logement",
        }
    return {
        "nav_publish_url": url_for("verifier_identite"),
        "nav_publish_label": "Valider mon identité",
    }


with app.app_context():
    os.makedirs(KYC_UPLOAD_ROOT, exist_ok=True)
    db.create_all()
    _migrate_user_kyc_columns()


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
    # Hero images:
    # - Production: use files placed in `static images/` (hero1.png, hero2.png).
    # - Local preview fallback: use the images you sent (Cursor assets).
    # - Ultimate fallback: conakry.jpg
    local_hero1 = (
        "c__Users_angie_AppData_Roaming_Cursor_User_workspaceStorage_ebe89c2026160384c3311c4681a43649_images_"
        "WhatsApp_Image_2026-03-19_at_17.41.18-231dac61-e367-4f60-a664-9731f24348d1.png"
    )
    local_hero2 = (
        "c__Users_angie_AppData_Roaming_Cursor_User_workspaceStorage_ebe89c2026160384c3311c4681a43649_images_"
        "WhatsApp_Image_2026-03-19_at_17.41.19-446a5e3b-41e4-43e0-b54a-ff6aefb86806.png"
    )

    def pick_static_hero(candidates: list[str]) -> str | None:
        for name in candidates:
            if os.path.isfile(os.path.join(CONAKRY_MEDIA_DIR, name)):
                return name
        return None

    hero1_name = pick_static_hero(["hero1.png", "hero1.png.jpeg", "hero1.jpg", "hero1.jpeg", "hero1.webp"])
    hero2_name = pick_static_hero(["hero2.png", "hero2.png.jpeg", "hero2.jpg", "hero2.jpeg", "hero2.webp"])

    if hero1_name:
        hero1_url = url_for("conakry_media", filename=hero1_name)
    elif os.path.isfile(os.path.join(CURSOR_ASSETS_DIR, local_hero1)):
        hero1_url = url_for("cursor_asset", filename=local_hero1)
    else:
        hero1_url = url_for("conakry_media", filename="conakry.jpg")

    if hero2_name:
        hero2_url = url_for("conakry_media", filename=hero2_name)
    elif os.path.isfile(os.path.join(CURSOR_ASSETS_DIR, local_hero2)):
        hero2_url = url_for("cursor_asset", filename=local_hero2)
    else:
        hero2_url = url_for("conakry_media", filename="conakry.jpg")

    return render_template("index.html", maisons=published_listings(), hero1_url=hero1_url, hero2_url=hero2_url)


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
        if len(password) < 8:
            flash("Mot de passe trop court (min 8 caractères).", "error")
            return render_template("inscription.html"), 400
        if password != password2:
            flash("Les mots de passe ne correspondent pas.", "error")
            return render_template("inscription.html"), 400
        if User.query.filter_by(email=email).first():
            flash("Un compte existe déjà avec cet email.", "error")
            return render_template("inscription.html"), 400

        u = User(email=email, kyc_status="documents_required")
        u.set_password(password)
        db.session.add(u)
        db.session.commit()
        login_user(u)
        flash(
            "Complétez la vérification d’identité (pièce + photo du visage) pour publier des annonces.",
            "info",
        )
        return redirect(safe_next_url() or url_for("verifier_identite"))

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
        kyc_status=current_user.kyc_status,
        kyc_allows_publish=user_kyc_allows_publish(current_user),
        is_kyc_admin_user=is_kyc_admin(current_user),
    )


@app.route("/compte/verifier-identite", methods=["GET", "POST"])
@login_required
def verifier_identite():
    user = db.session.get(User, current_user.id)
    if not user:
        abort(404)

    doc_types = [
        ("passport", "Passeport"),
        ("national_id", "Carte d’identité / CNI"),
        ("driving_license", "Permis de conduire"),
        ("residence_permit", "Titre de séjour"),
        ("other", "Autre pièce officielle"),
    ]

    if request.method == "POST":
        if user.kyc_status == "approved":
            flash("Votre identité est déjà validée.", "info")
            return redirect(url_for("dashboard"))

        full_name = (request.form.get("full_name") or "").strip()
        doc_type = (request.form.get("id_document_type") or "").strip()
        doc_number = (request.form.get("id_document_number") or "").strip()

        if not full_name or len(full_name) > 200:
            flash("Indiquez votre nom complet (tel qu’il figure sur la pièce).", "error")
            return render_template(
                "verifier_identite.html", doc_types=doc_types, user=user
            ), 400
        if doc_type not in {c[0] for c in doc_types}:
            flash("Type de pièce invalide.", "error")
            return render_template(
                "verifier_identite.html", doc_types=doc_types, user=user
            ), 400
        if not doc_number or len(doc_number) > 120:
            flash("Indiquez le numéro de la pièce d’identité.", "error")
            return render_template(
                "verifier_identite.html", doc_types=doc_types, user=user
            ), 400

        f_front = request.files.get("doc_front")
        f_selfie = request.files.get("face_photo")
        f_back = request.files.get("doc_back")

        path_front = _save_kyc_image(f_front, user.id, "front")
        path_selfie = _save_kyc_image(f_selfie, user.id, "selfie")
        path_back = None
        if doc_type in ("national_id", "driving_license", "residence_permit", "other"):
            path_back = _save_kyc_image(f_back, user.id, "back")

        if not path_front or not path_selfie:
            flash(
                "Merci d’ajouter une photo lisible du recto de la pièce et une photo de votre visage (selfie). "
                f"Formats : JPG, PNG, WebP — max {KYC_MAX_FILE_BYTES // (1024 * 1024)} Mo par fichier.",
                "error",
            )
            return render_template(
                "verifier_identite.html", doc_types=doc_types, user=user
            ), 400
        if doc_type in ("national_id", "driving_license", "residence_permit", "other") and not path_back:
            flash("Pour ce type de pièce, ajoutez aussi le verso (ou 2e page).", "error")
            return render_template(
                "verifier_identite.html", doc_types=doc_types, user=user
            ), 400

        # Remplacer d’anciens fichiers si nouvel envoi
        user.full_name = full_name
        user.id_document_type = doc_type
        user.id_document_number = doc_number
        user.kyc_doc_front = path_front
        user.kyc_doc_back = path_back
        user.kyc_selfie = path_selfie
        user.kyc_status = "pending_review"
        user.kyc_submitted_at = utcnow()
        user.kyc_rejection_reason = None
        user.kyc_reviewed_at = None
        db.session.commit()
        flash(
            "Dossier envoyé. Un administrateur validera votre identité sous peu. Vous recevrez l’accès publication après validation.",
            "info",
        )
        return redirect(url_for("dashboard"))

    return render_template("verifier_identite.html", doc_types=doc_types, user=user)


_KYC_FILE_REL_RE = re.compile(r"^(\d+)/([A-Za-z0-9_.-]+)$")


@app.route("/admin/kyc/fichier/<path:rel>")
@login_required
def admin_kyc_file(rel: str):
    """Sert une image KYC uniquement aux administrateurs (pas d’URL publique)."""
    if not is_kyc_admin(current_user):
        abort(404)
    m = _KYC_FILE_REL_RE.match(rel.replace("\\", "/"))
    if not m:
        abort(404)
    uid, fname = m.group(1), m.group(2)
    abs_path = os.path.realpath(os.path.join(KYC_UPLOAD_ROOT, uid, fname))
    allowed_root = os.path.realpath(os.path.join(KYC_UPLOAD_ROOT, uid))
    if not abs_path.startswith(allowed_root + os.sep) and abs_path != allowed_root:
        abort(404)
    if not os.path.isfile(abs_path):
        abort(404)
    return send_file(abs_path)


@app.route("/admin/kyc")
@login_required
def admin_kyc_list():
    if not is_kyc_admin(current_user):
        abort(404)
    pending = (
        User.query.filter(User.kyc_status == "pending_review")
        .order_by(User.kyc_submitted_at.asc())
        .all()
    )
    return render_template("admin_kyc.html", pending=pending)


@app.route("/admin/kyc/<int:user_id>/approuver", methods=["POST"])
@login_required
def admin_kyc_approve(user_id: int):
    if not is_kyc_admin(current_user):
        abort(404)
    u = db.session.get(User, user_id)
    if not u or u.kyc_status != "pending_review":
        flash("Dossier introuvable ou déjà traité.", "error")
        return redirect(url_for("admin_kyc_list"))
    u.kyc_status = "approved"
    u.kyc_reviewed_at = utcnow()
    u.kyc_rejection_reason = None
    db.session.commit()
    flash(f"Identité approuvée pour {u.email}.", "info")
    return redirect(url_for("admin_kyc_list"))


@app.route("/admin/kyc/<int:user_id>/refuser", methods=["POST"])
@login_required
def admin_kyc_reject(user_id: int):
    if not is_kyc_admin(current_user):
        abort(404)
    u = db.session.get(User, user_id)
    if not u or u.kyc_status != "pending_review":
        flash("Dossier introuvable ou déjà traité.", "error")
        return redirect(url_for("admin_kyc_list"))
    reason = (request.form.get("reason") or "").strip()[:2000]
    u.kyc_status = "rejected"
    u.kyc_reviewed_at = utcnow()
    u.kyc_rejection_reason = reason or None
    db.session.commit()
    flash(f"Dossier refusé pour {u.email}. L’utilisateur peut corriger et renvoyer.", "info")
    return redirect(url_for("admin_kyc_list"))


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
    if not user_kyc_allows_publish(current_user):
        flash(
            "La publication d’annonces est réservée aux comptes dont l’identité a été vérifiée. "
            "Envoyez votre pièce d’identité et une photo de votre visage.",
            "error",
        )
        return redirect(url_for("verifier_identite"))

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

        if not (commune and prix and description):
            flash("Merci de remplir tous les champs obligatoires.", "error")
            return render_template("publier.html"), 400
        if len(commune) > 120 or len(prix) > 80 or len(description) > 8000:
            flash("Texte trop long (commune ≤ 120, prix ≤ 80, description ≤ 8000 caractères).", "error")
            return render_template("publier.html"), 400
        if not (-90 <= latitude <= 90) or not (-180 <= longitude <= 180):
            flash("Coordonnées GPS invalides.", "error")
            return render_template("publier.html"), 400

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
    if not user_kyc_allows_publish(current_user):
        flash("Identité non validée. Complétez la vérification avant de payer.", "error")
        return redirect(url_for("verifier_identite"))

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
@csrf.exempt
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
@csrf.exempt
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
@csrf.exempt
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
    if is_production():
        abort(404)
    if not user_kyc_allows_publish(current_user):
        flash("Identité non validée (même en démo).", "error")
        return redirect(url_for("verifier_identite"))
    listing = Maison.query.filter_by(id=listing_id, owner_id=current_user.id).first_or_404()
    listing.status = "published"
    db.session.commit()
    flash("Annonce publiée en mode démo (sans paiement).", "info")
    return redirect(url_for("dashboard"))


if __name__ == "__main__":
    app.run(debug=True, port=5000)
