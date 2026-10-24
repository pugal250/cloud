"""Flask CLI commands:  init-db, seed-demo, create-admin."""
import os
import shutil

import click
from flask import current_app

from .db import close_db, get_db, init_db
from .security import hash_password
from .validators import USERNAME_RE, Form


def register(app):
    @app.cli.command("init-db")
    @click.option("--reset", is_flag=True, help="Delete the existing database and uploads first.")
    def init_db_command(reset):
        """Create the SQLite tables."""
        if reset:
            close_db()
            path = current_app.config["DATABASE"]
            if os.path.exists(path):
                os.remove(path)
            shutil.rmtree(current_app.config["UPLOAD_FOLDER"], ignore_errors=True)
            os.makedirs(current_app.config["UPLOAD_FOLDER"], exist_ok=True)
        init_db()
        click.echo("Database ready at " + current_app.config["DATABASE"])

    @app.cli.command("seed-demo")
    def seed_demo_command():
        """Load demo accounts, courses, attendance, marks and sample submissions."""
        from .seed import seed_demo

        init_db()
        if seed_demo(get_db()):
            click.echo("Demo data created. See README for the demo logins.")
        else:
            click.echo("Demo data already exists - nothing changed. (Use: flask --app sms init-db --reset)")

    @app.cli.command("create-admin")
    @click.option("--username", prompt=True)
    @click.option("--email", prompt=True)
    @click.option("--name", "full_name", prompt="Full name")
    @click.password_option()
    def create_admin_command(username, email, full_name, password):
        """Create an administrator account."""
        init_db()
        form = Form({"username": username, "email": email, "full_name": full_name, "password": password})
        form.text("username", "Username", regex=USERNAME_RE, message="Username must be 3-30 letters, numbers, . - _")
        form.email()
        form.text("full_name", "Full name", min_len=2, max_len=100)
        form.password()
        if not form.ok:
            raise click.ClickException(form.first_error())
        db = get_db()
        if db.execute("SELECT 1 FROM users WHERE username = ? OR email = ?", (username, email)).fetchone():
            raise click.ClickException("That username or email already exists.")
        with db:
            db.execute(
                "INSERT INTO users (username, email, full_name, password_hash, role) VALUES (?, ?, ?, ?, 'admin')",
                (username, form.values["email"], full_name, hash_password(password)),
            )
        click.echo(f"Admin '{username}' created.")
