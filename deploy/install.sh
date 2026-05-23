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

if [[ "$USER_NAME" = "root" ]]; then
  echo "ERROR: Do not run as root directly. Use: sudo bash deploy/install.sh" >&2
  exit 1
fi

# guard against unusual chars that could break sed or config files
if [[ ! "$USER_NAME" =~ ^[a-zA-Z0-9._-]+$ ]]; then
  echo "ERROR: Invalid characters in username: $USER_NAME" >&2
  exit 1
fi
if [[ ! "$REPO_DIR" =~ ^[a-zA-Z0-9._/-]+$ ]]; then
  echo "ERROR: Invalid characters in repo path: $REPO_DIR" >&2
  exit 1
fi

echo "Repo dir:   $REPO_DIR"
echo "User:       $USER_NAME"
echo ""

_INSTALLED=()
_BAKS=()
_TEMPS=()
_SUCCESS=false

cleanup() {
  for f in "${_TEMPS[@]}"; do
    rm -f "$f"
  done
  if ! "$_SUCCESS"; then
    for f in "${_INSTALLED[@]}"; do
      local bak="${f}.bak"
      if [[ -f "$bak" ]]; then
        mv "$bak" "$f"
      else
        rm -f "$f"
      fi
    done
    echo "Restored original files after failure" >&2
  else
    for f in "${_BAKS[@]}"; do
      rm -f "$f"
    done
  fi
}
trap cleanup EXIT

# --- helper: escape | & \ for sed replacement delimiter safety ---
sed_escape() {
  local s="$1"
  s="${s//\\/\\\\}"
  s="${s//&/\\&}"
  s="${s//|/\\|}"
  printf '%s' "$s"
}

# --- helper: substitute placeholders and atomically write a system file ---
write_file() {
  local src="$1" dst="$2" mode="$3"
  if [[ ! -f "$src" ]]; then
    echo "ERROR: template not found: $src" >&2
    exit 1
  fi
  local tmp user_safe repo_safe
  tmp="$(mktemp "${dst}.XXXXXX")"
  _TEMPS+=("$tmp")
  user_safe="$(sed_escape "$USER_NAME")"
  repo_safe="$(sed_escape "$REPO_DIR")"
  sed "s|YOUR_USER|$user_safe|g; s|/path/to/ffxivpp|$repo_safe|g" "$src" > "$tmp"
  if grep -qE -- 'YOUR_USER|/path/to/ffxivpp' "$tmp"; then
    echo "ERROR: unreplaced placeholders in $dst" >&2
    exit 1
  fi
  if [[ -f "$dst" ]]; then
    cp -a "$dst" "${dst}.bak"
    _BAKS+=("${dst}.bak")
  fi
  chmod -- "$mode" "$tmp"
  mv "$tmp" "$dst"
  command -v restorecon &>/dev/null && restorecon "$dst" 2>/dev/null || true
  _INSTALLED+=("$dst")
  echo "Installed:  $dst"
}

# --- systemd service files ---
shopt -s nullglob
_SERVICES=()
for tmpl in "$REPO_DIR"/deploy/*.service; do
  name="$(basename "$tmpl" .service)"
  write_file "$tmpl" "/etc/systemd/system/${name}.service" 644
  _SERVICES+=("$name")
done
shopt -u nullglob

# --- nginx ---
NGINX_DIR="/etc/nginx"
[[ -d "$NGINX_DIR/sites-enabled" ]] || NGINX_DIR="$NGINX_DIR/conf.d"
write_file "$REPO_DIR/deploy/nginx.conf" "$NGINX_DIR/ffxiv" 644

command -v nginx &>/dev/null || { echo "ERROR: nginx not found" >&2; exit 1; }
if ! nginx -t; then
  echo "ERROR: nginx config test failed — not deployed" >&2
  exit 1
fi

# --- sudoers (validate on temp before placing) ---
SUDOERS_SRC="$REPO_DIR/deploy/sudoers"
SUDOERS_DST="/etc/sudoers.d/ffxiv-pp"
if [[ ! -f "$SUDOERS_SRC" ]]; then
  echo "ERROR: template not found: $SUDOERS_SRC" >&2
  exit 1
fi

command -v visudo &>/dev/null || { echo "ERROR: visudo not found" >&2; exit 1; }
command -v mktemp &>/dev/null || { echo "ERROR: mktemp not found" >&2; exit 1; }

SUDOERS_TMP="$(mktemp "${SUDOERS_DST}.XXXXXX")"
_TEMPS+=("$SUDOERS_TMP")
user_safe="$(sed_escape "$USER_NAME")"
repo_safe="$(sed_escape "$REPO_DIR")"
sed "s|YOUR_USER|$user_safe|g; s|/path/to/ffxivpp|$repo_safe|g" "$SUDOERS_SRC" > "$SUDOERS_TMP"
if grep -qE -- 'YOUR_USER|/path/to/ffxivpp' "$SUDOERS_TMP"; then
  echo "ERROR: unreplaced placeholders in $SUDOERS_DST" >&2
  exit 1
fi
chmod -- 440 "$SUDOERS_TMP"
visudo -c -f "$SUDOERS_TMP" || {
  echo "ERROR: sudoers syntax invalid — aborting" >&2
  exit 1
}
if [[ -f "$SUDOERS_DST" ]]; then
  cp -a "$SUDOERS_DST" "${SUDOERS_DST}.bak"
  _BAKS+=("${SUDOERS_DST}.bak")
fi
mv "$SUDOERS_TMP" "$SUDOERS_DST"
command -v restorecon &>/dev/null && restorecon "$SUDOERS_DST" 2>/dev/null || true
_INSTALLED+=("$SUDOERS_DST")
echo "Installed:  $SUDOERS_DST"

echo ""
# --- enable & start ---
systemctl daemon-reload
systemctl enable --now "${_SERVICES[@]}"
echo "Services:   enabled & started"

systemctl reload-or-restart nginx
echo "Nginx:      config OK, reloaded"

echo ""
echo "Installation complete."
_SUCCESS=true
