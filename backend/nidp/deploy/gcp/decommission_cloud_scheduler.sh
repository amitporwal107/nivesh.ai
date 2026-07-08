#!/usr/bin/env bash
# decommission_cloud_scheduler.sh — WORK-0145: delete the legacy GCP Cloud
# Scheduler triggers now that VM cron (deploy/vm/nidp.cron) is the AUTHORITATIVE
# scheduler.
#
# The dual-scheduler era (VM cron + Cloud Scheduler firing the same jobs) risked
# double-runs and schedule drift ("change it in BOTH files"). VM cron is now the
# single source of truth (see nidp.cron header). This removes the `nidp-cron-*`
# Cloud Scheduler jobs so nothing fires them from the cloud side.
#
# Safe: DRY-RUN by default (lists what it would delete). Idempotent. Needs
# roles/cloudscheduler.admin.
#
#   ACCESS_TOKEN_FILE=/path/token ./decommission_cloud_scheduler.sh           # dry-run
#   ACCESS_TOKEN_FILE=/path/token CONFIRM=1 ./decommission_cloud_scheduler.sh  # delete
set -uo pipefail

PROJECT="${GCP_PROJECT:-niveshdataintelligence}"
REGION="${GCP_REGION:-asia-south1}"
GC=(gcloud --project="${PROJECT}")
[[ -n "${ACCESS_TOKEN_FILE:-}" ]] && GC+=(--access-token-file="${ACCESS_TOKEN_FILE}")

echo "== Cloud Scheduler jobs matching nidp-cron-* in ${REGION} =="
JOBS=$("${GC[@]}" scheduler jobs list --location="${REGION}" \
  --format="value(name.basename())" 2>/dev/null | grep -E '^nidp-cron-' || true)

if [[ -z "${JOBS}" ]]; then
  echo "None found — Cloud Scheduler is already decommissioned; VM cron is the only scheduler. ✓"
  exit 0
fi

echo "${JOBS}"
if [[ "${CONFIRM:-0}" != "1" ]]; then
  echo
  echo "DRY-RUN. These would be deleted. Re-run with CONFIRM=1 to delete them."
  echo "(VM cron in deploy/vm/nidp.cron will keep running everything.)"
  exit 0
fi

while read -r j; do
  [[ -z "$j" ]] && continue
  echo "deleting scheduler job: ${j}"
  "${GC[@]}" scheduler jobs delete "${j}" --location="${REGION}" --quiet
done <<< "${JOBS}"

echo "== done: Cloud Scheduler triggers removed. VM cron is the single scheduler. =="
