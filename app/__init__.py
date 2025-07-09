"""
Flask application factory for Spotify Voice Bridge API.
"""

from __future__ import annotations

import logging
import os
from http import HTTPStatus
from logging.config import dictConfig
from typing import Callable, Mapping, Any

from flasgger import Swagger
from flask import Flask, jsonify
from flask_migrate import Migrate
from flask_sqlalchemy import SQLAlchemy
from werkzeug.exceptions import HTTPException

db: SQLAlchemy = SQLAlchemy()
migrate: Migrate = Migrate()


def create_app(config_name: str | None = None) -> Flask:
    """
    Create and configure Flask app.
    """
    app = Flask(__name__)

    config_name = config_name or os.getenv("FLASK_ENV", "development")
    from config import config  # local import avoids circular deps

    cfg_obj = config[config_name]
    app.config.from_object(cfg_obj)
    cfg_obj.init_app(app)

    _init_extensions(app)
    _configure_logging(app)
    _register_blueprints(app)
    _register_error_handlers(app)
    _register_cli(app)

    app.logger.info("Spotify Voice Bridge API ready (%s mode)", config_name)
    return app


def _init_extensions(app: Flask) -> None:
    """Initialize Flask extensions."""
    db.init_app(app)
    migrate.init_app(app, db)
    Swagger(app)
    app.logger.debug("Extensions initialized")


def _configure_logging(app: Flask) -> None:
    """Configure logging unless TESTING is set."""
    if app.config.get("TESTING"):
        return

    default_fmt = "%(asctime)s %(levelname)-8s [%(name)s] %(message)s"
    log_level = app.config.get("LOG_LEVEL", "INFO").upper()

    custom_cfg: Mapping[str, Any] | None = app.config.get("LOGGING")
    if custom_cfg:
        dictConfig(custom_cfg)
        app.logger.debug("Logging configured by dictConfig")
        return

    root = logging.getLogger()
    root.handlers.clear()
    root.setLevel(log_level)

    console = logging.StreamHandler()
    console.setFormatter(logging.Formatter(default_fmt))
    root.addHandler(console)

    file_path = app.config.get("LOG_FILE")
    if file_path:
        file_handler = logging.handlers.RotatingFileHandler(
            file_path, maxBytes=10 * 1024 * 1024, backupCount=10
        )
        file_handler.setFormatter(logging.Formatter(default_fmt))
        root.addHandler(file_handler)

    app.logger.debug("Logging configured (level=%s)", log_level)


def _register_blueprints(app: Flask) -> None:
    from app.api.routes import api_bp

    app.register_blueprint(api_bp)
    app.logger.debug("Blueprints registered")


def _json_error(error: str, message: str, status: HTTPStatus):
    return jsonify({"error": error, "message": message}), status


def _register_error_handlers(app: Flask) -> None:
    @app.errorhandler(HTTPException)
    def http_errors(err: HTTPException):
        return _json_error(err.name, err.description, HTTPStatus(err.code))

    @app.errorhandler(Exception)
    def unhandled(err: Exception):
        app.logger.exception("Unhandled exception")
        db.session.rollback()
        msg = str(err) if app.config.get("DEBUG") else "An unexpected error occurred"
        return _json_error(
            "Internal Server Error", msg, HTTPStatus.INTERNAL_SERVER_ERROR
        )


def _register_cli(app: Flask) -> None:
    """Attach custom flask CLI commands."""

    @app.cli.command("init-db")
    def init_db() -> None:
        """Create all tables."""
        db.create_all()
        print("Database initialized")

    @app.cli.command("generate-key")
    def generate_key() -> None:
        """Generate and print new encryption key."""
        from cryptography.fernet import Fernet

        key = Fernet.generate_key().decode()
        print(f"FIELD_ENCRYPTION_KEY={key}")

    @app.cli.command("test-config")
    def test_config() -> None:
        """Print important configuration values."""
        for key in (
            "SQLALCHEMY_DATABASE_URI",
            "SPOTIFY_CLIENT_ID",
            "OPENAI_API_KEY",
            "FIELD_ENCRYPTION_KEY",
        ):
            val = app.config.get(key)
            masked = "*" * 10 if val else "NOT SET"
            print(f"{key}: {masked}")

    @app.cli.command("list-devices")
    def list_devices() -> None:
        """List registered devices."""
        from app.api.models import DeviceAuth

        devices = DeviceAuth.query.all()
        if not devices:
            print("No devices registered.")
            return
        print(f"Registered devices ({len(devices)}):")
        for dev in devices:
            print(f" • {dev.device_id} (updated: {dev.updated_at})")


def create_migration_app() -> Flask:
    return create_app("development")
