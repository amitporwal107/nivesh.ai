#!/usr/bin/env bash
# check-env.sh — validate a staging env file for the CloudPe VMs.
#
#   bash check-env.sh app  /opt/nivesh-staging/.env.staging
#   bash check-env.sh nidp /opt/nidp-staging/nidp.env
#
# Reports by variable NAME only — values are never printed.
#   exit 0  nothing missing (warnings may be shown)
#   exit 1  a required variable is missing/placeholder, or a GCP-only value remains

set -euo pipefail

KIND="${1:-}"
FILE="${2:-}"
[[ "$KIND" == "app" || "$KIND" == "nidp" ]] && [[ -n "$FILE" ]] \
    || { echo "usage: $0 app|nidp <env-file>" >&2; exit 2; }
[[ -r "$FILE" ]] || { echo "cannot read $FILE" >&2; exit 2; }

TAG="check-env"
# shellcheck source=lib/common.sh
source "$(dirname "$0")/lib/common.sh"

if [[ "$KIND" == "app" ]]; then
    # OPENAI_API_KEY: the backend fails at import without it.
    REQUIRED=(PI_POSTGRES_USER PI_POSTGRES_PASSWORD PI_POSTGRES_DB
              PI_MONGO_USER PI_MONGO_PASSWORD PI_MONGO_DB PI_REDIS_PASSWORD
              PI_PAN_ENCRYPTION_KEY OPENAI_API_KEY)
    # Previously resolved from Secret Manager or optional; features degrade without them.
    RECOMMENDED=(CASPARSER_API_KEY NIDP_DAAS_INTERNAL_TOKEN NIDP_QUERY_API_TOKEN
                 GOOGLE_CLIENT_ID GOOGLE_CLIENT_SECRET PI_ADMIN_TOKEN
                 SMTP_HOST SMTP_PORT SMTP_USERNAME SMTP_PASSWORD SMTP_FROM)
else
    REQUIRED=(NIDP_PG_USER NIDP_PG_PASSWORD NIDP_PG_DB NIDP_POSTGRES_URL
              NIDP_HOME NIDP_QUERY_API_TOKEN)
    RECOMMENDED=(NIDP_DAAS_INTERNAL_TOKEN OPENAI_API_KEY
                 NIDP_TELEGRAM_BOT_TOKEN NIDP_TELEGRAM_CHAT_ID)
fi

# Names whose mere presence means the file still expects GCP credentials.
GCP_NAMES=(GOOGLE_APPLICATION_CREDENTIALS PI_GCS_SA_KEY_PATH PI_GCS_BUCKET
           NIDP_GCS_BUCKET NIDP_VM_SA_KEY_PATH NSE_HTTPS_PROXY BSE_PROXY_URL)
# Value patterns that only resolve inside the GCP project/VPC.
GCP_VALUE_RE='(^|[^0-9])10\.160\.|gs://|metadata\.google\.internal|pkg\.dev'

rc=0

echo "== ${KIND} env: ${FILE}"

for name in "${REQUIRED[@]}"; do
    val=$(env_get "$name" "$FILE")
    if [[ -z "$val" ]]; then
        echo "MISSING   ${name}"; rc=1
    elif [[ "$val" == *CHANGEME* ]]; then
        echo "PLACEHOLDER ${name}"; rc=1
    fi
done

for name in "${RECOMMENDED[@]}"; do
    [[ -n "$(env_get "$name" "$FILE")" ]] || echo "warn: not set  ${name}"
done

for name in "${GCP_NAMES[@]}"; do
    val=$(env_get "$name" "$FILE")
    [[ -z "$val" ]] && continue
    if [[ "$val" =~ $GCP_VALUE_RE || "$name" == GOOGLE_APPLICATION_CREDENTIALS || "$name" == *_SA_KEY_PATH ]]; then
        echo "GCP-ONLY  ${name} (unset it, or point it at a non-GCP target)"; rc=1
    else
        echo "warn: review  ${name} (was GCP-coupled on the old VMs)"
    fi
done

# Any other variable still pointing into the GCP VPC / GCS / Artifact Registry.
while IFS= read -r name; do
    [[ " ${GCP_NAMES[*]} " == *" ${name} "* ]] && continue
    if [[ "$(env_get "$name" "$FILE")" =~ $GCP_VALUE_RE ]]; then
        echo "GCP-ONLY  ${name} (value points into GCP)"; rc=1
    fi
done < <(grep -oE '^[[:space:]]*(export[[:space:]]+)?[A-Za-z_][A-Za-z0-9_]*=' "$FILE" \
            | sed -E 's/^[[:space:]]*(export[[:space:]]+)?//; s/=$//' | sort -u)

if [[ "$KIND" == "app" ]]; then
    stub=$(env_get PI_GCS_STUB "$FILE")
    if [[ -n "$stub" && "${stub,,}" != "true" ]]; then
        echo "GCP-ONLY  PI_GCS_STUB (must be true or unset — there are no GCS credentials here)"; rc=1
    fi
else
    backend=$(env_get NIDP_STORAGE_BACKEND "$FILE")
    if [[ "${backend,,}" == "gcs" ]]; then
        echo "GCP-ONLY  NIDP_STORAGE_BACKEND (gcs — use local)"; rc=1
    fi
fi

if (( rc == 0 )); then echo "RESULT: OK"; else echo "RESULT: FIX THE ITEMS ABOVE"; fi
exit "$rc"
