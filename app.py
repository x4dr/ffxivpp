"""FF14 Party Planner — Flask API entry point."""

from __future__ import annotations

from app import create_app

app = create_app()

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=7111, debug=False)
