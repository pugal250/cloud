"""Student Management System - Flask application factory."""
import os
import secrets
from datetime import date, timedelta

from flask import Flask, g, render_template, request, url_for


def _load_secret_key(app):
    """SMS_SECRET_KEY env var wins; otherwise a random key is generated once and kept in instance/."""
    env = os.environ.get("SMS_SECRET_KEY")
    if env:
        return env
    path = os.path.join(app.instance_path, "secret_key")
    if os.path.exists(path):
        with open(path, encoding="utf-8") as fh:
            return fh.read().strip()
    key = secrets.token_hex(32)
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as fh:
        fh.write(key)
    return key


def create_app(test_config=None):
    app = Flask(__name__)
    os.makedirs(app.instance_path, exist_ok=True)

    app.config.from_mapping(
        DATABASE=os.environ.get("SMS_DATABASE", os.path.join(app.instance_path, "sms.sqlite3")),
        UPLOAD_FOLDER=os.environ.get("SMS_UPLOAD_FOLDER", os.path.join(app.instance_path, "uploads")),
        MAX_UPLOAD_BYTES=5 * 1024 * 1024,            # per certificate file
        MAX_CONTENT_LENGTH=6 * 1024 * 1024,          # whole request
        SESSION_COOKIE_HTTPONLY=True,
        SESSION_COOKIE_SAMESITE="Lax",
        SESSION_COOKIE_SECURE=os.environ.get("SMS_COOKIE_SECURE") == "1",  # set to 1 behind HTTPS
        PERMANENT_SESSION_LIFETIME=timedelta(hours=8),
    )
    if test_config:
        app.config.update(test_config)
    if not app.config.get("SECRET_KEY"):
        app.config["SECRET_KEY"] = _load_secret_key(app)
    os.makedirs(app.config["UPLOAD_FOLDER"], exist_ok=True)

    from . import admin, auth, cli, db, files, security, services, staff, student

    db.init_app(app)
    security.init_app(app)

        # Create tables automatically.
    with app.app_context():
        db.init_db()

        connection = db.get_db()
        user_count = connection.execute(
            "SELECT COUNT(*) FROM users"
        ).fetchone()[0]

        if user_count == 0 and os.environ.get("SMS_AUTO_SEED_DEMO") == "1":
            from .seed import seed_demo

            if seed_demo(connection):
                app.logger.info("Demo accounts created successfully.")
        elif user_count == 0:
            app.logger.warning(
                "No users yet. Set SMS_AUTO_SEED_DEMO=1 to load demo accounts."
            )

        db.close_db()
        
    for module in (auth, student, staff, admin, files):
        app.register_blueprint(module.bp)
    cli.register(app)

    # -- template helpers ---------------------------------------------------
    @app.template_filter("d")
    def fmt_date(value):
        if not value:
            return "-"
        try:
            return date.fromisoformat(str(value)[:10]).strftime("%d %b %Y")
        except ValueError:
            return str(value)

    @app.template_filter("pct")
    def fmt_pct(value):
        return "-" if value is None else f"{value:g}%"

    @app.template_filter("num")
    def fmt_num(value):
        return f"{value:g}"

    app.jinja_env.globals["is_low"] = services.is_low
    app.jinja_env.globals["csrf_token"] = security.csrf_token  # globals are visible inside imported macros

    nav = {
        "student": [
            ("student.dashboard", {}, "Dashboard", "grid-fill"),
            ("student.certificates", {}, "Certificates", "patch-check"),
            ("student.completions", {}, "Course completion", "mortarboard"),
            ("student.leaves", {}, "Leave requests", "calendar2-x"),
        ],
        "staff": [
            ("staff.dashboard", {}, "Dashboard", "grid-fill"),
            ("staff.reviews", {"kind": "certificates"}, "Certificates", "patch-check"),
            ("staff.reviews", {"kind": "completions"}, "Course completions", "mortarboard"),
            ("staff.reviews", {"kind": "leaves"}, "Leave requests", "calendar2-x"),
        ],
        "admin": [
            ("admin.dashboard", {}, "Dashboard", "grid-fill"),
            ("admin.students", {}, "Students", "people"),
            ("admin.staff_list", {}, "Staff", "person-badge"),
            ("admin.courses", {}, "Courses & settings", "journal-bookmark"),
            ("admin.attendance", {}, "Attendance & marks", "clipboard-data"),
        ],
    }

    @app.context_processor
    def inject():
        items = []
        if g.get("user") is not None:
            home = url_for(f"{g.user['role']}.dashboard")
            for endpoint, kwargs, label, icon in nav[g.user["role"]]:
                url = url_for(endpoint, **kwargs)
                active = request.path == url if url == home else request.path.startswith(url)
                items.append({"url": url, "label": label, "icon": icon, "active": active})
        return {"nav_items": items, "today": date.today().isoformat()}

    # -- errors -------------------------------------------------------------
    messages = {
        400: ("Request could not be processed", None),
        403: ("Access denied", "You do not have permission to view this page."),
        404: ("Page not found", "The page you asked for does not exist or is not available to you."),
        413: ("Upload too large", "The upload exceeds the maximum allowed size."),
        500: ("Something went wrong", "An unexpected error occurred. Please try again."),
    }

    def make_handler(code):
        def handler(err):
            title, default = messages[code]
            detail = getattr(err, "description", None) if code == 400 else default
            return render_template("error.html", code=code, title=title, detail=detail or default), code

        return handler

    for code in messages:
        app.register_error_handler(code, make_handler(code))

    return app
