"""FF14 Party Planner — Flask API entry point."""

from __future__ import annotations

import os

from app import create_app

app = create_app()

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 7111))
    app.run(host="0.0.0.0", port=port, debug=False)
