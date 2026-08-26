# Integration: sea/airship voyages

Decision: **in scope now.** Voyages are deterministic given parts + rank +
route — community sites exploit this; we reuse the same logic so a member can
open a quest ("job") tied to a specific voyage's expected yield.

## Data

- Static sector tables (loot per sector, surveillance/retrieval thresholds,
  route graphs, voyage durations, XP): compiled from community sources
  (submarine.girin.dev data, armadaxiv, the FFXIV Submarine Builders
  spreadsheets).
- **Not committed to git** (legality stance, maric's call). Files live in a
  server-side directory configured via `VOYAGE_DATA_DIR`; refresh procedure =
  download new pack per game patch and drop it in (documented in plans).
- Format: versioned JSON (`{meta: {game_version, source_pack}, sectors[], routes[]}`);
  loader validates schema + version and refuses stale/mismatched packs loudly.

## Fleet model

Per-FC configuration of airships/submersibles: vessel name, parts (hull/stern/
bow/bridge), rank, current condition. Stored in DB, editable on the web voyage
page (officers + whoever officers allow).

## Prediction

Given fleet config + selected route: reachable? (range/speed), duration,
expected loot table with surveillance-gated items highlighted, ceruleum tank
cost. Deterministic pure functions over static data → heavily unit-tested,
no I/O.

## Voyage-linked quests ("jobs")

From a predicted voyage (or a manually entered one), anyone can open a quest:
"Voyage to Sectors U-V — bring back/stock X". The quest is a normal questboard
quest with a voyage reference (route + date) attached for context. This covers
"someone can open a job for the specific voyage".

## Loot logging (flexible v1)

Manual "log run outcome" form (what actually came back). Kept deliberately
simple/flexible because maric expects to iterate on real FC feedback; structure
(voyage_runs/voyage_loot tables) supports later automation if the plugin
experiment ever yields chest deltas.
