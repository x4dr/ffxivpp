# Integration: FC chest visibility (Allagan interim + Dalamud mini-plugin)

Goal: "look into the company chest" from maric's PC to drive stock-orders and
fulfillment suggestions. Status: **experiment — might not work, we try.**
Everything here is additive; the questboard functions fully without it.

## Interim path: Allagan Tools JSON (no plugin dev)

1. Maric runs [Allagan Tools](https://github.com/Critical-Impact/InventoryTools)
   in game, copies/exports its inventory JSON (includes FC chest tabs).
2. **Automated watcher** (decision a+b): small local script on his PC watches
   the export location and pushes new snapshots to the API; manual paste/upload
   into the web UI also supported.
3. Server normalizes into `chest_snapshots` (`{item_id, qty, tab, fetched_at}`);
   snapshots are diffed against the previous one.

Uses: stock-order quests ("keep 300 popcorn") get current-chest display;
quest ingredient nodes show "already in chest: N"; diffs feed fulfillment
suggestions.

## Mini-plugin experiment (side project)

A tiny Dalamud plugin (C#, `plugins/` dir, own build) that reads FC chest
contents + audit-log-ish events opportunistically and reports to the API with
a shared-secret header.

- **Best-effort by design:** runs only while maric's game is up; the system
  treats chest data as *stale-until-refreshed*, never authoritative for
  completing anything.
- **Suggestion-only semantics:** when a diff shows materials arrived matching
  open pledges ("2000 logs appeared, Maric pledged 2000 logs"), the bot asks in
  the quest thread: "looks like this arrived — mark Maric's pledge turned in?"
  A human confirms. The plugin can never auto-complete (agreed decision).
- Scope guard: if audit-log reading proves unreliable/inaccessible, ship
  chest-snapshot-only and keep the suggestion flow based on deltas alone.

## Failure/isolation

All ingestion behind one endpoint with schema validation + per-source
deduplication. Bad/malformed uploads are rejected without touching quest state.
Feature flags: `CHEST_INGEST_ENABLED`, suggestion pings separately toggleable.
