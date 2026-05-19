#!/usr/bin/env bash
# ci-cd-setup-keys.sh — Generate SSH deploy keys for CI/CD and print setup instructions.
#
# Run this ONCE from any machine. It generates two key pairs:
#   1. nivesh-app-vm deploy key
#   2. nidp-stack-vm deploy key
#
# Then follow the printed instructions to:
#   a) Add public keys to each VM's authorized_keys
#   b) Add private keys as GitHub Secrets (or Jenkins credentials)

set -euo pipefail

KEY_DIR="${1:-./deploy/keys}"
mkdir -p "$KEY_DIR"
chmod 700 "$KEY_DIR"

log() { printf '\033[1;36m[setup]\033[0m %s\n' "$*"; }
ok()  { printf '\033[1;32m[setup]\033[0m %s\n' "$*"; }

# ── Generate keys ──────────────────────────────────────────────────────────────
for vm in nivesh-app nidp-stack; do
  KEY="$KEY_DIR/${vm}-deploy"
  if [[ -f "$KEY" ]]; then
    log "$vm key already exists at $KEY — skipping."
  else
    ssh-keygen -t ed25519 -f "$KEY" -N "" -C "github-actions-${vm}-$(date +%Y%m%d)" -q
    ok "Generated $KEY"
  fi
done

NIVESH_PUB=$(cat "$KEY_DIR/nivesh-app-deploy.pub")
NIDP_PUB=$(cat "$KEY_DIR/nidp-stack-deploy.pub")

# ── Instructions ───────────────────────────────────────────────────────────────
cat <<EOF

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  CI/CD Deploy Keys — Setup Instructions
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

STEP 1 — Add public keys to VMs (run on each VM as the deploy user)
───────────────────────────────────────────────────────

  ▶ On nivesh-app-vm (as aporwal107_gmail_com):
    echo '$NIVESH_PUB' >> ~/.ssh/authorized_keys
    chmod 600 ~/.ssh/authorized_keys

  ▶ On nidp-stack-vm (as aporwal107_gmail_com):
    echo '$NIDP_PUB' >> ~/.ssh/authorized_keys
    chmod 600 ~/.ssh/authorized_keys


STEP 2 — Add private keys as GitHub Secrets
───────────────────────────────────────────────────────
  URL: https://github.com/amitporwal107/nivesh.ai/settings/secrets/actions

  Create these secrets:

  Secret name              │ Value
  ─────────────────────────┼────────────────────────────────────────────
  SSH_USER                 │ aporwal107_gmail_com
  NIVESH_APP_VM_HOST       │ <IP of nivesh-app-vm>
  NIVESH_APP_VM_SSH_KEY    │ (paste contents of deploy/keys/nivesh-app-deploy)
  NIDP_VM_HOST             │ 34.93.60.254
  NIDP_VM_SSH_KEY          │ (paste contents of deploy/keys/nidp-stack-deploy)


STEP 3 — (If using Jenkins) Add credentials in Jenkins
───────────────────────────────────────────────────────
  Jenkins → Manage Jenkins → Credentials → System → Global

  Add: SSH Username with private key
    ID:          nivesh-app-vm-ssh
    Username:    aporwal107_gmail_com
    Private Key: (paste deploy/keys/nivesh-app-deploy)

  Add: SSH Username with private key
    ID:          nidp-stack-vm-ssh
    Username:    aporwal107_gmail_com
    Private Key: (paste deploy/keys/nidp-stack-deploy)

  Add: Secret text
    ID:    NIVESH_APP_VM_HOST
    Value: <IP of nivesh-app-vm>


STEP 4 — Set deployment branch
───────────────────────────────────────────────────────
  All deploys trigger off pushes to 'main' — feature branches are
  merged into main before they ship. If you ever need to deploy
  from a different branch, edit:
    .github/workflows/deploy-app.yml   → on.push.branches
    .github/workflows/deploy-nidp.yml  → on.push.branches


STEP 5 — Fix git remote (security)
───────────────────────────────────────────────────────
  Your current git remote embeds a GitHub PAT in the URL.
  Rotate that token and switch to SSH:

    git remote set-url origin git@github.com:amitporwal107/nivesh.ai.git

  Also update the REPO clone URL on both VMs so 'git pull' works
  without an embedded token. The easiest is to add a GitHub Deploy Key
  (read-only) for each VM:
    https://github.com/amitporwal107/nivesh.ai/settings/keys


━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

Private key files are in: $KEY_DIR/
⚠️  Do NOT commit the deploy/keys/ directory. It is gitignored below.

EOF

# Add keys dir to .gitignore
if ! grep -q "deploy/keys" /app/.gitignore 2>/dev/null; then
  echo "deploy/keys/" >> /app/.gitignore
  log "Added deploy/keys/ to .gitignore"
fi
