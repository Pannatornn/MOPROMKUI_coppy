import pytest
from sqlalchemy import create_engine
from sqlalchemy.engine import make_url

from app.config import normalize_database_url


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
