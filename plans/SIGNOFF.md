# SIGNOFF — decisions awaiting maric

Filled as the night goes. Nothing here was decided unilaterally where a real
fork existed; each item states what was done meanwhile.

| # | Topic | What I did meanwhile | Recommendation |
|---|-------|----------------------|----------------|
| 1 | Browser "Allow remote debugging" popup (interactive Chrome harness) | Used headless Playwright instead | Click Allow next session if you want me driving your real Chrome; otherwise Playwright is enough |
| 2 | Vision fallback analyzer 401 (invalid API key) | RESOLVED overnight: maric confirmed opencode (x-preview-f-free) reads images via `-f`. Screenshots get analyzed through `opencode run --model ... -f img.png` | Fix the stale key in config whenever convenient |
| 3 | Live-UI screenshot check blocked by approval gate | The demo-seed command used `rm -f` on a scratch DB; the harness correctly held it for consent and maric is asleep. All UI routes are covered by 10 integration tests instead; screenshots are the only thing missing. | Say the word in the morning and I'll seed `/tmp/qb_demo.db` + capture /quests/ and /voyages/ in one go |

## Overnight build summary (questboard effort)

Committed on `main`, one feature per commit, full suite green before each:

1. **Teamcraft import parser** — `core/teamcraft.py`: base64-or-json autodetect,
   item/qty extraction.
2. **Quest tree engine** — `core/quests.py`: requirement trees, positional node
   ids, proportional parent→child substitution accounting
   (pledge/turn-in at any level), flatten-to-shopping-list.
3. **Persistence** — `core/questdb.py`: quests, pledges, turn-ins,
   suggestion-only chest events, reminder opt-ins (daily + weekly w/ weekday),
   item catalog tables sharing the app's Base/metadata.
4. **Wiki pipeline** — `core/wiki.py` + fixture: consolegameswiki API parse
   (depth-aware template splitting), cache-first ItemCatalog lookup, patch
   detection from the Patches page to invalidate cache.
5. **Web** — `app/questboard.py` + templates: board page, quest detail tree,
   pledge/turn-in JSON APIs, nav links; plus `/voyages/` prediction view and
   `/chest/` paste UI with secret-token ingest API (`app/chest.py`).
6. **Bot** — `bot/questboard.py`: /quest-create/-list/-detail/-contribute/
   -close/-remind-me, thread-per-quest with auto-refreshing status embed,
   contribute select+modal, DM reminder loop wired into setup_hook.

Test count: baseline ~66 → now **163 collected**, all passing except the one
pre-existing e2e OAuth flake documented in OPEN_QUESTIONS.md #1 (reproduced on
the pre-questboard baseline commit).

## Morning checklist

1. `cd ~/PycharmProjects/ffxivpp && git log --oneline -12` — review commits.
2. Answer OPEN_QUESTIONS.md items when convenient.
3. Optional: approve the screenshot pass (SIGNOFF #3) for visual confirmation.
