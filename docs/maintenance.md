# Maintenance mode & dispositions

## Party planner: maintenance mode

Shipped and frozen. The FC found its static; planning is no longer the daily
use case. Kept working: compute engine, constraints UI, home-channel embeds,
Lodestone scraping, polls. Bug fixes only, no new features.

Event tracking / raid setups and a possible CalDAV integration are documented
as **future areas** — no design yet, will get their own docs when wanted.

## TODO.md dispositions (maric: "if it's review just do it, otherwise judge usefulness")

| Item | Disposition |
|---|---|
| Review `_conn_start_times` in app/db.py for multi-process safety | **Review — do during FastAPI migration** (touches db layer anyway); delete from TODO after verdict |
| Ensure all API endpoints protected by authentication | **Review — do as part of migration auth rewrite**; new endpoint-permission matrix comes from surfaces.md |
| Caching for Discord API responses in app/auth.py | **Useful — fold into migration**: check_access() hits up to 3 Discord endpoints per request; add short-TTL member/guild cache while rewriting auth on FastAPI |
| Input validation for all API endpoints | **Superseded by FastAPI/Pydantic models** during migration; legacy endpoints get validation as they're ported |

## Ownership

TODO.md is owned by the agent during this effort: entries get checked off /
removed only when their disposition (table above) is actually done, never
before. maric's wording is preserved otherwise.

## Migration gate

FastAPI cutover happens only with: full existing test suite green (unit +
integration + Playwright e2e), parity checklist of every current route
(routes.py, auth.py) verified against the new app, and maric's explicit go.
Abort hatch: if mid-migration it turns out not "easily possible" (auth session
semantics, SSE, or deploy surprises), stop, report, reassess with maric.
