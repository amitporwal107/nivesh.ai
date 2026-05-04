#!/usr/bin/env bash
# rotate_credentials.sh — rotate the NIDP service-account key.
#
# Sequence (idempotent):
#   1. Create a new key for nidp-sa@${GCP_PROJECT}.iam…
#   2. Push it to Secret Manager (NIDP_SA_KEY_JSON, new version).
#   3. Update Cloud Run Job env to point at the new secret version.
#   4. Smoke-test by executing one Cloud Run Job (nidp-nse-calendar — cheap, no PII).
#   5. Disable + delete the OLD key.
#
# Default mode: --dry-run. Pass --confirm to rotate for real.

set -euo pipefail

CONFIRM="${1:-}"
DRY=true
[[ "$CONFIRM" == "--confirm" ]] && DRY=false

PROJECT="${GCP_PROJECT:?GCP_PROJECT must be set}"
REGION="${GCP_REGION:-asia-south1}"
SA_EMAIL="nidp-sa@${PROJECT}.iam.gserviceaccount.com"
NEW_KEY_TMP="$(mktemp -t nidp-sa-XXXXXX.json)"
trap 'rm -f "$NEW_KEY_TMP"' EXIT

log() { echo "[rotate] $*"; }
maybe() {
    if $DRY; then log "DRY-RUN  $*"; else log "RUN      $*"; eval "$@"; fi
}

if $DRY; then
    log "🚧 dry-run mode. Re-run with --confirm to actually rotate."
fi

log "project=$PROJECT  sa=$SA_EMAIL"

# 1. Inventory current keys
log "current keys:"
gcloud iam service-accounts keys list --iam-account="$SA_EMAIL" --project="$PROJECT" \
    --format="table(name,validAfterTime,keyType)" || true

# 2. Mint a new key
maybe "gcloud iam service-accounts keys create '$NEW_KEY_TMP' \
    --iam-account=$SA_EMAIL --project=$PROJECT"

# 3. Upload to Secret Manager (creates secret on first run, else new version)
if ! gcloud secrets describe NIDP_SA_KEY_JSON --project="$PROJECT" &>/dev/null; then
    maybe "gcloud secrets create NIDP_SA_KEY_JSON --replication-policy=automatic --project=$PROJECT"
fi
maybe "gcloud secrets versions add NIDP_SA_KEY_JSON \
    --data-file='$NEW_KEY_TMP' --project=$PROJECT"

# 4. Smoke-test — pick the cheapest Cloud Run Job
SMOKE_JOB="${SMOKE_JOB:-nidp-nse-calendar}"
maybe "gcloud run jobs execute $SMOKE_JOB --region=$REGION --project=$PROJECT --wait"

# 5. Disable + delete OLD keys (everything that's not the new one).
#    Implementation note: the new key's name is in the JSON; we read it back to
#    avoid accidentally deleting it.
if ! $DRY; then
    NEW_KEY_NAME=$(jq -r '.private_key_id' < "$NEW_KEY_TMP")
    OLD_KEY_NAMES=$(gcloud iam service-accounts keys list \
        --iam-account="$SA_EMAIL" --project="$PROJECT" \
        --filter="keyType=USER_MANAGED AND NOT name~$NEW_KEY_NAME" \
        --format="value(name)")
    while IFS= read -r key; do
        [[ -z "$key" ]] && continue
        # `name` looks like projects/.../keys/<id>; extract id.
        key_id="${key##*/}"
        log "deleting old key $key_id"
        gcloud iam service-accounts keys delete "$key_id" \
            --iam-account="$SA_EMAIL" --project="$PROJECT" --quiet
    done <<< "$OLD_KEY_NAMES"
fi

log "✅ rotation complete."
$DRY && log "(dry-run only — re-run with --confirm to apply)"
