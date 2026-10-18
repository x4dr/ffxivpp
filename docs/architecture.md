# Architecture

## Current state (2026-08)

Two processes, one SQLite database (`party.db`, SQLAlchemy 2.0):

- **Flask app** (`app.py` → `app/`) served by gunicorn under `ffxiv-flask.service`.
  JSON API + Discord OAuth session auth + static `partydashboard.html` (vanilla JS, SSE).
- **Discord bot** (`bot.py` → `bot/commands.py`, discord.py 2.7) under `ffxiv-bot.service`.
  Slash commands, persistent home-channel embeds, background `scraper_loop`
  draining the `scraper_tasks` table (Lodestone character scraping with cooldowns).

Deploy: `deploy/install.sh` + systemd units + nginx. The host is behind NAT, so
`ffxiv-deploy.timer` pulls `origin/main` every minute; the GitHub Actions
workflow runs the tests and then polls `/deploy/version` to verify the rollout.
Package management via `uv`; QA gates: ruff (line 100), mypy strict (`app/` only),
pytest (5 s timeout policy).

The party-planning feature set (compute engine, constraints, home-channel embed)
is **frozen in maintenance mode**: it works, the FC found its static, it stays
available but receives no new features. Bug fixes allowed.

## Target state

Same two processes, one framework:

- **FastAPI app replaces Flask.** Migration is a deliberate, separately planned
  step with full regression testing before cutover ("easily possible" gate —
  if it turns out too hard mid-migration, we stop and reassess with maric).
  - Jinja2 templates + htmx for server-rendered pages; SSE via
    `StreamingResponse`/`sse-starlette`.
  - Auth: same Discord OAuth flow, reimplemented on FastAPI (itsdangerous-signed
    session cookie or `authlib`); identity = Discord user id, guild membership +
    admin-role checks identical to today's logic in `app/auth.py`.
  - The existing raw-JS frontend talks to JSON endpoints that barely use Flask
    features, which is why migration risk is judged low. Escape hatch exists.
- **Bot process unchanged** except new questboard commands/views.
- **Shared code** (`models`, `db` helpers, compute) imported by both processes;
  SQLite retained. Write discipline stays: short transactions, no connections
  held across network I/O.

### New modules (target layout)

```
app/            → web/          FastAPI app (routes split: parties legacy, questboard, voyages, admin)
core/           shared: models.py, db.py, wiki data pipeline, voyage math, item catalog
bot/            unchanged role: commands, views, scraper loop (+ quest announcement hooks)
plugins/        Dalamud plugin experiment (C#), separate build, talks to the API
data/voyages/   static voyage sector tables — NOT in git; supplied manually (see integrations-voyages.md)
docs/, plans/   design docs and per-feature implementation plans
```

(Renames are part of the FastAPI migration plan; until then new code lands in
the existing tree.)

## Storage additions

New tables (details in questboard.md / integrations docs): `quests`,
`quest_items` (tree nodes), `pledges`, `quest_events` (audit log incl. turn-ins),
`item_catalog` (wiki cache), `voyage_runs`/`voyage_loot` (optional logging),
`chest_snapshots`. Existing tables untouched.

## Environments / config

- Existing `.env`: Discord tokens, GUILD_ID, DATABASE_PATH.
- New: `VOYAGE_DATA_DIR` (static files location), `WIKI_CACHE_TTL`, optional
  `USER_AGENT` for consolegameswiki scraping (polite identification).

## Testing posture

- Unit tests for tree math, pledge accounting, voyage prediction, reminder scheduler.
- Integration tests against the FastAPI app (httpx ASGI client — already a dev dep).
- E2E Playwright suite kept green through the migration (existing suite).
- Bot-side logic tested with mocked Discord as today.

## Deployment deltas

- `ffxiv-flask.service` → `ffxiv-web.service` (uvicorn workers behind existing nginx).
- Bot unit unchanged.
- Manual step documented: placing refreshed voyage data files into `VOYAGE_DATA_DIR`.
