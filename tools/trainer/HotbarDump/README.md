# HotbarDump

A throwaway Dalamud dev plugin that dumps what is actually in the game, so the
`HOTBAR.DAT` parser can be checked against reality instead of against guesses.

It reads typed addon structs rather than the node tree:

```csharp
var bar = GameGui.GetAddonByName<AddonActionBar>("_ActionBar", 0);
var span = bar->ActionBarSlotVector.AsSpan();
int actionId = span[i].ActionId;      // what HOTBAR.DAT also stores
int layout  = (int)bar->ActionBarLayout;  // 1X12 / 2X6 / 3X4 / 4X3 / 6X2 / 12X1
```

`ActionBarSlot.ActionId` is the same identifier `HOTBAR.DAT` stores, which makes
it an oracle for the binary format. That is how the layout in
`docs/trainer-data-formats.md` was solved.

## Commands

```
/hbt             toggle the window
/hbdump          the candidate job bars
/hbdump all      every candidate addon name
/hbdump sheets   ClassJob + Action sheets (once)
/hbdump paths    print the output directory
```

Output lands in `pluginConfigs/HotbarDump/dumps/` as JSON.

## Build and deploy

```sh
tools/trainer/HotbarDump/deploy.sh
```

Copies `HotbarDump.dll` **and** `HotbarDump.json` into
`~/.xlcore/dalamud/DalamudPlugins/dev/HotbarDump/`. Both matter: the DLL holds
the behaviour, the manifest holds the build stamp. Dev-mode plugins auto-reload
when the files change.

Check the stamp in `/xlplugins`:

```
Dumps hotbar contents as JSON for offline analysis. compiled 20261018-173052
```

An old stamp means Dalamud did not reload the DLL: restart it. A Dalamud
restart also clears the "no config ui callback" warnings, which are evaluated
when plugins are scanned rather than when one is enabled.

On Windows `DALAMUD_HOME` is `%AppData%\XIVLauncher\addon\Hooks\<version>\`.

## Gotchas

- The addon name `_ActionBar` resolves at instance index **1**, not 0. The
  plugin tries both.
- Slot data is in `ActionBarSlotVector`, not in nodes. `ChildNode` is a pointer
  to the first child only, `NextSiblingNode` is not populated the way it looks,
  and `ChildCount` is a child count rather than a node-id range.
- `StdVector<T>.Get_Item` is an explicit interface implementation and cannot be
  called by name; use `AsSpan()`. `ActionBarSlotVector` holds slots by value.
- `SlotCount` is maintained separately from the vector's own `Count`. Clamp.
- There is **no addon enumeration API**, not in FFXIVClientStructs, not in
  Dalamud. The addon names are hypotheses; the dump records which name resolved,
  which struct matched and what actions it held, so bars are identified from
  their contents rather than from the name.

## Output

- `classjob.json`: every class job: id, category, abbreviation, name
- `actionmap.json`: every action: id, name, icon id
- `hotbar-<jobid>-<timestamp>.json`: per addon, the struct that matched, the
  bar layout, and per slot `index`, `actionId`, `hotbarId`