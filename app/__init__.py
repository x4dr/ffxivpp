from __future__ import annotations

import logging
import os

from dotenv import load_dotenv
from flask import Flask, request
from flask_discord import DiscordOAuth2Session  # type: ignore[import-untyped]

from app.db import close_db, init_db

for _lib in ("requests_oauthlib", "oauthlib", "urllib3"):
    logging.getLogger(_lib).setLevel(logging.WARNING)

load_dotenv()


def create_app(config_override: dict[str, Any] | None = None) -> Flask:
    app = Flask(__name__, static_folder="../static")
    
    # Configure logging to stdout for tests/debugging
    import sys
    handler = logging.StreamHandler(sys.stdout)
    handler.setLevel(logging.INFO)
    app.logger.addHandler(handler)
    app.logger.setLevel(logging.INFO)
    
    @app.before_request
    def log_request_info():
        app.logger.info(f"Request: {request.method} {request.url}")

    if config_override:
        app.config.update(config_override)
    
    sk = os.environ.get("FLASK_SECRET_KEY")
    if not sk:
        raise RuntimeError("FLASK_SECRET_KEY must be set in .env")
    app.secret_key = sk
    app.config["DISCORD_CLIENT_ID"] = os.environ.get("DISCORD_CLIENT_ID", "test_id")
    app.config["DISCORD_CLIENT_SECRET"] = os.environ.get("DISCORD_CLIENT_SECRET", "test_secret")
    app.config["DISCORD_REDIRECT_URI"] = os.environ.get("DISCORD_REDIRECT_URI")

    if not app.config.get("TESTING"):
        DiscordOAuth2Session(app)
    else:
        # Mock Discord OAuth for tests
        pass

    app.teardown_appcontext(close_db)

    with app.app_context():
        init_db()

    from app.auth import bp as auth_bp
    app.register_blueprint(auth_bp)

    from app.routes import bp
    app.register_blueprint(bp)

    return app

