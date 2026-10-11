#!/usr/bin/env bash
#
# install-code-server.sh — install code-server (VS Code in the browser) on a
# CloudPe Ubuntu 24.04 VM, for the user who runs this script.
#
# Run this ON the VM as your normal sudo user (e.g. `deploy`), NOT as root.
# It writes the config itself (so it does not depend on code-server's
# first-run behaviour), binds to 127.0.0.1 only, and starts a systemd service.
#
# ┌─ SECURITY ────────────────────────────────────────────────────────────────┐
# │ code-server is a full shell on this VM. It is bound to 127.0.0.1 and must  │
# │ only be reached through an SSH tunnel — never open port 8080 publicly.     │
# └────────────────────────────────────────────────────────────────────────────┘
#
# Usage (on the VM):
#   bash install-code-server.sh            # optional: PORT=8080
#
# Then from your laptop (Git Bash):
#   ssh -L 8080:127.0.0.1:8080 cloudpe1
#   open http://localhost:8080   (password is printed at the end of this script)

set -euo pipefail

PORT="${PORT:-8080}"
TARGET_USER="$(id -un)"

if [[ "$TARGET_USER" == "root" ]]; then
  echo "ERROR: run this as your normal sudo user (e.g. deploy), not root." >&2
  exit 1
fi

echo "==> Installing prerequisites"
sudo apt-get update -y
sudo apt-get install -y curl git build-essential openssl

echo "==> Installing code-server"
if ! command -v code-server >/dev/null 2>&1; then
  curl -fsSL https://code-server.dev/install.sh | sh
fi
command -v code-server >/dev/null 2>&1 || { echo "ERROR: code-server install failed" >&2; exit 1; }
code-server --version

echo "==> Writing config (~/.config/code-server/config.yaml)"
CONFIG_DIR="$HOME/.config/code-server"
CONFIG_FILE="$CONFIG_DIR/config.yaml"
mkdir -p "$CONFIG_DIR"
if [[ -f "$CONFIG_FILE" ]] && grep -q '^password:' "$CONFIG_FILE"; then
  PASSWORD="$(sed -n 's/^password: *//p' "$CONFIG_FILE")"
else
  PASSWORD="$(openssl rand -hex 16)"
fi
cat > "$CONFIG_FILE" <<EOF
bind-addr: 127.0.0.1:${PORT}
auth: password
password: ${PASSWORD}
cert: false
EOF
chmod 600 "$CONFIG_FILE"

echo "==> Enabling systemd service code-server@${TARGET_USER}"
sudo systemctl daemon-reload
sudo systemctl enable "code-server@${TARGET_USER}"
sudo systemctl restart "code-server@${TARGET_USER}"

echo "==> Verifying"
for _ in $(seq 1 15); do
  if curl -s -o /dev/null "http://127.0.0.1:${PORT}"; then break; fi
  sleep 1
done
if ! curl -s -o /dev/null "http://127.0.0.1:${PORT}"; then
  echo "ERROR: code-server is not answering on 127.0.0.1:${PORT}. Logs:" >&2
  sudo journalctl -u "code-server@${TARGET_USER}" -n 30 --no-pager >&2
  exit 1
fi
systemctl is-active "code-server@${TARGET_USER}"
curl -sI "http://127.0.0.1:${PORT}" | head -1

cat <<EOF

code-server is running on 127.0.0.1:${PORT} (not public).
Password: ${PASSWORD}   (also in ${CONFIG_FILE})

From your laptop (Git Bash):
  ssh -L ${PORT}:127.0.0.1:${PORT} cloudpe1
Then open: http://localhost:${PORT}
EOF
