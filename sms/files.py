"""Authorised access to uploaded certificate files (never served from a public folder)."""
import os

from flask import Blueprint, abort, current_app, g, send_from_directory

from .db import get_db
from .services import KINDS
from .security import MIME_BY_EXT

bp = Blueprint("files", __name__, url_prefix="/files")


@bp.get("/<kind>/<int:item_id>")
def download(kind, item_id):
    if g.user is None:
        abort(403)
    if kind not in ("certificates", "completions"):
        abort(404)
    table = KINDS[kind]["table"]
    db = get_db()
    row = db.execute(
        f"SELECT x.stored_filename, x.original_filename, s.user_id AS owner_id, s.staff_id "
        f"FROM {table} x JOIN students s ON s.id = x.student_id WHERE x.id = ?",
        (item_id,),
    ).fetchone()
    if row is None:
        abort(404)

    role = g.user["role"]
    allowed = False
    if role == "admin":
        allowed = True
    elif role == "student":
        allowed = row["owner_id"] == g.user["id"]          # only your own files
    elif role == "staff":
        me = db.execute("SELECT id FROM staff WHERE user_id = ?", (g.user["id"],)).fetchone()
        allowed = me is not None and row["staff_id"] == me["id"]  # only assigned students
    if not allowed:
        abort(404)  # do not reveal that the file exists

    stored = row["stored_filename"]
    ext = stored.rsplit(".", 1)[-1].lower()
    return send_from_directory(
        current_app.config["UPLOAD_FOLDER"],
        os.path.basename(stored),
        mimetype=MIME_BY_EXT.get(ext, "application/octet-stream"),
        download_name=row["original_filename"],
        as_attachment=False,
    )
