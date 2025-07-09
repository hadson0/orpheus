from __future__ import annotations

import json
from functools import lru_cache
from typing import Any, Dict

from cryptography.fernet import Fernet, InvalidToken
from flask import current_app


@lru_cache(maxsize=1)
def _fernet() -> Fernet:
    """Return cached Fernet instance from config key."""
    key = current_app.config.get("FIELD_ENCRYPTION_KEY")
    if not key:
        raise ValueError("FIELD_ENCRYPTION_KEY not configured")
    if isinstance(key, str):
        key = key.encode()
    try:
        return Fernet(key)  # type: ignore[arg-type]
    except Exception as exc:
        raise ValueError(f"Invalid FIELD_ENCRYPTION_KEY: {exc}") from exc


def _log_err(msg: str, exc: Exception) -> None:
    current_app.logger.error("%s – %s", msg, exc)


def encrypt(data: str) -> bytes:
    """Encrypt UTF-8 string to bytes."""
    if not isinstance(data, str):
        raise TypeError(f"Expected str, got {type(data).__name__}")
    if not data:
        raise ValueError("Cannot encrypt empty string")
    try:
        return _fernet().encrypt(data.encode())
    except Exception as exc:
        _log_err("Encryption failed", exc)
        raise


def decrypt(token: bytes) -> str:
    """Decrypt bytes to UTF-8 string."""
    if not isinstance(token, bytes):
        raise TypeError(f"Expected bytes, got {type(token).__name__}")
    if not token:
        raise ValueError("Cannot decrypt empty bytes")
    try:
        return _fernet().decrypt(token).decode()
    except InvalidToken as exc:
        _log_err("Decryption failed: invalid token or key", exc)
        raise ValueError("Invalid token or encryption key mismatch") from exc
    except Exception as exc:
        _log_err("Decryption failed", exc)
        raise


def encrypt_dict(data: Dict[str, Any]) -> bytes:
    """Encrypt dictionary as bytes (JSON)."""
    return encrypt(json.dumps(data))


def decrypt_dict(token: bytes) -> Dict[str, Any]:
    """Decrypt bytes (JSON) to dictionary."""
    return json.loads(decrypt(token))
