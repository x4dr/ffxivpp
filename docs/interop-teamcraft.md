# Interop: Teamcraft / Artisan

Decision: **link out; no rebuild.** Teamcraft owns personal crafting workflows
(lists, inventory simulation, rotations); ffxivpp owns FC-centric quest
distribution and pledging. We do not duplicate it — we interoperate.

## Out: "do it in Teamcraft/Artisan"

Every quest item node gets a **link-out**: a Teamcraft list-import URL for that
item+quantity (their documented import-string format:
`itemId,recipeId|null,qty`, semicolon-separated, base64-wrapped share link).
One click → the member has the full tree in their own Teamcraft/Artisan
(Artisan imports Teamcraft lists natively) and can craft with their own tools.
Progress reporting back stays manual (pledge/turn-in buttons), by design.

## In: import quest definitions

"Create quest from Teamcraft list": paste a TC import string / share link →
fxxivpp parses item ids + quantities → builds the quest root + manual children,
then tries auto-expansion from our wiki pipeline to fill in what it can.
Same importer accepts plain `itemId,qty` JSON for tool-agnostic use.

## Evaluated and rejected (for v1)

- Live two-way sync with TC lists (no public API for third-party write-back;
  fragile).
- Inventory pull from TC desktop app (unsupported; our chest path covers FC
  stock, which is what actually matters here).

Revisit if members adopt the link-out flow heavily and ask for round-tripping.
