"""CSRF, role guards, password hashing, and upload validation."""
import hmac
import os
import secrets
import uuid

from flask import abort, current_app, flash, g, redirect, request, session, url_for
from werkzeug.security import check_password_hash, generate_password_hash
from werkzeug.utils import secure_filename

from .db import get_db

# --------------------------------------------------------------------------
# Passwords
# --------------------------------------------------------------------------
# pbkdf2 is used explicitly because it works on every Python build.
_HASH_METHOD = "pbkdf2:sha256"
_dummy_hash = None


def hash_password(password):
    return generate_password_hash(password, method=_HASH_METHOD)


def verify_password(stored_hash, password):
    return check_password_hash(stored_hash, password)


def burn_password_check(password):
    """Spend roughly the same time when the username does not exist."""
    global _dummy_hash
    if _dummy_hash is None:
        _dummy_hash = hash_password(secrets.token_hex(8))
    check_password_hash(_dummy_hash, password)


# --------------------------------------------------------------------------
# Session user + CSRF (run before every request)
# --------------------------------------------------------------------------
def csrf_token():
    token = session.get("_csrf")
    if not token:
        token = secrets.token_urlsafe(32)
        session["_csrf"] = token
    return token


def _load_user():
    g.user = None
    uid = session.get("user_id")
    if uid is None:
        return
    row = get_db().execute(
        "SELECT id, username, full_name, email, role, is_active FROM users WHERE id = ?", (uid,)
    ).fetchone()
    if row is not None and row["is_active"]:
        g.user = row
    else:
        session.clear()


def _check_csrf():
    if request.method in ("GET", "HEAD", "OPTIONS"):
        return
    sent = request.form.get("csrf_token") or request.headers.get("X-CSRF-Token", "")
    expected = session.get("_csrf", "")
    if not expected or not hmac.compare_digest(sent.encode(), expected.encode()):
        abort(400, description="Your session expired or the form token was invalid. Reload the page and try again.")


def _security_headers(response):
    response.headers.setdefault("X-Content-Type-Options", "nosniff")
    response.headers.setdefault("X-Frame-Options", "DENY")
    response.headers.setdefault("Referrer-Policy", "same-origin")
    response.headers.setdefault(
        "Content-Security-Policy",
        "default-src 'self'; img-src 'self' data:; object-src 'self'; base-uri 'self'; "
        "form-action 'self'; frame-ancestors 'none'",
    )
    if request.endpoint != "static":
        response.headers.setdefault("Cache-Control", "no-store")
    return response


def init_app(app):
    @app.before_request
    def _before():
        _load_user()
        _check_csrf()

    app.after_request(_security_headers)


# --------------------------------------------------------------------------
# Role guards
# --------------------------------------------------------------------------
def home_url_for(role):
    return url_for(f"{role}.dashboard")


def require_role(role):
    """Use inside blueprint.before_request. Returns a response to short-circuit, or None."""
    if g.user is None:
        flash("Please sign in to continue.", "warning")
        return redirect(url_for("auth.login"))
    if g.user["role"] != role:
        abort(403)
    return None


# --------------------------------------------------------------------------
# File uploads
# --------------------------------------------------------------------------
ALLOWED_SIGNATURES = {
    "pdf": (b"%PDF-",),
    "png": (b"\x89PNG\r\n\x1a\n",),
    "jpg": (b"\xff\xd8\xff",),
    "jpeg": (b"\xff\xd8\xff",),
}
MIME_BY_EXT = {"pdf": "application/pdf", "png": "image/png", "jpg": "image/jpeg", "jpeg": "image/jpeg"}


class UploadError(Exception):
    pass


def save_upload(file_storage, label="File"):
    """Validate and store an uploaded certificate. Returns (stored_name, original_name).

    * extension must be pdf/png/jpg/jpeg AND the file's leading bytes must match
    * size limited by MAX_UPLOAD_BYTES
    * stored under a random name; the user's filename is only kept (sanitised) for display
    """
    if file_storage is None or not file_storage.filename:
        raise UploadError(f"{label} is required.")
    raw_name = file_storage.filename
    ext = raw_name.rsplit(".", 1)[-1].lower() if "." in raw_name else ""
    if ext not in ALLOWED_SIGNATURES:
        raise UploadError("Only PDF, PNG or JPG files are allowed.")

    stream = file_storage.stream
    head = stream.read(16)
    stream.seek(0, os.SEEK_END)
    size = stream.tell()
    stream.seek(0)
    if size == 0:
        raise UploadError("The uploaded file is empty.")
    max_bytes = current_app.config["MAX_UPLOAD_BYTES"]
    if size > max_bytes:
        raise UploadError(f"The file is too large (limit {max_bytes // (1024 * 1024)} MB).")
    if not any(head.startswith(sig) for sig in ALLOWED_SIGNATURES[ext]):
        raise UploadError("The file content does not match its extension.")

    stored = f"{uuid.uuid4().hex}.{ext}"
    folder = current_app.config["UPLOAD_FOLDER"]
    os.makedirs(folder, exist_ok=True)
    file_storage.save(os.path.join(folder, stored))
    display = secure_filename(raw_name) or f"upload.{ext}"
    return stored, display[:120]


def remove_uploads(stored_names):
    folder = current_app.config["UPLOAD_FOLDER"]
    for name in stored_names:
        if name and os.path.basename(name) == name:
            try:
                os.remove(os.path.join(folder, name))
            except OSError:
                pass
