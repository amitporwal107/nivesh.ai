#!/usr/bin/env bash
# bootstrap-staging.sh — one-shot provisioner for the NIDP staging environment.
#
# Run as root on the VM where prod NIDP already runs.  Idempotent — safe to
# re-run.  Creates a fully isolated staging stack alongside prod:
#
#   Code repo:     /opt/nidp/dev-repo      (dev branch — separate from prod /opt/nidp/repo)
#   Service user:  nidp-staging            (home: /opt/nidp-staging)
#   TimescaleDB:   nidp-postgres-staging   (host port 5434, separate from prod 5433)
#   Venv:          /opt/nidp-staging/venv
#   Env file:      /opt/nidp-staging/nidp.env  (seeded from nidp.env.staging.example)
#   Migrations:    run manually after this script finishes
#   Cron:          NOT installed — no feeds fire until explicitly enabled
#
# Usage:
#   sudo bash bootstrap-staging.sh [--confirm]

set -euo pipefail

NIDP_STAGING_HOME=/opt/nidp-staging
NIDP_STAGING_USER=nidp-staging
DEV_REPO=/opt/nidp/dev-repo/nivesh.ai  # staging code — tracks the dev branch
REPO_URL="${NIDP_REPO_URL:-}"
REPO_BRANCH="${NIDP_REPO_BRANCH:-dev}"
DRY=true

for arg in "$@"; do
    case "$arg" in
        --confirm) DRY=false ;;
        --dry-run) DRY=true ;;
        -h|--help) sed -n '2,22p' "$0"; exit 0 ;;
        *) echo "Unknown arg: $arg" >&2; exit 2 ;;
    esac
done

log()   { printf '\033[1;36m[bootstrap-staging]\033[0m %s\n' "$*"; }
run()   { if $DRY; then log "DRY-RUN  $*"; else log "RUN  $*"; eval "$@"; fi; }

$DRY && log "🚧 dry-run mode. Re-run with --confirm to apply."

# ── 0. Root check ────────────────────────────────────────────────────
if [[ $EUID -ne 0 ]]; then
    echo "ERROR: this script must be run as root (sudo)." >&2; exit 1
fi

# ── 1. Service user ──────────────────────────────────────────────────
if ! id -u "$NIDP_STAGING_USER" >/dev/null 2>&1; then
    log "creating service user $NIDP_STAGING_USER"
    run "useradd --system --create-home --home-dir '$NIDP_STAGING_HOME' \
        --shell /bin/bash '$NIDP_STAGING_USER'"
else
    log "service user $NIDP_STAGING_USER already exists"
fi
run "mkdir -p '$NIDP_STAGING_HOME'/{logs,run,data/postgres,raw_archives}"
run "chown -R '$NIDP_STAGING_USER:$NIDP_STAGING_USER' '$NIDP_STAGING_HOME'"

# ── 2. Dev repo at /opt/nidp/dev-repo ────────────────────────────────
# Separate from prod's /opt/nidp/repo (main branch) so deploys don't collide.
run "mkdir -p /opt/nidp"
if [[ -d "$DEV_REPO/.git" ]]; then
    log "dev-repo already exists at $DEV_REPO — fetching latest dev branch"
    run "git -C '$DEV_REPO' fetch origin '$REPO_BRANCH'"
    run "git -C '$DEV_REPO' reset --hard 'origin/$REPO_BRANCH'"
elif [[ -n "$REPO_URL" ]]; then
    log "cloning dev branch from $REPO_URL → $DEV_REPO"
    run "git clone --depth=50 --branch='$REPO_BRANCH' '$REPO_URL' '$DEV_REPO'"
else
    log "WARNING: $DEV_REPO not found and NIDP_REPO_URL not set."
    log "         Run: NIDP_REPO_URL=<url> bash bootstrap-staging.sh --confirm"
    log "         or:  git clone --branch dev <url> $DEV_REPO"
fi
# Allow nidp-staging user to read the repo
if [[ -d "$DEV_REPO" ]]; then
    run "chown -R root:$NIDP_STAGING_USER '$DEV_REPO'"
    run "chmod -R g+rX '$DEV_REPO'"
fi

# ── 3. Python venv ────────────────────────────────────────────────────
if [[ ! -x "$NIDP_STAGING_HOME/venv/bin/python" ]]; then
    log "creating Python venv at $NIDP_STAGING_HOME/venv"
    run "sudo -u '$NIDP_STAGING_USER' python3.11 -m venv '$NIDP_STAGING_HOME/venv'"
fi
if [[ -f "$DEV_REPO/backend/nidp/deploy/requirements.txt" ]]; then
    log "installing NIDP requirements into staging venv"
    run "sudo -u '$NIDP_STAGING_USER' \
        '$NIDP_STAGING_HOME/venv/bin/pip' install --quiet --upgrade pip"
    run "sudo -u '$NIDP_STAGING_USER' \
        '$NIDP_STAGING_HOME/venv/bin/pip' install --quiet \
        -r '$DEV_REPO/backend/nidp/deploy/requirements.txt'"
fi

# ── 4. Env file placeholder ───────────────────────────────────────────
if [[ ! -f "$NIDP_STAGING_HOME/nidp.env" ]]; then
    log "seeding $NIDP_STAGING_HOME/nidp.env"
    EXAMPLE="$DEV_REPO/backend/nidp/deploy/vm/nidp.env.staging.example"
    if [[ -f "$EXAMPLE" ]]; then
        run "cp '$EXAMPLE' '$NIDP_STAGING_HOME/nidp.env'"
    else
        run "cp '$DEV_REPO/backend/nidp/deploy/vm/nidp.env.example' \
            '$NIDP_STAGING_HOME/nidp.env'"
    fi
    run "chown '$NIDP_STAGING_USER:$NIDP_STAGING_USER' '$NIDP_STAGING_HOME/nidp.env'"
    run "chmod 600 '$NIDP_STAGING_HOME/nidp.env'"
    log "  ⚠  edit $NIDP_STAGING_HOME/nidp.env and set NIDP_PG_PASSWORD before proceeding"
fi

# ── 5. Docker network + container ─────────────────────────────────────
if ! docker network inspect nidp-staging-bridge >/dev/null 2>&1; then
    log "creating docker network nidp-staging-bridge"
    run "docker network create nidp-staging-bridge"
else
    log "docker network nidp-staging-bridge already exists"
fi

COMPOSE_FILE="$DEV_REPO/backend/nidp/deploy/vm/docker-compose.staging.yml"
if [[ -f "$COMPOSE_FILE" ]]; then
    if ! docker ps --filter "name=nidp-postgres-staging" --format '{{.Names}}' \
            | grep -q nidp-postgres-staging; then
        log "starting staging TimescaleDB container"
        run "docker compose -f '$COMPOSE_FILE' \
            --env-file '$NIDP_STAGING_HOME/nidp.env' up -d"
    else
        log "nidp-postgres-staging container already running"
    fi
else
    log "WARNING: $COMPOSE_FILE not found — skipping container start"
fi

# ── 6. Logrotate ──────────────────────────────────────────────────────
log "configuring logrotate for staging"
if ! $DRY; then
cat > /etc/logrotate.d/nidp-staging <<'EOF'
/opt/nidp-staging/logs/*/*.log {
    daily
    rotate 7
    compress
    delaycompress
    missingok
    notifempty
    su nidp-staging nidp-staging
    create 0640 nidp-staging nidp-staging
    sharedscripts
}
EOF
fi
$DRY && log "DRY-RUN  write /etc/logrotate.d/nidp-staging"

# ── 7. run_service.sh wrapper for staging ────────────────────────────
# Cron entries invoke this wrapper; it sources the staging env and runs
# Python from the dev-repo instead of /opt/nidp/repo.
STAGING_RS="$NIDP_STAGING_HOME/run_service.sh"
if [[ ! -f "$STAGING_RS" ]]; then
    log "writing staging run_service.sh at $STAGING_RS"
    if ! $DRY; then
cat > "$STAGING_RS" <<'RSEOF'
#!/usr/bin/env bash
# run_service.sh (staging) — sources /opt/nidp-staging/nidp.env,
# runs Python from /opt/nidp/dev-repo.
set -uo pipefail
NIDP_HOME=/opt/nidp-staging
DEV_REPO=/opt/nidp/dev-repo/nivesh.ai
SERVICE="${1:-}"; shift || true
if [[ -z "$SERVICE" ]]; then echo "usage: $0 <service> [args...]" >&2; exit 2; fi
LOG_DIR="$NIDP_HOME/logs/$SERVICE"
LOG_FILE="$LOG_DIR/$SERVICE.log"
LOCK_FILE="$NIDP_HOME/run/$SERVICE.lock"
mkdir -p "$LOG_DIR" "$NIDP_HOME/run"
set -a; source "$NIDP_HOME/nidp.env"; set +a
cd "$DEV_REPO/backend"
exec 9> "$LOCK_FILE"
if ! flock -n 9; then
    echo "[$(date -Iseconds)] $SERVICE skipped: previous run still active" >> "$LOG_FILE"
    exit 0
fi
START=$(date -Iseconds)
echo "[$START] starting $SERVICE $*" >> "$LOG_FILE"
"$NIDP_HOME/venv/bin/python" -m "nidp.services.$SERVICE" "$@" >> "$LOG_FILE" 2>&1
RC=$?
END=$(date -Iseconds)
if [[ $RC -eq 0 ]]; then echo "[$END] $SERVICE OK" >> "$LOG_FILE"
else echo "[$END] $SERVICE FAILED rc=$RC" >> "$LOG_FILE"; fi
exit $RC
RSEOF
        chmod +x "$STAGING_RS"
        chown "$NIDP_STAGING_USER:$NIDP_STAGING_USER" "$STAGING_RS"
    fi
else
    log "staging run_service.sh already exists at $STAGING_RS"
fi

log ""
log "✅ bootstrap-staging done."
log ""
log "Next steps:"
log "  1. Edit $NIDP_STAGING_HOME/nidp.env — set NIDP_PG_PASSWORD and all secrets"
log "  2. Run migrations against staging DB (port 5434):"
log "       psql postgresql://nidp_staging:<pw>@localhost:5434/nidp_staging \\"
log "           -f $DEV_REPO/backend/nidp/migrations/000_bootstrap.sql"
log "       # ... then 001 through latest migration"
log "  3. Install staging nginx vhost:"
log "       sudo bash $DEV_REPO/backend/nidp/deploy/vm/install_nginx_staging.sh"
log "  4. When ready to enable feeds, install the crontab:"
log "       sudo install -m 644 \\"
log "           $DEV_REPO/backend/nidp/deploy/vm/nidp.staging.cron \\"
log "           /etc/cron.d/nidp-staging"
log "       # then uncomment individual feed lines in /etc/cron.d/nidp-staging"
