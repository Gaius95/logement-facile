from datetime import datetime, timezone

from flask_sqlalchemy import SQLAlchemy
from werkzeug.security import check_password_hash, generate_password_hash

db = SQLAlchemy()


def utcnow():
    return datetime.now(timezone.utc)


class User(db.Model):
    __tablename__ = "users"

    id = db.Column(db.Integer, primary_key=True)
    email = db.Column(db.String(120), unique=True, nullable=False, index=True)
    password_hash = db.Column(db.String(256), nullable=False)
    full_name = db.Column(db.String(160), nullable=False)
    phone = db.Column(db.String(40), nullable=True)
    role = db.Column(db.String(20), nullable=False, default="user")
    identity_verified = db.Column(db.Boolean, default=False)
    created_at = db.Column(db.DateTime, default=utcnow)

    def set_password(self, pw: str) -> None:
        self.password_hash = generate_password_hash(pw)

    def check_password(self, pw: str) -> bool:
        return check_password_hash(self.password_hash, pw)


class Parcel(db.Model):
    __tablename__ = "parcels"

    id = db.Column(db.Integer, primary_key=True)
    public_id = db.Column(db.String(40), unique=True, nullable=False, index=True)
    commune = db.Column(db.String(80), nullable=False)
    quartier = db.Column(db.String(80), nullable=False)
    owner_display = db.Column(db.String(200), nullable=True)
    status = db.Column(db.String(30), nullable=False)
    usage = db.Column(db.String(40), nullable=False)
    area_m2 = db.Column(db.Float, nullable=False)
    lat = db.Column(db.Float, nullable=False)
    lng = db.Column(db.Float, nullable=False)
    created_at = db.Column(db.DateTime, default=utcnow)
    history_events = db.relationship("ParcelHistory", backref="parcel", lazy="dynamic")


class ParcelHistory(db.Model):
    __tablename__ = "parcel_history"

    id = db.Column(db.Integer, primary_key=True)
    parcel_id = db.Column(db.Integer, db.ForeignKey("parcels.id"), nullable=False)
    label = db.Column(db.String(120), nullable=False)
    detail = db.Column(db.Text, nullable=True)
    created_at = db.Column(db.DateTime, default=utcnow)


class LandTitle(db.Model):
    __tablename__ = "land_titles"

    id = db.Column(db.Integer, primary_key=True)
    parcel_id = db.Column(db.Integer, db.ForeignKey("parcels.id"), nullable=False)
    reference_no = db.Column(db.String(120), unique=True, nullable=False)
    authenticity_hash = db.Column(db.String(64), nullable=False)
    issued_at = db.Column(db.DateTime, nullable=False)
    parcel = db.relationship("Parcel", backref=db.backref("titles", lazy="dynamic"))


class AdminRequest(db.Model):
    __tablename__ = "admin_requests"

    id = db.Column(db.Integer, primary_key=True)
    reference_code = db.Column(db.String(24), unique=True, nullable=False, index=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False)
    request_type = db.Column(db.String(30), nullable=False)
    parcel_public_id = db.Column(db.String(40), nullable=True)
    subject = db.Column(db.String(200), nullable=False)
    body = db.Column(db.Text, nullable=False)
    status = db.Column(db.String(30), nullable=False, default="submitted")
    created_at = db.Column(db.DateTime, default=utcnow)
    user = db.relationship("User", backref=db.backref("requests", lazy="dynamic"))


class CompanyProfile(db.Model):
    __tablename__ = "company_profiles"

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), unique=True, nullable=False)
    company_name = db.Column(db.String(200), nullable=False)
    siege = db.Column(db.String(300), nullable=False)
    ville = db.Column(db.String(120), nullable=False)
    registre_commerce = db.Column(db.String(120), nullable=False)
    user = db.relationship("User", backref=db.backref("company_profile", uselist=False))


class Listing(db.Model):
    __tablename__ = "listings"

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False)
    title = db.Column(db.String(200), nullable=False)
    description = db.Column(db.Text, nullable=True)
    parcel_public_id = db.Column(db.String(40), nullable=True)
    price_cfa = db.Column(db.Integer, nullable=True)
    lat = db.Column(db.Float, nullable=True)
    lng = db.Column(db.Float, nullable=True)
    status = db.Column(db.String(30), nullable=False, default="pending_validation")
    created_at = db.Column(db.DateTime, default=utcnow)
    user = db.relationship("User", backref=db.backref("listings", lazy="dynamic"))


class ListingComment(db.Model):
    __tablename__ = "listing_comments"

    id = db.Column(db.Integer, primary_key=True)
    listing_id = db.Column(db.Integer, db.ForeignKey("listings.id"), nullable=False, index=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False)
    body = db.Column(db.Text, nullable=False)
    created_at = db.Column(db.DateTime, default=utcnow)
    listing = db.relationship("Listing", backref=db.backref("comments", lazy="dynamic"))
    user = db.relationship("User", backref=db.backref("listing_comments_posted", lazy="dynamic"))


class ListingLike(db.Model):
    __tablename__ = "listing_likes"

    id = db.Column(db.Integer, primary_key=True)
    listing_id = db.Column(db.Integer, db.ForeignKey("listings.id"), nullable=False, index=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False)
    created_at = db.Column(db.DateTime, default=utcnow)
    listing = db.relationship("Listing", backref=db.backref("likes", lazy="dynamic"))
    user = db.relationship("User", backref=db.backref("listing_likes_given", lazy="dynamic"))

    __table_args__ = (db.UniqueConstraint("listing_id", "user_id", name="uq_listing_like_user"),)


class AuditLog(db.Model):
    __tablename__ = "audit_logs"

    id = db.Column(db.Integer, primary_key=True)
    actor_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=True)
    action = db.Column(db.String(120), nullable=False)
    target_type = db.Column(db.String(40), nullable=True)
    target_id = db.Column(db.String(40), nullable=True)
    detail = db.Column(db.Text, nullable=True)
    created_at = db.Column(db.DateTime, default=utcnow)
    actor = db.relationship("User", backref=db.backref("audit_actions", lazy="dynamic"))
