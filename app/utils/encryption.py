"""
Encryption utilities for securing sensitive data.

This module provides functions to encrypt and decrypt data using
Fernet symmetric encryption from the cryptography library.
"""

from typing import Union
from cryptography.fernet import Fernet, InvalidToken
from flask import current_app


def get_fernet() -> Fernet:
    """
    Get a Fernet instance using the encryption key from configuration.

    Returns:
        Fernet: A Fernet cipher instance.

    Raises:
        ValueError: If FIELD_ENCRYPTION_KEY is not set or invalid.
    """
    encryption_key = current_app.config.get("FIELD_ENCRYPTION_KEY")

    if not encryption_key:
        raise ValueError("FIELD_ENCRYPTION_KEY not set in configuration.")

    try:
        if isinstance(encryption_key, str):
            encryption_key = encryption_key.encode("utf-8")

        return Fernet(encryption_key)
    except Exception as e:
        raise ValueError(f"Invalid FIELD_ENCRYPTION_KEY: {str(e)}")


def encrypt(data: str) -> bytes:
    """
    Encrypt a string using Fernet symmetric encryption.

    Args:
        data: The string data to encrypt.

    Returns:
        bytes: The encrypted data as bytes.

    Raises:
        ValueError: If encryption key is invalid or missing.
        TypeError: If data is not a string.
    """
    if not isinstance(data, str):
        raise TypeError(f"Expected string, got {type(data).__name__}")

    if not data:
        raise ValueError("Cannot encrypt empty string")

    try:
        fernet = get_fernet()
        encrypted_data = fernet.encrypt(data.encode("utf-8"))
        return encrypted_data
    except Exception as e:
        current_app.logger.error(f"Encryption failed: {str(e)}")
        raise


def decrypt(token: bytes) -> str:
    """
    Decrypt bytes back to the original string.

    Args:
        token: The encrypted bytes to decrypt.

    Returns:
        str: The decrypted string.

    Raises:
        ValueError: If decryption fails (invalid token or key).
        TypeError: If token is not bytes.
    """
    if not isinstance(token, bytes):
        raise TypeError(f"Expected bytes, got {type(token).__name__}")

    if not token:
        raise ValueError("Cannot decrypt empty bytes")

    try:
        fernet = get_fernet()
        decrypted_data = fernet.decrypt(token)
        return decrypted_data.decode("utf-8")
    except InvalidToken:
        current_app.logger.error("Decryption failed: Invalid token or wrong key")
        raise ValueError("Invalid token or encryption key mismatch")
    except Exception as e:
        current_app.logger.error(f"Decryption failed: {str(e)}")
        raise


def encrypt_dict(data: dict) -> bytes:
    """
    Encrypt a dictionary as JSON.

    Args:
        data: Dictionary to encrypt.

    Returns:
        bytes: Encrypted JSON bytes.
    """
    import json

    json_str = json.dumps(data)
    return encrypt(json_str)


def decrypt_dict(token: bytes) -> dict:
    """
    Decrypt bytes back to a dictionary.

    Args:
        token: Encrypted bytes containing JSON.

    Returns:
        dict: The decrypted dictionary.
    """
    import json

    json_str = decrypt(token)
    return json.loads(json_str)


# Context manager for temporary app context
class EncryptionContext:
    """Context manager for encryption operations outside request context."""

    def __init__(self, app):
        self.app = app
        self.ctx = None

    def __enter__(self):
        self.ctx = self.app.app_context()
        self.ctx.push()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.ctx.pop()

    def encrypt(self, data: str) -> bytes:
        return encrypt(data)

    def decrypt(self, token: bytes) -> str:
        return decrypt(token)
