import pytest
from werkzeug.security import generate_password_hash

from app import create_app
from app.extensions import db


@pytest.fixture()
def app(tmp_path):
    database_path = tmp_path / "test.sqlite"
    app = create_app(
        {
            "TESTING": True,
            "APP_ENV": "testing",
            "SECRET_KEY": "test-secret-key-that-is-long-enough",
            "SQLALCHEMY_DATABASE_URI": f"sqlite:///{database_path}",
            "STAFF_USERNAME": "nurse",
            "STAFF_PASSWORD_HASH": generate_password_hash("correct-horse-battery", method="scrypt"),
            "AI_PROVIDER": "stub",
            "OPENAI_API_KEY": "",
            "RATELIMIT_ENABLED": False,
        }
    )
    with app.app_context():
        db.create_all()
    result = app.test_cli_runner().invoke(args=["ensure-admin"])
    assert result.exit_code == 0
    yield app
    with app.app_context():
        db.drop_all()


@pytest.fixture()
def client(app):
    return app.test_client()


def create_case(client, complaint="ปวดท้องตั้งแต่เมื่อคืน"):
    return client.post(
        "/api/cases",
        json={
            "age_group": "18-39",
            "sex_at_birth": "female",
            "pregnancy_status": "not_pregnant",
            "chief_complaint": complaint,
            "consent": True,
        },
    )
