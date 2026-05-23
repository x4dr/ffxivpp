#!/usr/bin/env bash
# Manual deploy:  cd /path/to/ffxivpp && bash deploy/deploy.sh
set -euo pipefail
cd "$(dirname "$0")/.."

echo "=== Pulling latest ==="
git pull

echo "=== Installing deps ==="
uv sync

echo "=== Restarting services ==="
sudo systemctl restart ffxiv-flask ffxiv-bot

echo "=== Done ==="
