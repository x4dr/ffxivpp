"""FF14 Party Planner — Discord bot entry point."""

from __future__ import annotations

import os

from dotenv import load_dotenv

load_dotenv()

from bot.commands import client


def main() -> None:
    token = os.environ.get("DISCORD_BOT_TOKEN")
    if not token:
        raise RuntimeError("Set DISCORD_BOT_TOKEN environment variable")
    client.run(token)


if __name__ == "__main__":
    main()
