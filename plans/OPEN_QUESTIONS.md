# OPEN QUESTIONS — compiled for maric

Nothing here blocks the overnight build; answers get folded in when maric
returns. Newest at the bottom.

## Open

1. **Strict mypy on existing app/ code** — RESOLVED 2026-08-26 (agent pass,
   commit pending review): all ~28 errors fixed with honest typing, no
   behavior changes; `types-oauthlib` added as dev dependency. Gate now green.
2. ~~OpenCode agents are slow~~ — worked around: parallel background dispatch
   with completion notifications; two agents finished real fixes while we
   talked. Pace acceptable.
3. **Straggler lint** (~53 hits, all pre-existing): tests/test_scraper.py,
   tests/test_embed.py, tests/integration/test_api.py, migrate_data.py —
   trivial E501/F841. Queued behind agent B's exit to avoid tree collisions.

## Answered (for reference)

- Models pinned: x-preview-f-free / ox-alpha only.
- No implementation until "go" was given 2026-08-26 ~04:30 for overnight work.
- E2e flake: "assert pre-redirect, maybe rethink the mechanic generally for
  e2e with the login model." → RESOLVED 2026-08-26, commit b72de18: root cause
  was fork-time env (mock auth not guaranteed) + Playwright auto-following
  redirects; new mock_auth_server fixture pins env per server, assertions are
  pre-redirect (302+Location / 403). Deterministic across repeated runs and
  ambient TEST_MOCK_AUTH values. The deeper "rethink e2e login model" idea is
  NOT done — candidate for the FastAPI migration effort if you still want it.
- Mypy + ruff: "uh yes, fix." → in progress via agent B (mypy clean on all 16
  source files at last check).
