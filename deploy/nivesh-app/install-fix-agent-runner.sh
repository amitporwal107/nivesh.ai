#!/usr/bin/env bash
# install-fix-agent-runner.sh — install the PR-only auto-fix runner cron on nivesh-app-vm.
#
# Run once as root on the VM:
#   sudo bash /opt/nivesh/repo/deploy/nivesh-app/install-fix-agent-runner.sh
#
# Idempotent. The runner polls the app for issues queued by "Fix it" / auto-triage,
# clones dev, generates an RCA + minimal fix, py_compiles, pushes a fix/WORK-… branch
# and opens a PR (never merges). Runs on the VM because the app container has no git.
#
# Required files (0600, owned by nivesh):
#   /opt/nivesh/.gh_pat             (GitHub PAT, scopes: contents + pull_requests = write)
#   /opt/nivesh/.openai_key         (OpenAI API key)
#   /opt/nivesh/.work_ingest_secret (same secret as the app's WORK_INGEST_SECRET)

set -euo pipefail

NIVESH_HOME=/opt/nivesh
LOG_DIR="$NIVESH_HOME/logs"
CRON_SRC="$NIVESH_HOME/repo/deploy/nivesh-app/fix-agent-runner.cron"
CRON_DST=/etc/cron.d/fix-agent-runner

log() { printf '\033[1;36m[fix-agent-runner]\033[0m %s\n' "$*"; }

if [[ $EUID -ne 0 ]]; then
    echo "must run as root (use sudo)" >&2
    exit 1
fi

[[ -f "$CRON_SRC" ]] || { echo "cron source not found at $CRON_SRC — is the repo checked out?" >&2; exit 1; }
[[ -x /usr/bin/python3 ]] || { echo "python3 not installed" >&2; exit 1; }
command -v git >/dev/null || { echo "git not installed on this VM — required for clone/push" >&2; exit 1; }

# ── 1. Log directory ─────────────────────────────────────────────────────────
install -d -m 0755 -o nivesh -g nivesh "$LOG_DIR"
touch "$LOG_DIR/fix-agent-runner.log"
chown nivesh:nivesh "$LOG_DIR/fix-agent-runner.log"
chmod 0640 "$LOG_DIR/fix-agent-runner.log"

# ── 2. Logrotate ─────────────────────────────────────────────────────────────
cat > /etc/logrotate.d/fix-agent-runner <<'EOF'
/opt/nivesh/logs/fix-agent-runner.log {
    daily
    rotate 14
    compress
    delaycompress
    missingok
    notifempty
    su nivesh nivesh
    create 0640 nivesh nivesh
}
EOF

# ── 3. Cron install (idempotent — only reload cron if the file changed) ──────
if ! cmp -s "$CRON_SRC" "$CRON_DST"; then
    log "installing cron: $CRON_SRC → $CRON_DST"
    install -m 0644 -o root -g root "$CRON_SRC" "$CRON_DST"
    systemctl reload cron 2>/dev/null || service cron reload 2>/dev/null || true
else
    log "cron unchanged"
fi

# ── 4. Auth file presence check (operator drops them; we never write secrets) ─
warn=0
for f in "$NIVESH_HOME/.gh_pat" "$NIVESH_HOME/.openai_key" "$NIVESH_HOME/.work_ingest_secret"; do
    if [[ ! -f "$f" ]]; then
        log "⚠  missing: $f"
        warn=1
    else
        chown nivesh:nivesh "$f"
        chmod 0600 "$f"
    fi
done
if [[ $warn -eq 1 ]]; then
    log ""
    log "Drop the missing files (0600, owned by nivesh). The GH/OpenAI ones are shared"
    log "with error-triage; the ingest secret must equal the app's WORK_INGEST_SECRET:"
    log "  echo -n '<gh-pat>'          > $NIVESH_HOME/.gh_pat"
    log "  echo -n '<openai-key>'      > $NIVESH_HOME/.openai_key"
    log "  echo -n '<ingest-secret>'   > $NIVESH_HOME/.work_ingest_secret"
    log "  chown nivesh:nivesh $NIVESH_HOME/.{gh_pat,openai_key,work_ingest_secret}"
    log "  chmod 600           $NIVESH_HOME/.{gh_pat,openai_key,work_ingest_secret}"
fi

log "✅ installed. To smoke-test now (processes the queue once, prints logs):"
log "   sudo -u nivesh /usr/bin/python3 $NIVESH_HOME/repo/backend/scripts/fix_agent_runner.py"
