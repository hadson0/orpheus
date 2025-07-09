"""Entry point."""

import os
from app import create_app, db
from app.api.models import DeviceAuth

app = create_app(os.getenv("FLASK_ENV", "production"))


@app.shell_context_processor
def make_shell_context():
    """Expose db and models in flask shell."""
    return {"db": db, "DeviceAuth": DeviceAuth}


if __name__ == "__main__":
    host = os.getenv("FLASK_HOST", "0.0.0.0")
    port = int(os.getenv("FLASK_PORT", 5000))
    debug = os.getenv("FLASK_ENV") == "development"

    app.run(
        host=host,
        port=port,
        debug=debug,
        threaded=True,
        use_reloader=debug,
    )
