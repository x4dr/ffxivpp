# Questboard

The centerpiece feature: FC-centric crafting quest management. Someone posts a
quest ("400 Makira Croissants for raid food"), the system resolves the craft
tree, members pledge materials or finished items, turn-ins are logged, Discord
and web show the same state.

## Quest model

A **Quest** is the container:

- id, title, free-text description
- status: `open` | `fulfilled` | `cancelled` (officer can close/cancel)
- created_by (Discord user id), created_at
- optional **deadline** (date); drives optional reminders (below)
- one root item requirement — a tree node (see below)

### Requirement tree

Each quest has a root **requirement node**: `{item_id, qty, quality}` where
quality ∈ {any, hq} (a quest may *demand HQ* ingredients; otherwise any).

Children are auto-expanded from the recipe data pipeline
(integrations-wiki-tree.md) when the item is craftable; creators can also add
children manually (manual trees always possible). Node attributes:

- item ref, required qty, quality flag
- source: `auto` (recipe expansion) or `manual`
- flags from the catalog: capped/limited resource, buyable, gatherable,
  vendor price, Universalis market price hint
- derived state: pledged qty, turned-in qty (see accounting)

**Substitution semantics (the core rule):** pledging a parent satisfies its
children proportionally. If a quest needs 400 wheels whose recipe is 5 logs
each → 2000 logs total; someone pledging "400 wheels" zeroes out the log
requirement. Pledging a child only affects that node. The UI always shows both
levels: "2000 logs — covered by Maric's 400 wheels".

Expansion depth: full recursive expansion with per-node quantities scaled down
the tree (classic recipe explosion), computed once at quest creation and stored;
re-expansion is manual (button) so pledges never dangle after a re-expand.
Cycles impossible (game recipes are acyclic; guard anyway).

## Pledges & turn-ins

A **Pledge**: `{quest_item_node, person (discord id), qty, quality commitment,
pledged_at}`. Multiple partial pledges per node allowed and summed. A pledge is
a statement of intent, not delivery.

A **Turn-in**: `{pledge (or ad-hoc), qty, turned_in_at}` — the pledger marks
their own contribution as delivered ("I brought the logs"). Every turn-in is
appended to the quest's event log and reduces the open requirement on that
node. No automatic completion detection: humans mark their own jobs done.

### Event log (`quest_events`)

Append-only audit trail per quest: created, expanded, pledge added/changed/
withdrawn, turn-in recorded, deadline set/changed, status changes, chest-snapshot
suggestions (when the experiment produces them). Rendered as quest history on
web and in the Discord thread.

## Permissions (decision: c)

- **Create quests:** anyone authenticated (guild member via Discord OAuth).
- **Pledge / mark own turn-ins:** anyone authenticated, own pledges only.
- **Moderate:** officers/admin roles (existing admin_roles table logic) can
  edit/close/cancel any quest, remove others' pledges, re-expand trees.
- Anonymous access: none. Identity = Discord identity, everywhere.

## Deadlines & reminders (opt-in)

- Quest may carry an optional deadline (e.g. "before Tuesday raid").
- Members opt in per quest (or globally "remind me about all open quests") to
  daily or weekly reminders of their own open pledges; **each member picks the
  time of day** their ping fires.
- Delivery: bot DM + a ping in the quest's Discord thread. Quiet hours respected
  (no reminders 01:00–08:00 local). Reminder scheduler lives in the bot process
  (it owns long-lived tasks); state read from shared DB.
- No nagging about capped-resource stock levels — people know their weeklies
  (explicit decision).

## Stock orders vs quests

"Make sure there are 300 popcorn in the chest" is just a quest without a
deadline and with a flat single-item tree. No separate standing-order concept
in v1 (revisit later if a convenient mechanism appears — decision recorded).

## Market hints

Item pages show Universalis price/NQ-HQ spread as an informational hint
("buy ~1.2k gil on Cactuar") to help pledgers choose buy-vs-craft. Non-binding,
cache aggressively (Universalis is rate-friendly but we poll politely).
