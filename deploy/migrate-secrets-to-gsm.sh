#!/usr/bin/env bash
#
# migrate-secrets-to-gsm.sh — push secrets from a local env file into Google
# Secret Manager, suffixing env-specific ones with the environment name.
#
# RUN THIS ON THE VM that holds the env file (it reads values locally; values
# never leave the box except into GSM). Requires gcloud auth with
# secretmanager.admin on the target project.
#
# Naming:
#   * Secrets in the SHARED list  → stored unsuffixed   (e.g. OPENAI_API_KEY)
#   * Everything else             → stored <NAME>_<ENV> (e.g. MONGO_URL_PROD)
#   * Secrets in the SKIP list    → never pushed (plainly non-secret config)
#
# Idempotent: creates the secret if missing, else adds a new version.
# DRY-RUN by default — prints only secret NAMES + the action, never values.
# Pass --apply as the 3rd arg to actually write.
#
#   Usage:
#     ./migrate-secrets-to-gsm.sh staging /opt/nivesh-staging/.env.staging          # dry-run
#     ./migrate-secrets-to-gsm.sh staging /opt/nivesh-staging/.env.staging --apply   # write
#     ./migrate-secrets-to-gsm.sh prod    /opt/nivesh-prod/.env.prod      --apply
#
set -euo pipefail

ENVNAME="${1:?usage: $0 <staging|prod> <env-file> [--apply]}"
ENVFILE="${2:?usage: $0 <staging|prod> <env-file> [--apply]}"
APPLY="${3:-}"
PROJECT="${GSM_PROJECT:-niveshdataintelligence}"
SUFFIX="$(printf '%s' "$ENVNAME" | tr '[:lower:]' '[:upper:]')"

# Identical across staging+prod → stored UNSUFFIXED (one shared GSM secret).
# Edit to taste before running. Third-party API keys + the OAuth app are
# typically shared; DB creds / encryption keys / admin tokens are per-env.
SHARED=(
  OPENAI_API_KEY ANTHROPIC_API_KEY EMERGENT_LLM_KEY
  ALPHA_VANTAGE_KEY FRED_API_KEY
  CASPARSER_API_KEY PI_CASPARSER_API_KEY
  GOOGLE_CLIENT_ID GOOGLE_CLIENT_SECRET
)

# Plainly non-secret config → never pushed to GSM.
SKIP=(
  APP_ENV DB_NAME CORS_ORIGINS GMAIL_REDIRECT_URI
  PI_NGINX_BIND_ADDR PI_NGINX_PORT PI_GCS_STUB PI_GCS_BUCKET
  PI_WEBHOOK_ENABLED PI_CASPARSER_BASE_URL
  NIDP_DAAS_BASE_URL NIDP_QUERY_API_URL NIDP_GRAFANA_URL REACT_APP_BACKEND_URL
)

_in() { local n="$1"; shift; local x; for x in "$@"; do [ "$x" = "$n" ] && return 0; done; return 1; }

[ -f "$ENVFILE" ] || { echo "env file not found: $ENVFILE" >&2; exit 1; }
command -v gcloud >/dev/null || { echo "gcloud not found on PATH" >&2; exit 1; }

[ "$APPLY" = "--apply" ] && MODE="APPLY" || MODE="DRY-RUN"
echo "# migrate-secrets-to-gsm  env=$ENVNAME  project=$PROJECT  mode=$MODE"
echo "# file=$ENVFILE"

created=0; updated=0; skipped=0
while IFS= read -r line || [ -n "$line" ]; do
  # strip leading whitespace; skip blanks, comments, and `export ` prefixes
  line="${line#"${line%%[![:space:]]*}"}"
  case "$line" in ''|\#*) continue;; esac
  line="${line#export }"
  [[ "$line" == *=* ]] || continue

  KEY="${line%%=*}"; VAL="${line#*=}"
  KEY="${KEY//[[:space:]]/}"
  # strip one layer of surrounding single or double quotes
  VAL="${VAL%\"}"; VAL="${VAL#\"}"
  VAL="${VAL%\'}"; VAL="${VAL#\'}"
  [ -n "$KEY" ] || continue

  if _in "$KEY" "${SKIP[@]}"; then echo "skip(config)  $KEY"; skipped=$((skipped+1)); continue; fi
  if [ -z "$VAL" ];           then echo "skip(empty)   $KEY"; skipped=$((skipped+1)); continue; fi

  if _in "$KEY" "${SHARED[@]}"; then GSMNAME="$KEY"; else GSMNAME="${KEY}_${SUFFIX}"; fi

  if [ "$MODE" = "DRY-RUN" ]; then echo "would-set     $GSMNAME"; continue; fi

  if gcloud secrets describe "$GSMNAME" --project "$PROJECT" >/dev/null 2>&1; then
    printf '%s' "$VAL" | gcloud secrets versions add "$GSMNAME" --project "$PROJECT" --data-file=- >/dev/null
    echo "added-version $GSMNAME"; updated=$((updated+1))
  else
    gcloud secrets create "$GSMNAME" --project "$PROJECT" --replication-policy=automatic >/dev/null
    printf '%s' "$VAL" | gcloud secrets versions add "$GSMNAME" --project "$PROJECT" --data-file=- >/dev/null
    echo "created       $GSMNAME"; created=$((created+1))
  fi
done < "$ENVFILE"

echo "# summary: created=$created added-version=$updated skipped=$skipped  (mode=$MODE)"
[ "$MODE" = "DRY-RUN" ] && echo "# DRY-RUN only — re-run with --apply to write to GSM."
exit 0
