"""
Application factory for Spotify Voice Bridge API.

This module implements the Flask application factory pattern,
initializing all extensions and registering blueprints.
"""

import os
import logging
from logging.handlers import RotatingFileHandler
from flask import Flask
from flask_sqlalchemy import SQLAlchemy
from flask_migrate import Migrate
from flasgger import Swagger

# Initialize extensions
db = SQLAlchemy()
migrate = Migrate()


def create_app(config_name=None):
    """
    Create and configure the Flask application.

    Args:
        config_name: Configuration name ('development', 'production', 'testing').
                    If None, uses FLASK_ENV environment variable.

    Returns:
        Flask: Configured Flask application instance.
    """
    app = Flask(__name__)

    if config_name is None:
        config_name = os.environ.get("FLASK_ENV", "development")

    from config import config

    app.config.from_object(config[config_name])

    # Initialize configuration-specific settings
    config[config_name].init_app(app)

    # Initialize extensions with app
    db.init_app(app)
    migrate.init_app(app, db)

    # Configure Swagger
    Swagger(app)

    configure_logging(app)
    register_blueprints(app)
    register_error_handlers(app)
    register_cli_commands(app)

    app.logger.info(f"Spotify Voice Bridge API initialized in {config_name} mode")

    return app


def register_blueprints(app):
    """
    Register all application blueprints.

    Args:
        app: Flask application instance.
    """
    from app.api.routes import api_bp

    app.register_blueprint(api_bp)
    app.logger.debug("Registered API blueprint")


def register_error_handlers(app):
    """
    Register global error handlers.

    Args:
        app: Flask application instance.
    """
    from flask import jsonify

    @app.errorhandler(404)
    def not_found_error(error):
        """Handle 404 errors."""
        return (
            jsonify(
                {
                    "error": "Not Found",
                    "message": "The requested resource was not found",
                }
            ),
            404,
        )

    @app.errorhandler(500)
    def internal_error(error):
        """Handle 500 errors."""
        app.logger.error(f"Internal error: {str(error)}")
        db.session.rollback()
        return (
            jsonify(
                {
                    "error": "Internal Server Error",
                    "message": "An unexpected error occurred",
                }
            ),
            500,
        )

    @app.errorhandler(400)
    def bad_request_error(error):
        """Handle 400 errors."""
        return jsonify({"error": "Bad Request", "message": str(error)}), 400

    @app.errorhandler(401)
    def unauthorized_error(error):
        """Handle 401 errors."""
        return (
            jsonify({"error": "Unauthorized", "message": "Authentication required"}),
            401,
        )

    @app.errorhandler(403)
    def forbidden_error(error):
        """Handle 403 errors."""
        return jsonify({"error": "Forbidden", "message": "Access denied"}), 403

    @app.errorhandler(Exception)
    def handle_unexpected_error(error):
        """Handle unexpected errors."""
        app.logger.exception("An unexpected error occurred")
        db.session.rollback()

        # Don't expose internal errors in production
        if app.config.get("DEBUG"):
            message = str(error)
        else:
            message = "An unexpected error occurred"

        return jsonify({"error": "Internal Server Error", "message": message}), 500


def configure_logging(app):
    """
    Configure application logging.

    Args:
        app: Flask application instance.
    """
    # Skip logging configuration during testing
    if app.config.get("TESTING"):
        return

    log_level = getattr(logging, app.config.get("LOG_LEVEL", "INFO").upper())
    app.logger.setLevel(log_level)
    app.logger.handlers = []  # Remove default Flask handlers

    console_handler = logging.StreamHandler()
    console_handler.setLevel(log_level)
    console_formatter = logging.Formatter(
        "%(asctime)s - %(name)s - %(levelname)s - %(message)s"
    )
    console_handler.setFormatter(console_formatter)
    app.logger.addHandler(console_handler)

    log_file = app.config.get("LOG_FILE")
    if log_file:
        file_handler = RotatingFileHandler(
            log_file, maxBytes=10485760, backupCount=10  # 10MB
        )
        file_handler.setLevel(log_level)
        file_formatter = logging.Formatter(
            "%(asctime)s - %(name)s - %(levelname)s - %(message)s"
        )
        file_handler.setFormatter(file_formatter)
        app.logger.addHandler(file_handler)

    app.logger.info("Logging configured")


def register_cli_commands(app):
    """
    Register custom CLI commands.

    Args:
        app: Flask application instance.
    """

    @app.cli.command()
    def init_db():
        """Initialize the database."""
        db.create_all()
        print("Database initialized!")

    @app.cli.command()
    def generate_key():
        """Generate a new encryption key."""
        from cryptography.fernet import Fernet

        key = Fernet.generate_key().decode("utf-8")
        print(f"New encryption key: {key}")
        print(f"Add to .env: FIELD_ENCRYPTION_KEY={key}")

    @app.cli.command()
    def test_config():
        """Test configuration loading."""
        print(f"Database URI: {app.config['SQLALCHEMY_DATABASE_URI']}")
        print(
            f"Spotify Client ID: {'*' * 10 if app.config['SPOTIFY_CLIENT_ID'] else 'NOT SET'}"
        )
        print(
            f"OpenAI API Key: {'*' * 10 if app.config['OPENAI_API_KEY'] else 'NOT SET'}"
        )
        print(
            f"Encryption Key: {'*' * 10 if app.config['FIELD_ENCRYPTION_KEY'] else 'NOT SET'}"
        )

    @app.cli.command()
    def list_devices():
        """List all registered devices."""
        from app.api.models import DeviceAuth

        devices = DeviceAuth.query.all()
        if not devices:
            print("No devices registered")
        else:
            print(f"Registered devices ({len(devices)}):")
            for device in devices:
                print(f"  - {device.device_id} (Updated: {device.updated_at})")


def create_migration_app():
    """Create app instance for database migrations."""
    return create_app("development")
