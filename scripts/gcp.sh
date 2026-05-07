#!/usr/bin/env bash
# scripts/gcp.sh — wrapper around gcloud that:
#   1. activates the access token from /app/.gcp-token (created out-of-band
#      by the user via SA impersonation; see Path B handshake)
#   2. forces project + region so I never accidentally hit the wrong account
#   3. appends a one-line audit record to /app/.gcp-actions.log per call
#
# Usage:  bash scripts/gcp.sh <gcloud-args...>
# Example: bash scripts/gcp.sh run jobs list --filter='name~^nidp-' --format=value(name)
#
# This wrapper is called by Claude during a debugging session. Every
# invocation is logged so the user can audit "what did Claude do?"
# without having to read chat history.
set -euo pipefail

TOKEN_FILE="${GCP_TOKEN_FILE:-/app/.gcp-token}"
AUDIT_LOG="${GCP_AUDIT_LOG:-/app/.gcp-actions.log}"
PROJECT="${GCP_PROJECT:-niveshdataintelligence}"
REGION="${GCP_REGION:-asia-south1}"

if [[ ! -f "$TOKEN_FILE" ]]; then
    echo "ERROR: $TOKEN_FILE missing — user must mint a token via the Path B handshake." >&2
    exit 2
fi

# CLOUDSDK_AUTH_ACCESS_TOKEN: gcloud honors this as a one-shot bearer
# token. No persistent gcloud config writes — the token lives only in
# the current process env. Strip whitespace/newlines defensively.
export CLOUDSDK_AUTH_ACCESS_TOKEN
CLOUDSDK_AUTH_ACCESS_TOKEN="$(tr -d '\n\r ' < "$TOKEN_FILE")"

# Default project + region so we never need --project / --region inline.
export CLOUDSDK_CORE_PROJECT="$PROJECT"
export CLOUDSDK_RUN_REGION="$REGION"
export CLOUDSDK_COMPUTE_REGION="$REGION"

# ── audit ──────────────────────────────────────────────────────────
ts="$(date -u +%FT%TZ)"
caller="${USER:-claude}"
# Redact any obvious secret-shaped args (just in case). Tokens are >40
# chars of base64-y stuff; never log the token file or anything that
# looks like a key.
safe_args="$(printf '%s' "$*" | sed -E 's#(/app/\.gcp-token|--data-file=[^ ]+|--key-file=[^ ]+)#<redacted>#g')"
printf '%s  %s  gcloud %s\n' "$ts" "$caller" "$safe_args" >> "$AUDIT_LOG"

# ── exec ───────────────────────────────────────────────────────────
exec gcloud "$@"
