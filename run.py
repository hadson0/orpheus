"""
Entry point for the Spotify Voice Bridge API.

This module creates the Flask application instance and provides
the entry point for both development and production servers.
"""

import os
from app import create_app, db
from app.api.models import DeviceAuth

app = create_app(os.getenv("FLASK_ENV", "development"))


# Create shell context for Flask CLI
@app.shell_context_processor
def make_shell_context():
    """
    Make database models available in flask shell.
    """
    return {"db": db, "DeviceAuth": DeviceAuth}


if __name__ == "__main__":
    """
    Run the development server when executing this file directly.
    """
    host = os.getenv("FLASK_HOST", "0.0.0.0")
    port = int(os.getenv("FLASK_PORT", 5000))
    debug = os.getenv("FLASK_ENV") == "development"

    if not debug:
        print("\n" + "=" * 50)
        print("WARNING: Running with Flask development server!")
        print("For production, use: gunicorn -w 4 -b 0.0.0.0:8000 run:app")
        print("=" * 50 + "\n")

    # Run development server
    app.run(
        host=host,
        port=port,
        debug=debug,
        threaded=True,  # Enable threading for better concurrency
        use_reloader=debug,  # Auto-reload on code changes in debug mode
    )
