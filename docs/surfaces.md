# Surfaces: Web & Discord

Decision: **web-first, Discord as close to parity as technically possible.**
Work is done by LLMs, so raw effort is not the constraint — missing specification
is. This doc is that specification: every capability is defined once, then
implemented on both surfaces (or explicitly declared single-surface).

## Capability matrix

| Capability | Web | Discord |
|---|---|---|
| Browse open quests + tree state | questboard page (fine-grained tree) | embed menu per quest (ingredient summary, not full depth) |
| Create quest | form (title, root item w/ autocomplete, qty, HQ?, deadline, manual children) | `/quest create` modal; item via name search |
| Pledge parent or child node, partial amounts | tree UI, per-node "pledge X" | Contribute button → select node from ingredient list → amount modal |
| Withdraw / change own pledge | yes | yes |
| Mark own pledge turned in | yes | button on own pledge / thread command |
| View event log / history | quest history panel | pinned in quest thread (rolling) |
| Edit/close/cancel quest (officer) | yes | `/quest close|cancel` officer-gated |
| Re-expand tree (officer) | button | `/quest reexpand` |
| Set/change deadline | yes | `/quest deadline` |
| Opt into reminders, daily/weekly | toggle on quest | same via button/command |
| Universalis price hints | item detail popover | in embed footer/field |
| Voyage-linked quest ("job") | voyage page → open job | `/voyage job` |

Discord parity rule of thumb: **everything doable on web is doable in Discord
in a coarser but complete form** (modals/select menus instead of free-form
tree editing). Full-fidelity tree manipulation stays web-only by design.

## Sync model

Single source of truth = database. Both surfaces read/write through the shared
core (`core/db.py` helpers), never through each other.

- Every state change appends to `quest_events` and bumps `updated_at`.
- **Web reactivity:** SSE channel per questboard view (pattern already exists
  for party compute streaming); clients refresh affected subtrees on events.
- **Discord reactivity:** the bot consumes an internal SSE stream from the
  FastAPI app (bot = SSE client over asyncio; localhost/shared-secret) and
  edits the quest embed per event. Hybrid delivery: live push for immediacy +
  `updated_at` watermark check on connect/reconnect so events missed during a
  drop or bot restart are caught. No DB polling loop.
- Conflict policy: last-write-wins per field; pledges are additive rows so
  concurrent pledging cannot clobber.

## Quest threads

Each quest gets one Discord **thread** (created from the announcement embed):
announcement post with ingredient summary, live-updating status embed, and the
event history rolling in as short messages. Thread auto-rename follows quest
status (`[OPEN] 400 Croissants` → `[DONE] …`). Completion posts a final summary
(who pledged/delivered what) — doubles as FC credit record.
