"""
Configuration management for Spotify Voice Bridge API.

This module loads environment variables and provides configuration
settings for different deployment environments.
"""

import os
from typing import Optional
from dotenv import load_dotenv

load_dotenv()


class Config:
    """Base configuration class with common settings."""

    # Flask Core Configuration
    SECRET_KEY: str = os.environ.get("SECRET_KEY") or "dev-secret-key-please-change"
    FLASK_APP: str = os.environ.get("FLASK_APP", "run.py")

    # Database Configuration
    SQLALCHEMY_DATABASE_URI: str = os.environ.get(
        "DATABASE_URL", "sqlite:///project.db"
    )
    SQLALCHEMY_TRACK_MODIFICATIONS: bool = False

    # Spotify API Configuration
    SPOTIFY_CLIENT_ID = os.environ.get("SPOTIFY_CLIENT_ID")
    SPOTIFY_CLIENT_SECRET = os.environ.get("SPOTIFY_CLIENT_SECRET")
    SPOTIFY_REDIRECT_URI: str = os.environ.get(
        "SPOTIFY_REDIRECT_URI", "http://localhost:5000/auth/callback"
    )
    SPOTIFY_SCOPE = os.environ.get("SPOTIFY_SCOPE")
    SPOTIFY_AUTH_URL: str = "https://accounts.spotify.com/authorize"
    SPOTIFY_TOKEN_URL: str = "https://accounts.spotify.com/api/token"
    SPOTIFY_API_BASE_URL: str = "https://api.spotify.com/v1"

    # OpenAI Configuration
    OPENAI_API_KEY: str = os.environ.get("OPENAI_API_KEY", "")
    OPENAI_MODEL: str = "whisper-1"
    OPENAI_API_TIMEOUT: int = 30  # seconds

    # Encryption Configuration
    FIELD_ENCRYPTION_KEY: str = os.environ.get("FIELD_ENCRYPTION_KEY", "")

    # Authentication State Configuration
    AUTH_STATE_TTL: int = int(os.environ.get("AUTH_STATE_TTL", "300"))  # 5 minutes

    # Logging Configuration
    LOG_LEVEL: str = os.environ.get("LOG_LEVEL", "INFO")
    LOG_FILE: Optional[str] = os.environ.get("LOG_FILE")
    LOG_FORMAT: str = "%(asctime)s - %(name)s - %(levelname)s - %(message)s"

    # CORS Configuration
    CORS_ORIGINS: list = (
        os.environ.get("CORS_ORIGINS", "").split(",")
        if os.environ.get("CORS_ORIGINS")
        else []
    )

    # Rate Limiting
    RATELIMIT_ENABLED: bool = (
        os.environ.get("RATELIMIT_ENABLED", "false").lower() == "true"
    )
    RATELIMIT_DEFAULT: str = os.environ.get("RATELIMIT_DEFAULT", "100 per hour")

    # Server Configuration
    WORKERS: int = int(os.environ.get("WORKERS", "4"))
    BIND_ADDRESS: str = os.environ.get("BIND_ADDRESS", "0.0.0.0:8000")

    @staticmethod
    def init_app(app):
        """Initialize application with configuration."""
        # Configure SQLite for production if using SQLite
        if app.config["SQLALCHEMY_DATABASE_URI"].startswith("sqlite"):
            # Enable Write-Ahead Logging for better concurrency
            from sqlalchemy import event
            from sqlalchemy.engine import Engine

            @event.listens_for(Engine, "connect")
            def set_sqlite_pragma(dbapi_connection, connection_record):
                cursor = dbapi_connection.cursor()
                cursor.execute(
                    f"PRAGMA journal_mode={app.config.get('SQLITE_JOURNAL_MODE', 'WAL')}"
                )
                cursor.execute("PRAGMA foreign_keys=ON")
                cursor.execute("PRAGMA synchronous=NORMAL")
                cursor.close()

        # Checagem de variáveis obrigatórias
        missing = []
        for var in ["SPOTIFY_CLIENT_ID", "SPOTIFY_CLIENT_SECRET", "SPOTIFY_SCOPE"]:
            value = app.config.get(var) or os.environ.get(var)
            if not value:
                missing.append(var)
        if missing:
            import warnings

            warnings.warn(f"Missing required Spotify config vars: {', '.join(missing)}")


class DevelopmentConfig(Config):
    """Development configuration with debug enabled."""

    DEBUG = True
    FLASK_ENV = "development"


class ProductionConfig(Config):
    """Production configuration with security hardening."""

    DEBUG = False
    FLASK_ENV = "production"

    # Force HTTPS in production
    SESSION_COOKIE_SECURE = True
    SESSION_COOKIE_HTTPONLY = True
    SESSION_COOKIE_SAMESITE = "Lax"

    # Security headers
    SEND_FILE_MAX_AGE_DEFAULT = 31536000  # 1 year

    @classmethod
    def init_app(cls, app):
        """Production-specific initialization."""
        Config.init_app(app)

        # Log to file in production
        if cls.LOG_FILE:
            import logging
            from logging.handlers import RotatingFileHandler

            file_handler = RotatingFileHandler(
                cls.LOG_FILE, maxBytes=10485760, backupCount=10  # 10MB
            )
            file_handler.setFormatter(logging.Formatter(cls.LOG_FORMAT))
            file_handler.setLevel(getattr(logging, cls.LOG_LEVEL.upper()))
            app.logger.addHandler(file_handler)
            app.logger.setLevel(getattr(logging, cls.LOG_LEVEL.upper()))
            app.logger.info("Spotify Voice Bridge API startup")


class TestingConfig(Config):
    """Testing configuration with in-memory database."""

    TESTING = True
    SQLALCHEMY_DATABASE_URI = "sqlite:///:memory:"
    WTF_CSRF_ENABLED = False
    FIELD_ENCRYPTION_KEY = "test-key-1234567890123456789012345678901234="


# Configuration dictionary
config = {
    "development": DevelopmentConfig,
    "production": ProductionConfig,
    "testing": TestingConfig,
    "default": DevelopmentConfig,
}


def get_config():
    """Get configuration based on FLASK_ENV environment variable."""
    env = os.environ.get("FLASK_ENV", "development")
    return config.get(env, DevelopmentConfig)
