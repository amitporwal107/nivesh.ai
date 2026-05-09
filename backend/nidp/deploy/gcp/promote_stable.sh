#!/usr/bin/env bash
# Promote the currently-deployed image of a NIDP service to ":stable".
#
# Run AFTER you've verified a Cloud Run job is healthy in production.
# Pinning :stable lets `rollback.sh` revert to a known-good image
# without having to dig out a SHA.
#
# Usage:
#   ./promote_stable.sh delivery
#   ./promote_stable.sh price_adjuster
#   ./promote_stable.sh all     # promote every nidp-* job in one shot
set -euo pipefail

PROJECT="${PROJECT:-niveshdataintelligence}"
REGION="${REGION:-asia-south1}"

promote_one() {
  local service="$1"
  local service_dashed="${service//_/-}"
  local job="nidp-${service_dashed}"

  local current_img
  current_img=$(gcloud run jobs describe "$job" \
                  --region="$REGION" --project="$PROJECT" \
                  --format='value(spec.template.spec.template.spec.containers[0].image)' 2>/dev/null || true)

  if [ -z "$current_img" ]; then
    echo "skip $service — job $job not found"
    return
  fi

  local current_sha="${current_img##*:}"
  if [ "$current_sha" = "stable" ]; then
    echo "skip $service — already on :stable"
    return
  fi

  local repo_path="${current_img%:*}"
  echo "promoting $service ${current_sha} -> :stable"
  gcloud artifacts docker tags add \
    "${repo_path}:${current_sha}" \
    "${repo_path}:stable" \
    --project="$PROJECT" --quiet
}

if [ "${1:-}" = "all" ]; then
  for j in $(gcloud run jobs list --region="$REGION" --project="$PROJECT" \
              --format='value(name)' | grep '^nidp-' | grep -v -E 'keygen|migrations'); do
    svc="${j#nidp-}"
    svc="${svc//-/_}"
    promote_one "$svc"
  done
else
  promote_one "${1:?usage: promote_stable.sh <service|all>}"
fi
