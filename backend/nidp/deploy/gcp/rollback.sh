#!/usr/bin/env bash
# Rollback a NIDP Cloud Run job to its last :stable image (or any specific tag).
#
# Usage:
#   ./rollback.sh delivery                  # → :stable
#   ./rollback.sh price_adjuster <BUILD_ID> # → that exact build
set -euo pipefail

PROJECT="${PROJECT:-niveshdataintelligence}"
REGION="${REGION:-asia-south1}"

service="${1:?usage: rollback.sh <service> [tag]}"
tag="${2:-stable}"
service_dashed="${service//_/-}"
job="nidp-${service_dashed}"
img="${REGION}-docker.pkg.dev/${PROJECT}/nidp/${service}:${tag}"

# Verify tag exists
if ! gcloud artifacts docker images describe "$img" --project="$PROJECT" &>/dev/null; then
  echo "❌ tag not found: $img" >&2
  exit 1
fi

echo "rolling back $job → $img"
gcloud run jobs update "$job" \
  --image="$img" \
  --region="$REGION" --project="$PROJECT" --quiet

echo "✅ done. verify with: gcloud run jobs describe $job --region=$REGION"
