# SIGNOFF — decisions awaiting maric

Filled as the night goes. Nothing here was decided unilaterally where a real
fork existed; each item states what was done meanwhile.

| # | Topic | What I did meanwhile | Recommendation |
|---|-------|----------------------|----------------|
| 1 | Browser "Allow remote debugging" popup (interactive Chrome harness) | Not needed: headless Playwright Chromium works on hati; live screenshots taken with it | Nothing to click unless you later want me driving your real Chrome |
| 2 | ~~Vision fallback analyzer 401~~ | OBSOLETE — struck 2026-08-26 morning. Current config.yaml has no vision-analyzer key entry; screenshots are read via `opencode run -f img.png` (works, verified twice) | Nothing to do |
| 3 | Live-UI screenshot check | DONE morning of 2026-08-26 without any destructive step (fresh uniquely-named DB instead of rm). Captured plans/shots/quests.png + voyages.png, verified through opencode vision | See findings below |

## Screenshot-pass findings (from opencode vision review)

1. BUG (queued): `/voyages/` renders `(sector )` empty — `predict_voyage`
   appends the scaled loot dict without the sector/threshold fields. Small fix
   in core/voyages.py + regression test. Queued behind the running lint/types
   agent because it owns that file right now.
2. NIT (queued): quest cards show raw ISO timestamp (`2026-08-26T08:07`);
   format it human-readable in the template.
3. Board content verified correct: substitution math displays as designed
   (turn-ins propagate proportionally to children: 50/300 popcorn delivered →
   fire clusters shown at x83 of 100).
