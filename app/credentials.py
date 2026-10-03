from __future__ import annotations

import base64
import hashlib

from cryptography.fernet import Fernet, InvalidToken
from flask import current_app

from .extensions import db
from .models import ApiCredential

PROVIDERS = {"openai", "gemini"}


def _cipher() -> Fernet:
    """Derive a database-encryption key from the server-only Flask secret."""
    secret = current_app.config["SECRET_KEY"].encode("utf-8")
    key = base64.urlsafe_b64encode(hashlib.sha256(secret).digest())
    return Fernet(key)


def get_api_key(provider: str) -> str:
    """Return an administrator override when available, otherwise the Render environment value."""
    credential = db.session.scalar(
        db.select(ApiCredential).where(ApiCredential.provider == provider)
    )
    if credential is not None:
        try:
            return _cipher().decrypt(credential.encrypted_key.encode("utf-8")).decode("utf-8")
        except (InvalidToken, UnicodeDecodeError):
            current_app.logger.error("Stored API credential could not be decrypted for provider %s", provider)
    return current_app.config[f"{provider.upper()}_API_KEY"]


def credential_status(provider: str) -> ApiCredential | None:
    return db.session.scalar(db.select(ApiCredential).where(ApiCredential.provider == provider))


def save_api_key(provider: str, api_key: str, updated_by: str) -> None:
    credential = credential_status(provider)
    encrypted_key = _cipher().encrypt(api_key.encode("utf-8")).decode("utf-8")
    if credential is None:
        db.session.add(
            ApiCredential(
                provider=provider,
                encrypted_key=encrypted_key,
                updated_by=updated_by,
            )
        )
    else:
        credential.encrypted_key = encrypted_key
        credential.updated_by = updated_by
    db.session.commit()


def clear_api_key(provider: str) -> bool:
    credential = credential_status(provider)
    if credential is None:
        return False
    db.session.delete(credential)
    db.session.commit()
    return True
