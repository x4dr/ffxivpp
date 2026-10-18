# FFXIV data formats

What is needed to work on the trainer. Everything here is verified against real
data unless a section says otherwise.

The readers run in the browser (`static/trainer/js/`). `tests/js/` checks them
against synthetic containers built to the documented shape and against the real
`.DAT` files in the game's config directory, so a silently wrong parser fails
before it reaches the UI.

---

## .DAT container

Every character config file shares this shell:

```
17-byte header   u32 file_type, u32 max_size, u32 content_size, ...
content          max_size bytes; real data occupies the first content_size,
                 the rest is null padding
footer           15 null bytes
invariant        file_size == max_size + 32
```

Content bytes are XORed with a **per-file-type mask**, applied to content only:

| file | file_type | mask |
| --- | --- | --- |
| KEYBIND.DAT | `0x00650003` | `0x73` |
| HOTBAR.DAT | `0x00040002` | `0x31` |
| MACRO.DAT | `0x00020001` | `0x73` |
| GEARSET.DAT | `0x006b0005` | `0x73` |
| UISAVE.DAT | `0x00010009` | `0x31` |

The mask is not derivable from `file_type`; do not try to compute it. Windows and
Linux use identical files in identical formats; only the path differs.

## KEYBIND.DAT (`static/trainer/js/keybind_dat.js`)

After unmasking, a run of records then null padding:

```
'T' <u16 len> <name + NUL>   'C' <u16 len> <codes + NUL>
```

`len` counts the name **including** its NUL terminator. `codes` is a
comma-separated list of two optional `<keyid>.<modbits>` pairs, hex, trailing
comma included:

```
31.00,00.00,      key '1', no modifiers
31.04,00.00,      Alt+1
56.01,00.00,      Shift+V
```

`modbits`: `1` Shift, `2` Ctrl, `4` Alt.

**Key ids are `SeVirtualKey` values, not ASCII.** FFXIVClientStructs publishes
the enum at `FFXIV.Client.System.Input.SeVirtualKey` and types `KeySetting.Key`
as it, so it is the ground truth for what the file stores. Digits (`0x30`–`0x39`)
and letters (`0x41`–`0x5A`) coincide with ASCII, which is why the ids were once
mistaken for it. The rest does not:

| ids | meaning |
| --- | --- |
| `0x08`–`0x2F` | Backspace, Tab, Enter, Esc, Space, arrows, Insert/Delete, Print Screen (`0x2C`) |
| `0x60`–`0x6F` | numpad 0–9, then `* + , - . /` |
| `0x70`–`0x7B` | F1–F12 |
| `0x80`/`0x81` | NumLock / ScrollLock in this enum, not F17/F18 |
| `0x82`–`0x87` | F19–F24 |

Checked against this character's `KEYBIND.DAT`: `MOVE_STRIFE_L/R` are `0x41`/
`0x44` (A/D), `MENU` is `0x6A` (numpad multiply), `KEY_SCREENSHOT` is `0x2C`
(Print Screen), and hotbar 6's slots 1–9 are `0x61`–`0x69` (numpad 1–9).

Mouse buttons (`0x01`–`0x06`) and gamepad inputs (`0xA0`+) share the same value
space, but a browser `keydown` never reports them. `0x89`/`0x8C` are movement
directions. OEM punctuation (`0xBA`+) is not in the game's enum. All of those
stay unmapped rather than guessed.

A bind is **untrainable** (`Binding.trainable`) when the key id cannot be named,
because guessing would silently accept every miss, or when its second-slot key
cannot be named, since we cannot check whether the player is holding it.
Untrainable binds appear in the UI with a **teach** button.

## HOTBAR.DAT (`static/trainer/js/hotbar_dat.js`)

Records start at **offset 132**, 8 bytes each:

```
byte 0     page index, measured one position behind the record
byte 1     slot index, likewise one behind
byte 2     kind
bytes 3-6  value, little-endian u32
byte 7     block index
```

Consecutive records sharing byte 7 form a **block**. Block 0 is the character's
shared layout (271 records); every other block has exactly 288 = 18 bars × 16
slots.

**Block index is the ClassJob row id.** Blocks 1..14 hold Gladiator..Alchemist
in sheet order; 19 is Paladin, 28 Scholar, 33 Astrologian, 40 Sage. Bar 1 of a
job block is its class action bar and holds that job's abilities in canonical
order, verified against the running client for all 43 job blocks.

Bytes 0 and 1 satisfy `(position - 1) // 16, (position - 1) % 16` with zero
violations, so the writer stores index − 1. Use the record's position; the
fields are carried but not relied on.

**Bars are 16 slots wide**, only the first 12 have binds. Bars 1–10 are the only
hotbar pages that exist in game; 11+ are other data (bar 11 holds a Scholar
spread, bar 12 a mirrored bar 2) and must not be treated as trainable bars.

**Binds join here.** `HOTBAR_<bar>_<slot>`, bar 1-based, slot 1-based from the
12-character alphabet `1234567890AB` (`_0` is slot 10, `_A` is 11, `_B` is 12),
maps to record `(bar - 1) * 16 + (slot - 1)`. Confirmed by Adloquium, which the
character keeps on bar 1 slot 3 and which sits at position 2 of the Scholar
block.

`kind` does **not** indicate slot contents: Mount arrives as kind 1 in
Paladin's block, 12 in Archer's, 10 in Conjurer's. Emptiness is `value == 0`.
Kinds seen: 0, 1, 2, 4, 6, 7, 8, 9, 10, 11, 12, 15, 17, 18, 26, 27, 29, 30, 32,
33. Only 9 is understood, as the marker for ids ≥ 100000 (crafting actions).

**Unexplored:** blocks 64..85 also exist and are populated. What they are is
unknown: no claim has been verified about them, and earlier guesses (PvP
layouts, per-job bars) were speculation from a handful of examples. Likewise
bars 11-18 of any block: they are not hotbar pages in game, but what the file
stores there has not been worked out. `job_ids()` and `extra_blocks()` expose
the two ranges separately rather than guessing at the difference.

## Names and icons

**Action ids are the only reliable key.** Ids are unique, but:

- `icon: 405` is a placeholder on 46,061 of 51,501 Action rows (89%).
- 8,153 action names have more than one row across expansions (Succor has 5,
  Adloquium has 5).
- Crafting actions live from 100001 up and Lumina's `Action` sheet stops at row
  51500, so they have no name there.

So never resolve icon → name or name → action. Resolve **action id → name**.

**Items are stored with an offset.** An item slot on a hotbar is not the Item
row id directly: it is `1,000,000 + item id`. Bar 4 slot 5 here is `1049240`,
which is item 49240, Caramel Popcorn. This matters because action 49240 also
exists (Dark II), so the offset has to be removed before an Item lookup. The
offset, not the id itself, is what identifies the slot as an item.

`tools/trainer/resolve_items.mjs` scans the HOTBAR.DAT in use for that range and
writes base id → name and icon path into `static/trainer/data/item_index.json`,
using XIVAPI v2 for current items (v1 has no row for 49238). Values at
`2,000,000` and above also occur (`2,002,023` in this file); that offset is
unverified and stays unnamed.

Icons are keyed by id because name-keyed sources were tried first:
consolegameswiki's MD5 path pattern is real (`Adloquium.png` → `/9/9b/`) but only
11 of a Scholar's 36 distinct abilities actually resolve under their own names.

## Known gaps

1. **`HOTBAR.DAT` disagrees with the running client.** The class bar's slot 5
   is empty in the file but holds action 16457 in game; every other slot
   matches. Note slot numbering: bind names are 1-based, the plugin's dump is
   0-based, and index 4 is bind slot 5.
2. **The name source is stale.** Lumina's Action sheet calls 16457 "Prominence",
   a Paladin ability. It sits at slot 5 of the Paladin class bar, which is where
   Prominence belongs, and also at slot 5 of the Scholar class bar. What it is
   there is unknown.

   Note the Scholar block is not missing a raise: Scholar's is called
   **Resurrection** and is already on the class bar at slot 11. The Action sheet
   does carry rows named "Raise" (125, 6285, 16929, 25658, 29326, 32512,
   49287) but none of them is the Scholar's, which is why its absence from the
   block is not a gap.
3. **Per-bar shared vs job-specific is not in `HOTBAR.DAT`.** This is a global
   setting, one flag per bar rather than per job, so it would live in a global
   config. Comparing bars across job blocks measures contents, not the flag,
   and proves nothing about it. Not found.
4. **Bar geometry is not in the config files.** It is readable live:
   `AddonActionBar.ActionBarLayout` is an enum with `Layout12X1 / 1X12 / 2X6 /
   3X4 / 4X3 / 6X2`; `Layout1X12` is 128, so the values are not a 0-based
   sequence. The plugin dumps it.

Item icons use `/trainer/api/item-icon/<item id>` and XIVAPI v2, cached under an
`item-` prefix because an item id can equal an action id. The game's own Item
sheet is still the fallback source when the plugin dumps `itemmap.json`; the
xivapi route is what works when the game is not running.

## The Dalamud plugin

`tools/trainer/HotbarDump` dumps ground truth from the running client: action
ids, bar geometry and the ClassJob/Action sheets. It exists because
`HOTBAR.DAT` was undocumented and needed an oracle; the format in §3 was solved
by locating the ids it reported in the file.

Read `tools/trainer/HotbarDump/README.md` for the build and deploy loop, and
`tools/trainer/probe/Program.cs` for checking an API before using it.