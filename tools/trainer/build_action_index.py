"""Bundle an action-id index into static/trainer/data/action_index.json.

Names have to resolve without Dalamud present: the trainer reads a player's
uploaded HOTBAR.DAT in the browser, on a machine that has never run the plugin.
The index is a flat {id: name} map, so the hotbar view works the moment a file
is uploaded and only icons need the network.

The source is the Action sheet the plugin dumped. When the plugin has also
dumped the Item sheet, ids that are items rather than abilities are merged in
under their item name, which is how a potion on a hotbar stops rendering as
`#1049238`.
"""

from __future__ import annotations

import json
import pathlib

ROOT = pathlib.Path(__file__).resolve().parent.parent.parent
DUMPS = pathlib.Path.home() / ".xlcore/pluginConfigs/HotbarDump/dumps"
OUT = ROOT / "static/trainer/data/action_index.json"

#: Filled from the Item sheet when available; kept so repeat runs stay stable.
ITEM_START = 100000


def load(name: str):
    path = DUMPS / name
    if not path.exists():
        return None
    with path.open(encoding="utf-8") as fh:
        return json.load(fh)


def main() -> int:
    actions = load("actionmap.json")
    if actions is None:
        print("no actionmap.json; run the plugin's sheet dump first")
        return 1

    index: dict[str, str] = {}
    for row in actions:
        name = row.get("name") or ""
        if name:
            index[str(row["id"])] = name

    from_actions = len(index)

    items = load("itemmap.json")
    merged = 0
    if items is None:
        print("no itemmap.json yet - item ids stay unnamed "
              "(run the plugin's sheet dump again to include them)")
    else:
        for row in items:
            key = str(row["id"])
            name = row.get("name") or ""
            if name and key not in index:
                index[key] = name
                merged += 1

    OUT.parent.mkdir(parents=True, exist_ok=True)
    with OUT.open("w", encoding="utf-8") as fh:
        json.dump(index, fh, ensure_ascii=False, sort_keys=True)

    size = OUT.stat().st_size / 1024
    print(f"wrote {OUT}: {from_actions} actions"
          + (f", +{merged} items" if items else "")
          + f" ({size:.0f} KB)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
