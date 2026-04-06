import hashlib
import io
import json
import os
import secrets
import shutil
from datetime import datetime, timezone
from functools import wraps

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
from fpdf import FPDF
from sqlalchemy import func

import config
from models import (
    AdminRequest,
    AuditLog,
    CompanyProfile,
    LandTitle,
    Listing,
    ListingComment,
    ListingImage,
    ListingLike,
    Parcel,
    ParcelHistory,
    User,
    db,
)

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
INSTANCE_DIR = os.path.join(BASE_DIR, "instance")

LISTING_UPLOAD_REL = "uploads/listings"
ALLOWED_LISTING_IMAGES = frozenset({"png", "jpg", "jpeg", "webp", "gif"})


def ensure_listing_upload_dir() -> None:
    path = os.path.join(BASE_DIR, "static", LISTING_UPLOAD_REL.replace("/", os.sep))
    os.makedirs(path, exist_ok=True)


def collect_valid_listing_uploads(files_storage):
    """Return [(FileStorage, extension_lower), ...] for valid image files."""
    out = []
    for f in files_storage:
        if not f or not f.filename:
            continue
        name = f.filename
        if "." not in name:
            continue
        ext = name.rsplit(".", 1)[-1].lower()
        if ext not in ALLOWED_LISTING_IMAGES:
            continue
        out.append((f, ext))
    return out


def _database_url() -> str:
    raw = (os.environ.get("DATABASE_URL") or "").strip()
    if not raw:
        os.makedirs(INSTANCE_DIR, exist_ok=True)
        return "sqlite:///" + os.path.join(INSTANCE_DIR, "sassandra.db").replace("\\", "/")
    if raw.startswith("postgres://"):
        raw = "postgresql://" + raw[len("postgres://") :]
    return raw


def title_hash(ref: str, secret: str) -> str:
    return hashlib.sha256(f"{ref}|{secret}".encode()).hexdigest()


def log_audit(actor_id, action, target_type=None, target_id=None, detail=None):
    db.session.add(
        AuditLog(
            actor_id=actor_id,
            action=action,
            target_type=target_type,
            target_id=str(target_id) if target_id is not None else None,
            detail=detail,
        )
    )


app = Flask(__name__, static_folder="static", template_folder="templates")
app.config["SECRET_KEY"] = os.environ.get("SECRET_KEY", "dev-sassandra-change-me")
app.config["SQLALCHEMY_DATABASE_URI"] = _database_url()
app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False
app.config["MAX_CONTENT_LENGTH"] = 25 * 1024 * 1024

db.init_app(app)


def login_required(f):
    @wraps(f)
    def w(*args, **kwargs):
        if not session.get("user_id"):
            flash("Veuillez vous connecter.", "error")
            return redirect(url_for("auth_login", next=request.path))
        return f(*args, **kwargs)

    return w


def role_required(*roles):
    def deco(f):
        @wraps(f)
        @login_required
        def w(*args, **kwargs):
            u = User.query.get(session["user_id"])
            if not u or u.role not in roles:
                abort(403)
            return f(*args, **kwargs)

        return w

    return deco


@app.context_processor
def inject_globals():
    hero_urls = []
    for rel in config.HERO_IMAGES:
        path = os.path.join(BASE_DIR, "static", rel.replace("/", os.sep))
        if os.path.isfile(path):
            hero_urls.append(url_for("static", filename=rel))
    logo_path = os.path.join(BASE_DIR, "static", config.BRAND_LOGO.replace("/", os.sep))
    brand_logo_url = (
        url_for("static", filename=config.BRAND_LOGO) if os.path.isfile(logo_path) else None
    )
    uid = session.get("user_id")
    user = User.query.get(uid) if uid else None
    return {
        "app_name": config.APP_NAME,
        "hero_image_urls": hero_urls,
        "hero_interval_ms": config.HERO_INTERVAL_MS,
        "current_user": user,
        "brand_logo_url": brand_logo_url,
    }


def seed_if_empty():
    if User.query.count() > 0:
        return
    secret = app.config["SECRET_KEY"]

    admin = User(email="admin@sassandra.ci", full_name="Administrateur", role="admin")
    admin.set_password(os.environ.get("ADMIN_PASSWORD", "Sassandra2026!"))
    agent = User(email="agent@sassandra.ci", full_name="Agent terrain", role="agent", identity_verified=True)
    agent.set_password(os.environ.get("AGENT_PASSWORD", "Sassandra2026!"))
    demo = User(email="demo@sassandra.ci", full_name="Citoyen demo", role="user", identity_verified=True)
    demo.set_password("demo1234")
    db.session.add_all([admin, agent, demo])
    db.session.flush()

    parcels_data = [
        ("SA-2024-001", "Sassandra", "Centre-ville", "M. Kouassi A.***", "titre", "Residentiel", 450.0, 4.95, -6.08),
        ("SA-2024-002", "Sassandra", "Bakoukou", "Mme Traore B.***", "instruction", "Agricole", 1200.0, 4.92, -6.10),
        ("SA-2024-003", "Sassandra", "Plage", None, "litige", "Mixte", 800.0, 4.96, -6.05),
    ]
    for pid, com, quart, owner, stat, usage, area, la, ln in parcels_data:
        p = Parcel(
            public_id=pid,
            commune=com,
            quartier=quart,
            owner_display=owner,
            status=stat,
            usage=usage,
            area_m2=area,
            lat=la,
            lng=ln,
        )
        db.session.add(p)
        db.session.flush()
        db.session.add(
            ParcelHistory(
                parcel_id=p.id,
                label="Inscription cadastrale",
                detail="Parcelle enregistree (donnees de demonstration).",
            )
        )
        if stat == "titre":
            ref = "TF-CI-" + pid.replace("-", "")
            db.session.add(
                LandTitle(
                    parcel_id=p.id,
                    reference_no=ref,
                    authenticity_hash=title_hash(ref, secret),
                    issued_at=datetime.now(timezone.utc),
                )
            )

    lst = Listing(
        user_id=demo.id,
        title="Terrain bord de route — Bakoukou",
        description="Contact pour negociation (demo).",
        parcel_public_id="SA-2024-002",
        price_cfa=45_000_000,
        lat=4.92,
        lng=-6.1,
        status="published",
    )
    db.session.add(lst)
    db.session.flush()
    ensure_listing_upload_dir()
    hero_demo = os.path.join(BASE_DIR, "static", "hero", "01-bassin-ci.png")
    if os.path.isfile(hero_demo):
        dst_name = f"{lst.id}_seed.png"
        dst_path = os.path.join(BASE_DIR, "static", LISTING_UPLOAD_REL.replace("/", os.sep), dst_name)
        shutil.copy2(hero_demo, dst_path)
        db.session.add(
            ListingImage(
                listing_id=lst.id,
                filename=f"{LISTING_UPLOAD_REL}/{dst_name}",
                sort_order=0,
            )
        )
    log_audit(agent.id, "seed", "system", None, "Donnees initiales")
    db.session.commit()


@app.route("/")
def index():
    return render_template("index.html")


@app.route("/a-propos")
def a_propos():
    return render_template("a_propos.html")


@app.route("/entreprise")
def enterprise_hub():
    return render_template("enterprise_hub.html")


@app.route("/entreprise/inscription", methods=["GET", "POST"])
def enterprise_register():
    if request.method == "POST":
        company_name = (request.form.get("company_name") or "").strip()
        email = (request.form.get("email") or "").strip().lower()
        phone = (request.form.get("phone") or "").strip()
        password = request.form.get("password") or ""
        siege = (request.form.get("siege") or "").strip()
        ville = (request.form.get("ville") or "").strip()
        rc = (request.form.get("registre_commerce") or "").strip()
        if not all([company_name, email, password, siege, ville, rc]):
            flash("Remplis tous les champs obligatoires.", "error")
        elif len(password) < 6:
            flash("Mot de passe : au moins 6 caracteres.", "error")
        elif User.query.filter_by(email=email).first():
            flash("Cet email est deja utilise.", "error")
        else:
            u = User(email=email, full_name=company_name, phone=phone or None, role="company")
            u.set_password(password)
            db.session.add(u)
            db.session.flush()
            db.session.add(
                CompanyProfile(
                    user_id=u.id,
                    company_name=company_name,
                    siege=siege,
                    ville=ville,
                    registre_commerce=rc,
                )
            )
            db.session.commit()
            session["user_id"] = u.id
            flash("Compte entreprise cree. Vous pouvez publier vos biens.", "success")
            return redirect(url_for("listings_list"))
    return render_template("enterprise_register.html")


@app.route("/auth/connexion", methods=["GET", "POST"])
def auth_login():
    if request.method == "POST":
        email = (request.form.get("email") or "").strip().lower()
        password = request.form.get("password") or ""
        nxt = request.args.get("next") or request.form.get("next") or ""
        u = User.query.filter_by(email=email).first()
        if u and u.check_password(password):
            session["user_id"] = u.id
            flash("Connexion reussie.", "success")
            if nxt and nxt.startswith("/"):
                return redirect(nxt)
            return redirect(url_for("index"))
        flash("Email ou mot de passe incorrect.", "error")
    return render_template("auth_login.html", next=request.args.get("next", ""))


@app.route("/auth/inscription", methods=["GET", "POST"])
def auth_register():
    if request.method == "POST":
        email = (request.form.get("email") or "").strip().lower()
        password = request.form.get("password") or ""
        full_name = (request.form.get("full_name") or "").strip()
        phone = (request.form.get("phone") or "").strip()
        if not email or not password or not full_name:
            flash("Remplis tous les champs obligatoires.", "error")
        elif User.query.filter_by(email=email).first():
            flash("Cet email est deja utilise.", "error")
        else:
            u = User(email=email, full_name=full_name, phone=phone or None, role="user")
            u.set_password(password)
            db.session.add(u)
            db.session.commit()
            session["user_id"] = u.id
            flash("Compte cree. Bienvenue !", "success")
            return redirect(url_for("index"))
    return render_template("auth_register.html")


@app.route("/auth/deconnexion")
def auth_logout():
    session.pop("user_id", None)
    flash("Deconnecte.", "info")
    return redirect(url_for("index"))


@app.route("/recherche")
def search_hub():
    return render_template("search_hub.html")


@app.route("/recherche/identifiant", methods=["GET", "POST"])
def search_by_id():
    parcel = None
    q = (request.form.get("public_id") or request.args.get("q") or "").strip().upper()
    if request.method == "POST" or q:
        if not q:
            flash("Saisis un identifiant.", "error")
        else:
            parcel = Parcel.query.filter_by(public_id=q).first()
            if not parcel:
                flash("Aucune parcelle trouvee pour cet identifiant.", "error")
    return render_template("search_by_id.html", parcel=parcel, q=q)


@app.route("/recherche/commune", methods=["GET", "POST"])
def search_by_commune():
    parcels = []
    commune = (request.form.get("commune") or request.args.get("commune") or "").strip()
    quartier = (request.form.get("quartier") or request.args.get("quartier") or "").strip()
    if request.method == "POST" or commune or quartier:
        qy = Parcel.query
        if commune:
            qy = qy.filter(Parcel.commune.ilike(f"%{commune}%"))
        if quartier:
            qy = qy.filter(Parcel.quartier.ilike(f"%{quartier}%"))
        parcels = qy.order_by(Parcel.public_id).limit(50).all()
        if not parcels:
            flash("Aucun resultat pour ces criteres.", "info")
    return render_template("search_by_commune.html", parcels=parcels, commune=commune, quartier=quartier)


@app.route("/recherche/carte")
def search_map_redirect():
    return redirect(url_for("map_sig"))


@app.route("/parcelle/<public_id>")
def parcel_detail(public_id):
    p = Parcel.query.filter_by(public_id=public_id.upper()).first_or_404()
    history = ParcelHistory.query.filter_by(parcel_id=p.id).order_by(ParcelHistory.created_at.desc()).all()
    title = LandTitle.query.filter_by(parcel_id=p.id).first()
    return render_template("parcel_detail.html", parcel=p, history=history, title=title)


@app.route("/titre/<public_id>")
def title_view(public_id):
    p = Parcel.query.filter_by(public_id=public_id.upper()).first_or_404()
    title = LandTitle.query.filter_by(parcel_id=p.id).first()
    if not title:
        flash("Aucun titre numerique pour cette parcelle.", "info")
        return redirect(url_for("parcel_detail", public_id=p.public_id))
    return render_template("title_detail.html", parcel=p, title=title)


@app.route("/titre/<public_id>/pdf")
def title_pdf(public_id):
    p = Parcel.query.filter_by(public_id=public_id.upper()).first_or_404()
    title = LandTitle.query.filter_by(parcel_id=p.id).first_or_404()
    pdf = FPDF()
    pdf.add_page()
    pdf.set_font("Helvetica", size=14)
    pdf.cell(0, 10, "Sassandra Foncier - Extrait titre (demo)", ln=1)
    pdf.set_font("Helvetica", size=11)
    pdf.cell(0, 8, f"Reference : {title.reference_no}", ln=1)
    pdf.cell(0, 8, f"Parcelle : {p.public_id}", ln=1)
    pdf.cell(0, 8, f"Hash authenticite : {title.authenticity_hash[:16]}...", ln=1)
    data = pdf.output()
    if isinstance(data, str):
        data = data.encode("latin-1")
    elif isinstance(data, bytearray):
        data = bytes(data)
    return send_file(
        io.BytesIO(data),
        mimetype="application/pdf",
        as_attachment=True,
        download_name=f"titre-{p.public_id}.pdf",
    )


@app.route("/titre/verifier", methods=["GET", "POST"])
def title_verify():
    result = None
    if request.method == "POST":
        ref = (request.form.get("reference") or "").strip()
        h = (request.form.get("hash") or "").strip().lower()
        t = LandTitle.query.filter_by(reference_no=ref).first()
        if t and h == t.authenticity_hash.lower():
            result = "ok"
        else:
            result = "bad"
    return render_template("title_verify.html", result=result)


@app.route("/demandes")
@login_required
def requests_list():
    uid = session["user_id"]
    user_requests = AdminRequest.query.filter_by(user_id=uid).order_by(AdminRequest.created_at.desc()).all()
    return render_template("requests_list.html", user_requests=user_requests)


@app.route("/demandes/nouvelle", methods=["GET", "POST"])
@login_required
def requests_new():
    uid = session["user_id"]
    types = [
        ("mutation", "Mutation"),
        ("verification", "Verification"),
        ("plainte", "Plainte"),
    ]
    if request.method == "POST":
        rt = request.form.get("request_type") or "verification"
        subject = (request.form.get("subject") or "").strip()
        body = (request.form.get("body") or "").strip()
        parcel_pid = (request.form.get("parcel_public_id") or "").strip().upper() or None
        if not subject or not body:
            flash("Sujet et detail requis.", "error")
        else:
            code = "DEM-" + secrets.token_hex(4).upper()
            r = AdminRequest(
                reference_code=code,
                user_id=uid,
                request_type=rt,
                parcel_public_id=parcel_pid,
                subject=subject,
                body=body,
                status="submitted",
            )
            db.session.add(r)
            log_audit(uid, "demande cree", "AdminRequest", code, subject)
            db.session.commit()
            flash(f"Dossier enregistre. Reference : {code}", "success")
            return redirect(url_for("request_track", ref=code))
    return render_template("requests_new.html", types=types)


@app.route("/demandes/suivi/<ref>")
def request_track(ref):
    r = AdminRequest.query.filter_by(reference_code=ref.upper()).first_or_404()
    return render_template("request_track.html", req=r)


@app.route("/carte")
def map_sig():
    parcels = Parcel.query.all()
    geo = [{"id": p.public_id, "lat": p.lat, "lng": p.lng} for p in parcels]
    focus = (request.args.get("focus") or "").strip().upper()
    return render_template(
        "map_sig.html",
        parcels_json=json.dumps(geo),
        focus_public_id=focus,
    )


@app.route("/vente")
def listings_list():
    lst = Listing.query.filter(Listing.status == "published").order_by(Listing.created_at.desc()).all()
    first_thumb = {}
    if lst:
        ids = [x.id for x in lst]
        imgs = (
            ListingImage.query.filter(ListingImage.listing_id.in_(ids))
            .order_by(ListingImage.listing_id, ListingImage.sort_order)
            .all()
        )
        for im in imgs:
            if im.listing_id not in first_thumb:
                first_thumb[im.listing_id] = url_for("static", filename=im.filename)
    return render_template("listings_list.html", listings=lst, first_thumb=first_thumb)


@app.route("/vente/nouvelle", methods=["GET", "POST"])
@login_required
def listing_new():
    uid = session["user_id"]
    if request.method == "POST":
        title = (request.form.get("title") or "").strip()
        description = (request.form.get("description") or "").strip()
        parcel_pid = (request.form.get("parcel_public_id") or "").strip().upper() or None
        price = request.form.get("price_cfa")
        lat = request.form.get("lat")
        lng = request.form.get("lng")
        try:
            price_cfa = int(price) if price else None
        except ValueError:
            price_cfa = None
        try:
            lat_f = float(lat) if lat else None
            lng_f = float(lng) if lng else None
        except ValueError:
            lat_f = lng_f = None
        ensure_listing_upload_dir()
        raw_files = request.files.getlist("images")
        staged = collect_valid_listing_uploads(raw_files)
        if not title:
            flash("Titre requis.", "error")
        elif not staged:
            if any(f and getattr(f, "filename", None) for f in raw_files):
                flash(
                    "Les fichiers choisis ne sont pas au bon format. Utilisez JPG, PNG, WEBP ou GIF "
                    "(sur iPhone : réglages appareil photo → Formats → « Le plus compatible » pour du JPEG).",
                    "error",
                )
            else:
                flash(
                    "Ajoutez au moins une photo du bien dans la zone orange en haut du formulaire (JPG, PNG, WEBP ou GIF).",
                    "error",
                )
        else:
            l = Listing(
                user_id=uid,
                title=title,
                description=description or None,
                parcel_public_id=parcel_pid,
                price_cfa=price_cfa,
                lat=lat_f,
                lng=lng_f,
                status="pending_validation",
            )
            db.session.add(l)
            db.session.flush()
            try:
                for i, (f, ext) in enumerate(staged):
                    fn = f"{l.id}_{secrets.token_hex(8)}.{ext}"
                    rel = f"{LISTING_UPLOAD_REL}/{fn}".replace("\\", "/")
                    abs_path = os.path.join(BASE_DIR, "static", *rel.split("/"))
                    f.save(abs_path)
                    db.session.add(ListingImage(listing_id=l.id, filename=rel, sort_order=i))
                log_audit(uid, "annonce creee", "Listing", str(l.id), title)
                db.session.commit()
            except OSError:
                db.session.rollback()
                flash(
                    "Impossible d'enregistrer les fichiers sur le serveur (disque plein ou dossier protégé). "
                    "Réessayez plus tard ou contactez l'administrateur.",
                    "error",
                )
                return render_template("listing_new.html")
            flash("Annonce et photos enregistrees. Validation par un agent avant publication.", "success")
            return redirect(url_for("listings_list"))
    return render_template("listing_new.html")


@app.route("/vente/<int:listing_id>")
def listing_detail(listing_id):
    l = Listing.query.get_or_404(listing_id)
    uid = session.get("user_id")
    comments = []
    like_count = 0
    user_liked = False
    if l.status == "published":
        comments = (
            ListingComment.query.filter_by(listing_id=l.id)
            .order_by(ListingComment.created_at.desc())
            .all()
        )
        like_count = ListingLike.query.filter_by(listing_id=l.id).count()
        if uid:
            user_liked = ListingLike.query.filter_by(listing_id=l.id, user_id=uid).first() is not None
    publisher = l.user
    publisher_label = (
        publisher.company_profile.company_name
        if getattr(publisher, "company_profile", None)
        else publisher.full_name
    )
    imgs = (
        ListingImage.query.filter_by(listing_id=l.id)
        .order_by(ListingImage.sort_order, ListingImage.id)
        .all()
    )
    listing_image_urls = [url_for("static", filename=im.filename) for im in imgs]
    return render_template(
        "listing_detail.html",
        listing=l,
        comments=comments,
        like_count=like_count,
        user_liked=user_liked,
        publisher_label=publisher_label,
        listing_image_urls=listing_image_urls,
    )


@app.route("/vente/<int:listing_id>/commenter", methods=["POST"])
@login_required
def listing_comment(listing_id):
    l = Listing.query.get_or_404(listing_id)
    if l.status != "published":
        flash("Les commentaires sont disponibles sur les annonces publiees uniquement.", "error")
        return redirect(url_for("listing_detail", listing_id=listing_id))
    body = (request.form.get("body") or "").strip()
    if not body:
        flash("Saisissez un message.", "error")
    else:
        db.session.add(
            ListingComment(listing_id=l.id, user_id=session["user_id"], body=body)
        )
        log_audit(session["user_id"], "commentaire annonce", "Listing", str(l.id), None)
        db.session.commit()
        flash("Commentaire publie.", "success")
    return redirect(url_for("listing_detail", listing_id=listing_id))


@app.route("/vente/<int:listing_id>/like", methods=["POST"])
@login_required
def listing_like(listing_id):
    l = Listing.query.get_or_404(listing_id)
    if l.status != "published":
        flash("Les reactions sont disponibles sur les annonces publiees uniquement.", "error")
        return redirect(url_for("listing_detail", listing_id=listing_id))
    uid = session["user_id"]
    existing = ListingLike.query.filter_by(listing_id=l.id, user_id=uid).first()
    if existing:
        db.session.delete(existing)
        flash("Like retire.", "info")
    else:
        db.session.add(ListingLike(listing_id=l.id, user_id=uid))
        flash("Merci pour votre interet.", "success")
    db.session.commit()
    return redirect(url_for("listing_detail", listing_id=listing_id))


@app.route("/admin")
@role_required("admin", "agent")
def admin_dashboard():
    n_parcels = Parcel.query.count()
    n_req = AdminRequest.query.filter_by(status="submitted").count()
    n_list = Listing.query.filter_by(status="pending_validation").count()
    return render_template("admin_dashboard.html", n_parcels=n_parcels, n_req=n_req, n_list=n_list)


@app.route("/admin/agents")
@role_required("admin")
def admin_agents():
    agents = User.query.filter(User.role.in_(["agent", "admin"])).all()
    return render_template("admin_agents.html", agents=agents)


@app.route("/admin/validation")
@role_required("admin", "agent")
def admin_validation():
    pending = Listing.query.filter_by(status="pending_validation").order_by(Listing.created_at.desc()).all()
    thumbs = {}
    for row in pending:
        im = (
            ListingImage.query.filter_by(listing_id=row.id)
            .order_by(ListingImage.sort_order, ListingImage.id)
            .first()
        )
        if im:
            thumbs[row.id] = url_for("static", filename=im.filename)
    return render_template("admin_validation.html", listings=pending, thumbs=thumbs)


@app.route("/admin/validation/<int:listing_id>/publier", methods=["POST"])
@role_required("admin", "agent")
def admin_publish_listing(listing_id):
    l = Listing.query.get_or_404(listing_id)
    l.status = "published"
    log_audit(session["user_id"], "annonce publiee", "Listing", str(l.id), l.title)
    db.session.commit()
    flash("Annonce publiee.", "success")
    return redirect(url_for("admin_validation"))


@app.route("/admin/audit")
@role_required("admin")
def admin_audit():
    logs = AuditLog.query.order_by(AuditLog.created_at.desc()).limit(200).all()
    return render_template("admin_audit.html", logs=logs)


@app.route("/admin/statistiques")
@role_required("admin", "agent")
def admin_stats():
    n_users = User.query.count()
    n_parcels = Parcel.query.count()
    n_titles = LandTitle.query.count()
    n_req = AdminRequest.query.count()
    return render_template("admin_stats.html", n_users=n_users, n_parcels=n_parcels, n_titles=n_titles, n_req=n_req)


with app.app_context():
    db.create_all()
    seed_if_empty()
    try:
        ensure_listing_upload_dir()
    except OSError as exc:
        app.logger.warning("Dossier uploads annonces non cree: %s", exc)
