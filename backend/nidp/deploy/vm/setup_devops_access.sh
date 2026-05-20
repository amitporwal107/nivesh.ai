#!/usr/bin/env bash
# setup_devops_access.sh
# Creates the 'devops' Linux user, installs an authorized SSH public key,
# and grants NOPASSWD sudo access for GitHub Actions CI/CD.
# Usage: sudo bash setup_devops_access.sh '<ssh-public-key>'
# Idempotent: safe to re-run; will not duplicate the key or recreate the user.

set -euo pipefail

PUBLIC_KEY="${1:-}"

if [[ -z "$PUBLIC_KEY" ]]; then
  echo "ERROR: public key argument is required." >&2
  echo "Usage: sudo bash $0 '<ssh-ed25519 AAAA...>'" >&2
  exit 1
fi

if [[ "$EUID" -ne 0 ]]; then
  echo "ERROR: this script must be run as root (use sudo)." >&2
  exit 1
fi

# --- Create user -----------------------------------------------------------

if id devops &>/dev/null; then
  USER_STATUS="already exists"
else
  useradd --create-home --shell /bin/bash devops
  USER_STATUS="created"
fi

DEVOPS_HOME="$(getent passwd devops | cut -d: -f6)"

# --- Install SSH key -------------------------------------------------------

SSH_DIR="$DEVOPS_HOME/.ssh"
AUTH_KEYS="$SSH_DIR/authorized_keys"

mkdir -p "$SSH_DIR"
chmod 700 "$SSH_DIR"
touch "$AUTH_KEYS"
chmod 600 "$AUTH_KEYS"
chown -R devops:devops "$SSH_DIR"

if grep -qF "$PUBLIC_KEY" "$AUTH_KEYS" 2>/dev/null; then
  KEY_STATUS="already present"
else
  echo "$PUBLIC_KEY" >> "$AUTH_KEYS"
  KEY_STATUS="added"
fi

# --- Sudoers drop-in -------------------------------------------------------

SUDOERS_FILE="/etc/sudoers.d/devops-nopasswd"

echo "devops ALL=(ALL) NOPASSWD: ALL" > "$SUDOERS_FILE"
chmod 440 "$SUDOERS_FILE"

if ! visudo -c -f "$SUDOERS_FILE"; then
  echo "ERROR: sudoers validation failed — removing $SUDOERS_FILE" >&2
  rm -f "$SUDOERS_FILE"
  exit 1
fi

# --- Summary ---------------------------------------------------------------

echo ""
echo "devops user setup complete"
echo "  user        : devops ($USER_STATUS)"
echo "  home        : $DEVOPS_HOME"
echo "  ssh key     : $KEY_STATUS in $AUTH_KEYS"
echo "  sudoers     : $SUDOERS_FILE (validated OK)"
echo ""
