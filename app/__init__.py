from __future__ import annotations

import os

from dotenv import load_dotenv
from flask import Flask
from flask_discord import DiscordOAuth2Session  # type: ignore[import-untyped]

from app.db import close_db, init_db

load_dotenv()


def create_app() -> Flask:
    app = Flask(__name__, static_folder="../static")
    sk = os.environ.get("FLASK_SECRET_KEY")
    if not sk:
        raise RuntimeError("FLASK_SECRET_KEY must be set in .env")
    app.secret_key = sk
    app.config["DISCORD_CLIENT_ID"] = os.environ["DISCORD_CLIENT_ID"]
    app.config["DISCORD_CLIENT_SECRET"] = os.environ["DISCORD_CLIENT_SECRET"]
    app.config["DISCORD_REDIRECT_URI"] = os.environ["DISCORD_REDIRECT_URI"]

    DiscordOAuth2Session(app)
    app.teardown_appcontext(close_db)

    with app.app_context():
        init_db()

    from app.auth import bp as auth_bp

    app.register_blueprint(auth_bp)

    from app.routes import bp

    app.register_blueprint(bp)

    return app
