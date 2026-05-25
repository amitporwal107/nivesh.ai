#!/usr/bin/env bash
# setup_staging_secrets.sh — provision GCP Secret Manager secrets for NIDP staging.
#
# Creates a parallel set of secrets with a "-staging" suffix so the staging
# environment never shares secret values with production.
#
# Prod secret name     →  Staging secret name
# ──────────────────────────────────────────────────────
# NIDP_POSTGRES_URL    →  NIDP_POSTGRES_URL_STAGING
# NIVESH_POSTGRES_URL  →  NIVESH_POSTGRES_URL_STAGING
# NIDP_TELEGRAM_BOT_TOKEN  →  NIDP_TELEGRAM_BOT_TOKEN_STAGING
# NIDP_TELEGRAM_CHAT_ID    →  NIDP_TELEGRAM_CHAT_ID_STAGING
# NIDP_FRED_API_KEY    →  NIDP_FRED_API_KEY_STAGING
# NIDP_CLAUDE_API_KEY  →  NIDP_CLAUDE_API_KEY_STAGING
# NIDP_QUERY_API_TOKEN →  NIDP_QUERY_API_TOKEN_STAGING
#
# All secrets are created with placeholder value "SET_ME" — update them in
# the GCP console (or via `gcloud secrets versions add`) before running feeds.
#
# Usage:
#   ./setup_staging_secrets.sh --project=<GCP_PROJECT_ID> [--confirm]
#
# Env overrides:
#   GCP_PROJECT

set -euo pipefail

PROJECT="${GCP_PROJECT:-}"
DRY=true

for arg in "$@"; do
    case "$arg" in
        --project=*) PROJECT="${arg#*=}" ;;
        --confirm)   DRY=false ;;
        --dry-run)   DRY=true ;;
        -h|--help)   sed -n '2,22p' "$0"; exit 0 ;;
        *) echo "Unknown arg: $arg" >&2; exit 2 ;;
    esac
done

if [[ -z "$PROJECT" ]]; then
    echo "ERROR: --project is required (or set GCP_PROJECT env)" >&2
    exit 2
fi

if ! command -v gcloud >/dev/null; then
    echo "ERROR: gcloud CLI not found." >&2; exit 1
fi

ACTIVE_ACCT=$(gcloud auth list --filter=status:ACTIVE --format="value(account)" 2>/dev/null || true)
if [[ -z "$ACTIVE_ACCT" ]]; then
    echo "ERROR: no active gcloud account. Run: gcloud auth login" >&2; exit 1
fi

log()   { echo "[setup-staging-secrets] $*"; }
maybe() { if $DRY; then log "DRY-RUN  $*"; else log "RUN      $*"; eval "$@"; fi; }

$DRY && log "🚧 dry-run. Re-run with --confirm to create."

log "project:  $PROJECT"
log "caller:   $ACTIVE_ACCT"
log ""

# ── Staging secrets to create ────────────────────────────────────────
declare -A SECRETS=(
    [NIDP_POSTGRES_URL_STAGING]="postgresql://nidp_staging:SET_ME@localhost:5434/nidp_staging"
    [NIVESH_POSTGRES_URL_STAGING]="postgresql://SET_ME:SET_ME@localhost:5432/SET_ME"
    [NIDP_TELEGRAM_BOT_TOKEN_STAGING]="SET_ME"
    [NIDP_TELEGRAM_CHAT_ID_STAGING]="SET_ME"
    [NIDP_FRED_API_KEY_STAGING]="SET_ME"
    [NIDP_CLAUDE_API_KEY_STAGING]="SET_ME"
    [NIDP_QUERY_API_TOKEN_STAGING]="SET_ME"
    # Query API base URL for staging (Cloudflare A record → this VM, nginx routes by vhost)
    [NIDP_QUERY_API_BASE_URL_STAGING]="https://data.staging.niveshcopilot.com"
    # TLS certs for data.staging.niveshcopilot.com (self-signed or Cloudflare Origin CA)
    # Populate with: openssl req -x509 -newkey rsa:2048 -keyout /dev/stdout -out /dev/stdout \
    #   -days 3650 -nodes -subj "/CN=data.staging.niveshcopilot.com" 2>/dev/null | \
    #   <split cert/key and upload separately>
    [nidp-tls-cert-staging]="SET_ME_PEM_CERT"
    [nidp-tls-key-staging]="SET_ME_PEM_KEY"
)

for SECRET_NAME in "${!SECRETS[@]}"; do
    PLACEHOLDER="${SECRETS[$SECRET_NAME]}"

    if gcloud secrets describe "$SECRET_NAME" --project="$PROJECT" &>/dev/null; then
        log "  ✓ already exists: $SECRET_NAME (skipping)"
    else
        log "  creating: $SECRET_NAME"
        maybe "printf '%s' '$PLACEHOLDER' | gcloud secrets create '$SECRET_NAME' \
            --replication-policy=automatic \
            --data-file=- \
            --project='$PROJECT'"
    fi
done

log ""
log "─── IAM: grant staging SA access to staging secrets ───────────────"
# If a dedicated staging service account exists, grant it accessor role.
SA_STAGING="${NIDP_STAGING_SA:-}"
if [[ -n "$SA_STAGING" ]]; then
    for SECRET_NAME in "${!SECRETS[@]}"; do
        maybe "gcloud secrets add-iam-policy-binding '$SECRET_NAME' \
            --project='$PROJECT' \
            --member='serviceAccount:$SA_STAGING' \
            --role='roles/secretmanager.secretAccessor'"
    done
else
    log "NIDP_STAGING_SA not set — skipping IAM bindings."
    log "  To grant access later:"
    log "    gcloud secrets add-iam-policy-binding <SECRET> \\"
    log "      --project=$PROJECT \\"
    log "      --member=serviceAccount:<SA_EMAIL> \\"
    log "      --role=roles/secretmanager.secretAccessor"
fi

log ""
if $DRY; then
    log "✅ dry-run complete. Re-run with --confirm to apply."
else
    log "✅ staging secrets created in project $PROJECT."
    log ""
    log "Next: update each secret value in the GCP Console or via:"
    log "  printf '%s' '<value>' | gcloud secrets versions add <SECRET_NAME> \\"
    log "      --data-file=- --project=$PROJECT"
    log ""
    log "Secrets to fill in:"
    for SECRET_NAME in "${!SECRETS[@]}"; do
        log "  $SECRET_NAME"
    done
fi
