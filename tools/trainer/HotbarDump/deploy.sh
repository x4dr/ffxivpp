#!/usr/bin/env bash
# Build HotbarDump and copy it into Dalamud's dev plugin folder.
#
# Paths are derived from this script's own location, so it does not matter what
# the current working directory is. Override the destination with HOTBARDUMP_DEST
# (used by the test run) or DALAMUD_HOME if Dalamud lives somewhere unusual.
set -euo pipefail

here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
dal="${DALAMUD_HOME:-$HOME/.xlcore/dalamud/Hooks/15.0.3.7}"
dest="${HOTBARDUMP_DEST:-$HOME/.xlcore/dalamud/DalamudPlugins/dev/HotbarDump}"

cd "$here"

echo "building in $here"
DALAMUD_HOME="$dal" dotnet build -c Release -v quiet

if [ ! -d "$dal" ]; then
    echo "error: Dalamud not found at $dal" >&2
    echo "       set DALAMUD_HOME to your Hooks/<version> directory" >&2
    exit 1
fi

mkdir -p "$dest"
cp bin/Release/HotbarDump.dll bin/Release/HotbarDump.json "$dest/"

echo
echo "deployed to $dest"
python3 - "$dest/HotbarDump.json" <<'PY'
import json, sys
with open(sys.argv[1]) as fh:
    manifest = json.load(fh)
print("description:", manifest.get("Description"))
print("punchline:  ", manifest.get("Punchline"))
PY