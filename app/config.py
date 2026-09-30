import os


def normalize_database_url(url: str) -> str:
    """Use the installed psycopg 3 driver for managed PostgreSQL URLs."""
    for prefix in ("postgres://", "postgresql://"):
        if url.startswith(prefix):
            return "postgresql+psycopg://" + url[len(prefix):]
    return url


class Config:
    APP_ENV = os.getenv("APP_ENV", "development")
    SECRET_KEY = os.getenv("SECRET_KEY", "dev-only-change-me")
    SQLALCHEMY_DATABASE_URI = normalize_database_url(
        os.getenv("DATABASE_URL", "sqlite:///morpromkui.db")
    )
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    SQLALCHEMY_ENGINE_OPTIONS = {"pool_pre_ping": True}
    MAX_CONTENT_LENGTH = 32 * 1024

    SESSION_COOKIE_HTTPONLY = True
    SESSION_COOKIE_SAMESITE = "Lax"
    SESSION_COOKIE_SECURE = APP_ENV == "production"
    PERMANENT_SESSION_LIFETIME = 8 * 60 * 60

    RATELIMIT_STORAGE_URI = os.getenv("RATELIMIT_STORAGE_URI", "memory://")
    RATELIMIT_HEADERS_ENABLED = True

    STAFF_USERNAME = os.getenv("STAFF_USERNAME", "clinic")
    STAFF_PASSWORD = os.getenv("STAFF_PASSWORD", "")
    STAFF_PASSWORD_HASH = os.getenv("STAFF_PASSWORD_HASH", "")
    OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "")
    OPENAI_MODEL = os.getenv("OPENAI_MODEL", "gpt-5.6-terra")
    GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "")
    GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-3.6-flash")
    GEMINI_BASE_URL = os.getenv(
        "GEMINI_BASE_URL", "https://generativelanguage.googleapis.com/v1beta/openai/"
    )
    AI_PROVIDER = os.getenv("AI_PROVIDER", "stub")
    CLINIC_NAME = os.getenv("CLINIC_NAME", "คลินิกตัวอย่าง")
    PRIVACY_CONTACT = os.getenv("PRIVACY_CONTACT", "privacy@example.com")
    DATA_RETENTION_DAYS = int(os.getenv("DATA_RETENTION_DAYS", "30"))
    CONSENT_VERSION = os.getenv("CONSENT_VERSION", "pilot-1.0")
