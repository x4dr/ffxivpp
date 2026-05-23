#!/usr/bin/env bash
# Install script for FF14 Party Planner
# Usage: sudo bash deploy/install.sh
set -euo pipefail

REPO_DIR="$(cd "$(dirname "$0")/.." && pwd)"
USER_NAME="${SUDO_USER:-$(whoami)}"

if [[ "$EUID" -ne 0 ]]; then
  echo "This must be run as root (sudo bash deploy/install.sh)" >&2
  exit 1
fi

echo "Repo dir:   $REPO_DIR"
echo "User:       $USER_NAME"
echo ""

# --- systemd service files ---
for svc in ffxiv-flask ffxiv-bot; do
  src="$REPO_DIR/deploy/$svc.service"
  dst="/etc/systemd/system/$svc.service"
  sed "s|YOUR_USER|$USER_NAME|g; s|/path/to/ffxivpp|$REPO_DIR|g" "$src" > "$dst"
  chmod 644 "$dst"
  echo "Installed:  $dst"
done

# --- nginx ---
src="$REPO_DIR/deploy/nginx.conf"
dst="/etc/nginx/sites-enabled/ffxiv"
sed "s|YOUR_USER|$USER_NAME|g; s|/path/to/ffxivpp|$REPO_DIR|g" "$src" > "$dst"
chmod 644 "$dst"
echo "Installed:  $dst"

# --- sudoers ---
src="$REPO_DIR/deploy/sudoers"
dst="/etc/sudoers.d/ffxiv-pp"
sed "s|YOUR_USER|$USER_NAME|g; s|/path/to/ffxivpp|$REPO_DIR|g" "$src" > "$dst"
chmod 440 "$dst"
echo "Installed:  $dst"

echo ""
# --- enable & start ---
systemctl daemon-reload
systemctl enable --now ffxiv-flask ffxiv-bot
echo "Services:   enabled & started"

nginx -t && systemctl reload nginx
echo "Nginx:      config OK, reloaded"
