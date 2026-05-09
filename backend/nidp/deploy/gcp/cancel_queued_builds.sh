#!/usr/bin/env bash
# Cancel all currently QUEUED Cloud Build builds in asia-south1.
# Useful when you want to re-trigger them on the new private pool
# instead of waiting for the shared default pool to drain.
set -euo pipefail

PROJECT="${PROJECT:-niveshdataintelligence}"
REGION="${REGION:-asia-south1}"

echo "Listing QUEUED builds..."
queued=$(gcloud builds list --region="$REGION" --project="$PROJECT" \
           --filter='status=QUEUED' --format='value(id)')

if [ -z "$queued" ]; then
  echo "No queued builds."
  exit 0
fi

echo "Cancelling $(echo "$queued" | wc -l) builds..."
for id in $queued; do
  gcloud builds cancel "$id" --region="$REGION" --project="$PROJECT" --quiet &
done
wait
echo "✅ Done."
