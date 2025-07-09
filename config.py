from __future__ import annotations

"""
Configuration management for Spotify Voice Bridge API.

This module loads environment variables and provides configuration
settings for different deployment environments.
"""


import os
import warnings
from typing import Any, Dict, List, Type

from dotenv import load_dotenv
from flask import Flask
from sqlalchemy import event
from sqlalchemy.engine import Engine

load_dotenv()


def _env(key: str, default: Any | None = None) -> str | None:
    """Get environment variable as string or None."""
    val = os.getenv(key, default)
    return val if val not in ("", None) else None


def _bool_env(key: str, default: bool = False) -> bool:
    """Get environment variable as bool."""
    return (
        (_env(key, str(default)).lower() == "true")
        if _env(key, str(default))
        else default
    )


def _int_env(key: str, default: int) -> int:
    """Get environment variable as int."""
    try:
        return int(_env(key, default))
    except (TypeError, ValueError):
        return default


class BaseConfig:
    """Base settings for all environments."""

    SECRET_KEY: str = _env("SECRET_KEY") or "dev-secret-key-change-me"
    FLASK_APP: str = _env("FLASK_APP", "run.py")
    SQLALCHEMY_DATABASE_URI: str = _env("DATABASE_URL", "sqlite:///project.db")
    SQLALCHEMY_TRACK_MODIFICATIONS: bool = False

    SPOTIFY_CLIENT_ID: str | None = _env("SPOTIFY_CLIENT_ID")
    SPOTIFY_CLIENT_SECRET: str | None = _env("SPOTIFY_CLIENT_SECRET")
    SPOTIFY_REDIRECT_URI: str = _env(
        "SPOTIFY_REDIRECT_URI", "http://localhost:5000/auth/callback"
    )
    SPOTIFY_SCOPE: str | None = _env("SPOTIFY_SCOPE")
    SPOTIFY_AUTH_URL: str = "https://accounts.spotify.com/authorize"
    SPOTIFY_TOKEN_URL: str = "https://accounts.spotify.com/api/token"
    SPOTIFY_API_BASE_URL: str = "https://api.spotify.com/v1"

    OPENAI_API_KEY: str | None = _env("OPENAI_API_KEY")
    OPENAI_MODEL: str = "whisper-1"
    OPENAI_API_TIMEOUT: int = _int_env("OPENAI_API_TIMEOUT", 30)

    FIELD_ENCRYPTION_KEY: str | None = _env("FIELD_ENCRYPTION_KEY")
    AUTH_STATE_TTL: int = _int_env("AUTH_STATE_TTL", 300)

    LOG_LEVEL: str = (_env("LOG_LEVEL", "INFO") or "INFO").upper()
    LOG_FILE: str | None = _env("LOG_FILE")
    LOG_FORMAT: str = "%(asctime)s - %(name)s - %(levelname)s - %(message)s"

    CORS_ORIGINS: List[str] = (
        _env("CORS_ORIGINS", "").split(",") if _env("CORS_ORIGINS") else []
    )

    RATELIMIT_ENABLED: bool = _bool_env("RATELIMIT_ENABLED", False)
    RATELIMIT_DEFAULT: str = _env("RATELIMIT_DEFAULT", "100 per hour")

    WORKERS: int = _int_env("WORKERS", 4)
    BIND_ADDRESS: str = _env("BIND_ADDRESS", "0.0.0.0:8000")

    @staticmethod
    def _enable_sqlite_wal(app: Flask) -> None:
        """Enable WAL for SQLite if used."""
        if not app.config["SQLALCHEMY_DATABASE_URI"].startswith("sqlite"):
            return

        @event.listens_for(Engine, "connect")
        def _set_sqlite_pragma(dbapi_connection, _):
            cursor = dbapi_connection.cursor()
            cursor.execute(
                f"PRAGMA journal_mode={app.config.get('SQLITE_JOURNAL_MODE', 'WAL')}"
            )
            cursor.execute("PRAGMA foreign_keys=ON")
            cursor.execute("PRAGMA synchronous=NORMAL")
            cursor.close()

    @classmethod
    def _warn_missing_spotify_vars(cls, app: Flask) -> None:
        """Warn if required Spotify variables are missing."""
        required = ("SPOTIFY_CLIENT_ID", "SPOTIFY_CLIENT_SECRET", "SPOTIFY_SCOPE")
        missing = [var for var in required if not app.config.get(var)]
        if missing:
            warnings.warn(f"Missing required Spotify vars: {', '.join(missing)}")

    @classmethod
    def init_app(cls, app: Flask) -> None:
        """Run common initialisation after loading config."""
        cls._enable_sqlite_wal(app)
        cls._warn_missing_spotify_vars(app)


class DevelopmentConfig(BaseConfig):
    DEBUG = True
    FLASK_ENV = "development"


class ProductionConfig(BaseConfig):
    DEBUG = False
    FLASK_ENV = "production"
    SESSION_COOKIE_SECURE = True
    SESSION_COOKIE_HTTPONLY = True
    SESSION_COOKIE_SAMESITE = "Lax"
    SEND_FILE_MAX_AGE_DEFAULT = 31536000

    @classmethod
    def init_app(cls, app: Flask) -> None:
        super().init_app(app)

        if cls.LOG_FILE:
            import logging
            from logging.handlers import RotatingFileHandler

            file_handler = RotatingFileHandler(
                cls.LOG_FILE, maxBytes=10 * 1024 * 1024, backupCount=10
            )
            file_handler.setFormatter(logging.Formatter(cls.LOG_FORMAT))
            file_handler.setLevel(getattr(logging, cls.LOG_LEVEL, "INFO"))
            app.logger.addHandler(file_handler)
            app.logger.setLevel(getattr(logging, cls.LOG_LEVEL, "INFO"))
            app.logger.info("Spotify Voice Bridge API started (production)")


class TestingConfig(BaseConfig):
    TESTING = True
    SQLALCHEMY_DATABASE_URI = "sqlite:///:memory:"
    WTF_CSRF_ENABLED = False
    FIELD_ENCRYPTION_KEY = "test-key-1234567890123456789012345678901234="


config = {
    "development": DevelopmentConfig,
    "production": ProductionConfig,
    "default": DevelopmentConfig,
}


def get_config() -> Type[BaseConfig]:
    """Return config class for current FLASK_ENV."""
    env = os.getenv("FLASK_ENV", "development")
    return config.get(env, DevelopmentConfig)
