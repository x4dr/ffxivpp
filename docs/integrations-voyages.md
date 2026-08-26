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

## Real data

`data/voyages/submarines-real.json` is generated from community-measured game
data by `tools/build_voyage_pack.py` (stdlib only). Regenerate with:

```sh
uv run python tools/build_voyage_pack.py        # uses .cache/voyages-src/
uv run python tools/build_voyage_pack.py --refresh   # force re-download
```

Sources (cached under `.cache/voyages-src/`, embedded in `meta.source`):

- **Loot + qty ranges**: saerielle's submersible loot DB (`export-items.json`)
  — community-measured drops for 128 sectors, min/max taken from the "Normal"
  quality column per loot tier.
- **Sector adjacency** (route walking): paultraylor.net's mermaid graphs,
  one block per sea. Sector names/letters also come from those node lists.
- **Surveillance breakpoints**: SubmarineTracker `Sectors.cs` `MapBreakpoints`
  — T2/T3 values per numeric sector id become the pack's `min_surveillance`
  gates (T1 is always surveillance 0).

The pack covers 6 seas (Deep-Sea Site, Sea of Ash, Sea of Jade, Sirensong Sea,
The Lilac Sea, South Indigo Deep), 128 sectors, ids like `deepsea-A`.
`load_pack(filename="submarines-real.json")` loads it explicitly; the default
`load_pack()` picks the newest `*.json` in `VOYAGE_DATA_DIR` by mtime, so the
operator picks per-deployment (e.g. drop the real pack in and touch it, or set
the filename in app config).

Caveats:

- `distance` is 0 for every sector — not derivable from these sources — so
  route range checks are vacuous (`reachable` is always true). Treat reachability
  as unimplemented for this pack.
- Routes are approximations: greedy walks along unlock edges (2–5 sectors),
  not game-optimal loops; `duration_minutes` is a flat 12h.
- Sectors are included only when the loot DB has measurements for them. The
  Northern Empty (patch 7.x map, 13 sectors with breakpoints but no measured
  loot) is therefore absent, as are any future unmeasured sectors.
- South Indigo Deep letters N–R have no adjacency data yet (adjacency page
  lags the loot DB) — they exist in the pack but appear in no route.
- Some newer-sector quantities are `[0, 0]` (unmeasured); the loot *names*
  are real, the qty ranges are placeholders until re-measured upstream.
