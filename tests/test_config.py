import pytest
from sqlalchemy import create_engine
from sqlalchemy.engine import make_url
from werkzeug.security import check_password_hash, generate_password_hash

from app import create_app
from app.config import normalize_database_url
from app.extensions import db
from app.models import StaffUser


@pytest.mark.parametrize("scheme", ["postgres", "postgresql"])
def test_managed_postgres_url_selects_installed_driver(scheme):
    original = f"{scheme}://demo:p%40ss%2Fword@db.example:5432/demo?sslmode=require"
    normalized = normalize_database_url(original)
    parsed = make_url(normalized)
    assert parsed.drivername == "postgresql+psycopg"
    assert parsed.password == "p@ss/word"
    assert parsed.host == "db.example"
    assert parsed.port == 5432
    assert parsed.database == "demo"
    assert parsed.query["sslmode"] == "require"
    # Load the actual DBAPI without opening a network connection.
    engine = create_engine(normalized)
    assert engine.dialect.driver == "psycopg"
    engine.dispose()


@pytest.mark.parametrize(
    "url",
    [
        "sqlite:///morpromkui.db",
        "sqlite:///:memory:",
        "postgresql+psycopg://demo:password@db:5432/demo",
        "postgresql+psycopg2://demo:password@db:5432/demo",
    ],
)
def test_explicit_drivers_and_local_database_are_preserved(url):
    assert normalize_database_url(url) == url


def test_production_plain_staff_password_is_hashed_before_storage(tmp_path):
    password = "RenderDemoPassword2026!"
    app = create_app(
        {
            "APP_ENV": "production",
            "SECRET_KEY": "production-secret-key-that-is-at-least-32-characters",
            "SQLALCHEMY_DATABASE_URI": f"sqlite:///{tmp_path / 'production.sqlite'}",
            "STAFF_USERNAME": "demo-admin",
            "STAFF_PASSWORD": password,
            "STAFF_PASSWORD_HASH": "",
            "RATELIMIT_ENABLED": False,
        }
    )
    with app.app_context():
        db.create_all()
    result = app.test_cli_runner().invoke(args=["ensure-admin"])
    assert result.exit_code == 0
    with app.app_context():
        user = db.session.scalar(db.select(StaffUser).where(StaffUser.username == "demo-admin"))
        assert user is not None
        assert user.password_hash != password
        assert check_password_hash(user.password_hash, password)


def test_plain_staff_password_updates_existing_configured_user(tmp_path):
    old_password = "PreviousPassword2026!"
    new_password = "UpdatedRenderPassword2026!"
    app = create_app(
        {
            "APP_ENV": "production",
            "SECRET_KEY": "production-secret-key-that-is-at-least-32-characters",
            "SQLALCHEMY_DATABASE_URI": f"sqlite:///{tmp_path / 'existing.sqlite'}",
            "STAFF_USERNAME": "demo-admin",
            "STAFF_PASSWORD": new_password,
            "STAFF_PASSWORD_HASH": "",
            "RATELIMIT_ENABLED": False,
        }
    )
    with app.app_context():
        db.create_all()
        db.session.add(
            StaffUser(
                username="demo-admin",
                display_name="ผู้ดูแลระบบ",
                password_hash=generate_password_hash(old_password, method="scrypt"),
                role="admin",
                is_active=True,
            )
        )
        db.session.commit()

    result = app.test_cli_runner().invoke(args=["ensure-admin"])

    assert result.exit_code == 0
    assert "credentials synchronized" in result.output
    with app.app_context():
        user = db.session.scalar(db.select(StaffUser).where(StaffUser.username == "demo-admin"))
        assert user is not None
        assert check_password_hash(user.password_hash, new_password)
        assert not check_password_hash(user.password_hash, old_password)


def test_production_rejects_short_plain_staff_password(tmp_path):
    with pytest.raises(RuntimeError, match="STAFF_PASSWORD must be at least 14 characters"):
        create_app(
            {
                "APP_ENV": "production",
                "SECRET_KEY": "production-secret-key-that-is-at-least-32-characters",
                "SQLALCHEMY_DATABASE_URI": f"sqlite:///{tmp_path / 'production.sqlite'}",
                "STAFF_PASSWORD": "too-short",
                "STAFF_PASSWORD_HASH": "",
            }
        )
