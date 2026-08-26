# Overnight Session Plan — Questboard Foundation (2026-08-26 night)

**Authorization:** maric, ~04:30. Build overnight with `opencode/x-preview-f-free`
/ `ox-alpha` ONLY (Hermes + OpenCode agents). He sleeps; no questions until he's
back (~8h). Compile all questions into OPEN_QUESTIONS.md; decisions needing his
sign-off go in SIGNOFF.md.

**Hard constraints**
- Models: x-preview-f-free / ox-alpha only, everywhere.
- No implementation outside the scope below; design docs (docs/) are the spec.
- Deviations from the plan → document, don't decide.
- Existing party-planner behavior must keep working; baseline suite must stay green.
- AGENTS.md rules: uv for everything, ruff line 100, mypy strict on app/,
  5-second test timeout policy, no chore:/fix: prefixes, never "final"/"finalize"
  in commit messages.
- TODO.md is agent-owned: check off only when a disposition is actually done.

## Scope order (cut from the bottom when time runs out)

0. plans/overnight-session.md (this file) + OPEN_QUESTIONS.md scaffold
1. **core/** shared domain package:
   - item catalog model + quest/requirement-tree/pledge/turn-in/event models
   - pure logic: tree explosion & proportional substitution accounting,
     quest status transitions
   - Teamcraft import-string parser (`itemId,recipeId|null,qty;...`)
   - unit tests for all of it (TDD)
2. **wiki pipeline**: consolegameswiki fetch → recipe parse → cache tables,
   patch detection hook, rate limiting; fixture-based parser tests
   (anonymized HTML fixture like tests/fixtures/*)
3. **web (Flask)**: /questboard routes (list, detail, create, pledge, turn-in),
   Jinja templates + htmx partials, SSE refresh endpoint reusing existing pattern;
   auth via existing check_access()/require decorators; Pydantic-free (Flask) —
   validation functions in core
4. **bot**: /quest create/list/detail/contribute/close commands + views,
   quest thread creation, embed update loop (SSE client w/ watermark fallback →
   if SSE client proves flaky tonight: DB polling watermark, documented as
   deviation), reminder scheduler skeleton (per-user time, opt-in)
5. **voyages**: data-dir loader + schema validation, prediction pure functions
   (range/duration/surveillance gates), sample data file (clearly marked SAMPLE,
   not real community data), minimal page
6. **chest ingest**: POST endpoint (shared secret), manual paste form, snapshot
   diff + fulfillment suggestion records (no auto-completion ever)
7. Wrap-up: full suite green, screenshots dir, SIGNOFF.md, OPEN_QUESTIONS.md
   finalized, commits tidy, this file updated with what actually happened.

## Explicitly out of scope tonight

- FastAPI migration (gated separately; needs maric's explicit go)
- Dalamud plugin (C# side project)
- Real voyage community-data ingestion (legality/format sign-off pending)
- Reminders actually firing in production (skeleton + tests only)
- Any deploy to the server

## Delegation pattern

OpenCode one-shot tasks per work package (`opencode run --model opencode/x-preview-f-free`),
each with precise context: file paths, interfaces, test commands, commit message.
Hermes reviews diffs, runs suites, fixes integration seams directly or via follow-up
runs. Re-nudge on stalls (maric expects slow/stuck agents tonight).
