#!/usr/bin/env bash
# Pull-based deploy check, run by ffxiv-deploy.timer once a minute.
#
# The server is behind NAT, so GitHub cannot call in. It fetches origin/main and
# only runs the deploy when the local HEAD is behind, which keeps the timer
# cheap and makes a failed fetch retry on the next tick.
set -euo pipefail
cd "$(dirname "$0")/.."
export PATH="/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin"

if command -v flock >/dev/null 2>&1; then
    exec 9>/tmp/ffxivpp-deploy.lock
    flock -n 9 || { echo "deploy already running"; exit 0; }
fi

local_rev="$(git rev-parse HEAD)"
git fetch --quiet origin main
remote_rev="$(git rev-parse origin/main)"
if [ "$local_rev" = "$remote_rev" ]; then
    exit 0
fi

echo "$(date -Is) deploying $local_rev -> $remote_rev"
exec "$(dirname "$0")/deploy.sh"
