# Integration: consolegameswiki recipe data & the item catalog

Purpose: resolve "400 wheels" into its full material tree automatically, flag
capped/limited inputs, and provide item search. Manual tree entry stays
available for anything the pipeline can't resolve.

## Source

consolegameswiki (ffxiv.consolegameswiki.com) — chosen by maric as
pretty good/complete. Per-item pages expose recipe trees, acquisition sources,
and whether an input is capped (weekly books, scrip items, timed nodes).

## Pipeline

1. **Item resolution:** user types a name (web autocomplete / Discord modal) →
   search against local `item_catalog`; on miss, live-search the wiki.
2. **Expansion:** fetch item page → parse recipe table recursively (BFS with
   depth cap ~8 and cycle guard), scaling quantities down the tree; store
   resulting tree JSON per quest node (`source: auto`).
3. **Cache-first:** every parsed item goes into `item_catalog` +
   `recipe_cache` tables with `fetched_at` and game-version tag.
   Lookups always serve from cache; network only on cache miss.
4. **Patch detection (decision: fully automatic):** scraper loop checks the
   wiki's game version/page daily (cheap single request). On change:
   mark all cached recipes stale; quests keep their stored trees (pledges never
   break silently); new expansions use fresh data; officers get a nudge that a
   re-expand is available for affected open quests.
5. **Politeness:** rate limit ~1 req/s (reuse scraper_loop discipline),
   descriptive User-Agent, backoff on 429s.

## Flags stored per ingredient

- `capped` / `weekly_limited` / `timed_node` — surfaced as a warning chip on
  quest nodes ("weekly-capped: plan across raiders") — informational only, no
  budgets tracked (explicit decision).
- buyable (vendor/gil), tradeable, gatherable — feeds buy-vs-craft hints.
- Universalis market price (separate cache, longer TTL).

## Failure modes

Wiki page layout changes → parser breaks → expansion falls back to manual-tree
mode for that item + error logged to event log + admin-visible scrape-failure
counter (same pattern as existing Lodestone scraper tests/fixtures: anonymized
HTML fixture in tests/).
