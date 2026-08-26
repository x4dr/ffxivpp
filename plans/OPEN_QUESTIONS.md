# OPEN QUESTIONS — compiled for maric

Nothing here blocks the overnight build; answers get folded in when maric
returns. Newest at the bottom.

## Open

1. **Pre-existing e2e flake** (not from overnight work; reproduced on baseline
   commit before any questboard code): `tests/e2e/test_security.py::test_non_admin_cannot_access_admin_features`
   — unauthenticated request to `/api/channels` gets redirected through
   `/auth/login` to discord.com, and the test then asserts on *Discord's* 200
   instead of a local 403. Fix options: assert pre-redirect status
   (`allow_redirects=False`) or start redirect chain detection at `/auth/login`.
   Want me to fix it as part of maintenance?
2. **Strict mypy currently fails on existing app/ code** (app/db.py,
   app/compute.py etc. — ~20 errors). AGENTS.md says mypy strict applies;
   either the gate is aspirational or app/ drifted. FastAPI migration plan
   should include a "make strict green" pass. No action taken without you.
3. **OpenCode agents are slow tonight** (~7+ min for one bounded task, tool
   timeout at 5 min killed my visibility though the agent kept working).
   Switched to writing core myself + using opencode for review passes. Fine
   for quality, but flagging the pace.

## Answered (for reference)

- Models pinned: x-preview-f-free / ox-alpha only.
- No implementation until "go" was given 2026-08-26 ~04:30 for overnight work.
