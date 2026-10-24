from flask import Blueprint, flash, g, redirect, render_template, request, session, url_for

from .db import get_db
from .security import burn_password_check, home_url_for, verify_password

bp = Blueprint("auth", __name__)


@bp.get("/")
def index():
    if g.user:
        return redirect(home_url_for(g.user["role"]))
    return redirect(url_for("auth.login"))


@bp.route("/login", methods=["GET", "POST"])
def login():
    if g.user and request.method == "GET":
        return redirect(home_url_for(g.user["role"]))

    username = ""
    if request.method == "POST":
        username = (request.form.get("username") or "").strip()[:60]
        password = request.form.get("password") or ""
        db = get_db()
        user = db.execute(
            "SELECT id, role, password_hash, is_active FROM users WHERE username = ?", (username,)
        ).fetchone()

        if user is None:
            burn_password_check(password)
        if user is None or not verify_password(user["password_hash"], password):
            flash("Incorrect username or password.", "danger")
            return render_template("auth/login.html", username=username), 401
        if not user["is_active"]:
            flash("This account is disabled. Contact an administrator.", "danger")
            return render_template("auth/login.html", username=username), 403

        session.clear()                      # new session on login (prevents fixation)
        session["user_id"] = user["id"]
        session.permanent = True
        with db:
            db.execute("UPDATE users SET last_login_at = datetime('now') WHERE id = ?", (user["id"],))
        return redirect(home_url_for(user["role"]))

    return render_template("auth/login.html", username=username)


@bp.post("/logout")
def logout():
    session.clear()
    flash("You have been signed out.", "success")
    return redirect(url_for("auth.login"))
