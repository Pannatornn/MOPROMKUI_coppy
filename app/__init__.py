from __future__ import annotations

from datetime import datetime, timedelta, timezone
import json
import os
from zoneinfo import ZoneInfo

import click
from flask import Flask, jsonify, render_template
from werkzeug.security import check_password_hash, generate_password_hash
from werkzeug.middleware.proxy_fix import ProxyFix

from .config import Config
from .extensions import db, limiter


def _validate_config(app: Flask) -> None:
    if app.config["APP_ENV"] != "production" or app.config.get("TESTING"):
        return
    problems = []
    if app.config["SECRET_KEY"] in {"", "dev-only-change-me"} or len(app.config["SECRET_KEY"]) < 32:
        problems.append("SECRET_KEY must be a random value of at least 32 characters")
    password_hash = app.config["STAFF_PASSWORD_HASH"]
    password = app.config["STAFF_PASSWORD"]
    has_password_hash = bool(password_hash) and not password_hash.startswith("CHANGE_ME")
    has_plain_password = (
        bool(password) and not password.startswith("CHANGE_ME") and len(password) >= 14
    )
    if not has_password_hash and not has_plain_password:
        problems.append(
            "STAFF_PASSWORD must be at least 14 characters or STAFF_PASSWORD_HASH must be generated"
        )
    if "CHANGE_ME" in os.getenv("DATABASE_URL", ""):
        problems.append("DATABASE_URL still contains CHANGE_ME")
    if problems:
        raise RuntimeError("Unsafe production configuration: " + "; ".join(problems))


def create_app(test_config: dict | None = None) -> Flask:
    app = Flask(__name__)
    app.config.from_object(Config)
    # Read-only API traffic must not refresh a stale authentication cookie.
    # Patient case authorization uses X-Case-Token, never the staff session.
    from flask.sessions import SecureCookieSessionInterface
    from flask import request
    class CaseSessionInterface(SecureCookieSessionInterface):
        def save_session(self, app, session, response):
            if request.path.startswith('/api/cases'):
                return
            super().save_session(app, session, response)
    app.session_interface = CaseSessionInterface()
    if test_config:
        app.config.update(test_config)
    _validate_config(app)

    app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1)  # type: ignore[method-assign]
    db.init_app(app)
    limiter.init_app(app)

    from . import routes

    routes.init_app(app)
    from . import appointments
    appointments.init_app(app)

    @app.after_request
    def security_headers(response):
        response.headers.setdefault(
            "Content-Security-Policy",
            "default-src 'self'; script-src 'self'; style-src 'self' https://cdn.jsdelivr.net; "
            "font-src 'self' https://cdn.jsdelivr.net; img-src 'self' data:; connect-src 'self'; "
            "frame-ancestors 'none'; base-uri 'self'; form-action 'self'",
        )
        response.headers.setdefault("Cache-Control", "no-store")
        response.headers.setdefault("X-Content-Type-Options", "nosniff")
        response.headers.setdefault("X-Frame-Options", "DENY")
        response.headers.setdefault("Referrer-Policy", "no-referrer")
        return response

    from .case_display import summary_is_current

    @app.context_processor
    def inject_branding():
        return {
            "clinic_name": app.config["CLINIC_NAME"],
            "summary_is_current": summary_is_current,
            "privacy_contact": app.config["PRIVACY_CONTACT"],
        }

    @app.template_filter("pretty_json")
    def pretty_json(value):
        return json.dumps(value or {}, ensure_ascii=False, indent=2)

    @app.template_filter("bangkok_time")
    def bangkok_time(value, format_string="%d/%m/%Y %H:%M"):
        if value is None:
            return "—"
        if value.tzinfo is None:
            value = value.replace(tzinfo=timezone.utc)
        return value.astimezone(ZoneInfo("Asia/Bangkok")).strftime(format_string)

    @app.errorhandler(401)
    def unauthorized(_error):
        return render_template("401.html"), 401

    @app.errorhandler(404)
    def not_found(_error):
        if request_prefers_json():
            return jsonify({"error": "ไม่พบข้อมูล"}), 404
        return render_template("404.html"), 404

    @app.errorhandler(403)
    def forbidden(_error):
        return render_template("403.html"), 403

    @app.cli.command("init-db")
    def init_db_command():
        db.create_all()
        click.echo("Database is ready.")

    @app.cli.command("ensure-admin")
    def ensure_admin_command():
        from .models import StaffUser

        username = app.config["STAFF_USERNAME"].strip().casefold()
        plain_password = app.config["STAFF_PASSWORD"]
        password_hash = app.config["STAFF_PASSWORD_HASH"]
        if not password_hash or password_hash.startswith("CHANGE_ME"):
            password_hash = generate_password_hash(plain_password, method="scrypt")
        user = db.session.scalar(db.select(StaffUser).where(StaffUser.username == username))
        if user is None:
            db.session.add(
                StaffUser(
                    username=username,
                    display_name="ผู้ดูแลระบบ",
                    password_hash=password_hash,
                    role="admin",
                    is_active=True,
                )
            )
            db.session.commit()
            click.echo(f"Admin user {username} created.")
            return
        password_changed = bool(plain_password) and not check_password_hash(
            user.password_hash, plain_password
        )
        if password_changed:
            user.password_hash = password_hash
        active_admin = db.session.scalar(
            db.select(StaffUser).where(StaffUser.role == "admin", StaffUser.is_active.is_(True))
        )
        if active_admin is None:
            user.role = "admin"
            user.is_active = True
        if password_changed or active_admin is None:
            db.session.commit()
            click.echo(f"Admin credentials synchronized for {username}.")
            return
        click.echo("Admin user is ready.")

    @app.cli.command("purge-expired")
    def purge_expired_command():
        from .models import Case

        cutoff = datetime.now(timezone.utc) - timedelta(days=app.config["DATA_RETENTION_DAYS"])
        expired = db.session.scalars(db.select(Case).where(Case.created_at < cutoff)).all()
        for case in expired:
            db.session.delete(case)
        db.session.commit()
        click.echo(f"Purged {len(expired)} expired cases.")

    return app


def request_prefers_json() -> bool:
    from flask import request

    return request.path.startswith("/api/")
