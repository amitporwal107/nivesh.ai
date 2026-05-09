#!/usr/bin/env bash
# Run this ONCE to set up the fast-build infrastructure.
# Requires owner-level permissions on the project (or:
# roles/artifactregistry.admin + roles/cloudbuild.workerPoolOwner).
#
# Usage:
#   export PROJECT=niveshdataintelligence
#   gcloud auth login         # use your owner account
#   bash setup_fast_build_infra.sh

set -euo pipefail

PROJECT="${PROJECT:-niveshdataintelligence}"
REGION="${REGION:-asia-south1}"

echo "=== 1. Enable required APIs ==="
gcloud services enable \
  cloudbuild.googleapis.com \
  artifactregistry.googleapis.com \
  compute.googleapis.com \
  --project="$PROJECT"

echo ""
echo "=== 2. Create Artifact Registry cache repo ==="
gcloud artifacts repositories create nidp-cache \
  --repository-format=docker \
  --location="$REGION" \
  --description="Kaniko layer cache for NIDP service builds" \
  --project="$PROJECT" || echo "(already exists, continuing)"

echo ""
echo "=== 3. Create private worker pool ==="
gcloud builds worker-pools create nidp-private-pool \
  --project="$PROJECT" \
  --region="$REGION" \
  --worker-machine-type=e2-highcpu-8 \
  --worker-disk-size=200 || echo "(already exists, continuing)"

echo ""
echo "=== 4. Grant Cloud Build SA permission to write to the cache repo ==="
PROJECT_NUMBER=$(gcloud projects describe "$PROJECT" --format='value(projectNumber)')
CLOUD_BUILD_SA="${PROJECT_NUMBER}-compute@developer.gserviceaccount.com"

gcloud artifacts repositories add-iam-policy-binding nidp-cache \
  --location="$REGION" \
  --member="serviceAccount:${CLOUD_BUILD_SA}" \
  --role=roles/artifactregistry.writer \
  --project="$PROJECT" || true

echo ""
echo "=== 5. Verify ==="
gcloud builds worker-pools list --region="$REGION" --project="$PROJECT"
gcloud artifacts repositories list --location="$REGION" --project="$PROJECT"

echo ""
echo "✅ Done. Next steps:"
echo "  • Cancel any QUEUED builds: bash cancel_queued_builds.sh"
echo "  • Push code → triggers fire on the new private pool with Kaniko cache"
