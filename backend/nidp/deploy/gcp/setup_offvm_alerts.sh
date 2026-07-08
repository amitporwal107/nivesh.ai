#!/usr/bin/env bash
# setup_offvm_alerts.sh — WORK-0143: off-VM alert plane via GCP Cloud Monitoring.
#
# Why: every monitor on nidp-stack-vm reads/writes the same DB/VM it watches, so
# a disk-full -> Postgres-down -> VM-degraded outage BLINDS the monitoring and
# kills its ability to alert (HANDOFF-FEED-RELIABILITY.md Theme B). This creates
# an EXTERNAL alarm: Google's uptime checkers probe the DaaS /readyz endpoint
# from OUTSIDE the VM, and Google's alerting pipeline emails on failure — so it
# fires even if nidp-stack-vm is completely down / unreachable.
#
# /readyz returns HTTP 503 when the DB is unreachable (the disk-full outage),
# which /health hides (always 200). So the uptime check catches the dominant
# failure. NOTE: /readyz must be deployed on the target host (prod needs the
# rollout; staging already has it).
#
# Requires creds with roles/monitoring.editor. Idempotent: safe to re-run.
# APPLIED 2026-07-07 (WORK-0143): email channel + prod (/daas/health) & staging
# (/daas/readyz) uptime checks + 2 alert policies are LIVE in niveshdataintelligence.
# Re-run to add prod /daas/readyz once the prod rollout deploys it.
#
#   ACCESS_TOKEN_FILE=/path/to/token ALERT_EMAIL=you@example.com ./setup_offvm_alerts.sh
set -uo pipefail

PROJECT="${GCP_PROJECT:-niveshdataintelligence}"
ALERT_EMAIL="${ALERT_EMAIL:-aporwal107@gmail.com}"
GC=(gcloud --project="${PROJECT}")
[[ -n "${ACCESS_TOKEN_FILE:-}" ]] && GC+=(--access-token-file="${ACCESS_TOKEN_FILE}")

# Uptime targets: "display|host|path".
# prod uses /daas/health (catches VM unreachable now; /readyz returns 404 until the
# prod rollout — switch to /daas/readyz then for DB-down detection). staging has /readyz.
TARGETS=(
  "NIDP DaaS liveness (prod)|data.niveshcopilot.com|/daas/health"
  "NIDP DaaS readiness (staging)|staging-data.niveshcopilot.com|/daas/readyz"
)

echo "== 1. email notification channel =="
CH_NAME=$("${GC[@]}" beta monitoring channels list \
  --format="value(name,labels.email_address)" 2>/dev/null \
  | awk -v e="${ALERT_EMAIL}" '$2==e{print $1; exit}')
if [[ -z "${CH_NAME}" ]]; then
  CH_NAME=$("${GC[@]}" beta monitoring channels create \
    --display-name="NIDP feed-reliability alerts" --type=email \
    --channel-labels="email_address=${ALERT_EMAIL}" \
    --format="value(name)")
  echo "   created channel: ${CH_NAME}"
else
  echo "   reusing channel: ${CH_NAME}"
fi

for t in "${TARGETS[@]}"; do
  IFS='|' read -r DISPLAY HOST PATH_ <<< "${t}"
  echo "== 2. uptime check: ${DISPLAY} (${HOST}${PATH_}) =="
  CHECK_ID=$("${GC[@]}" monitoring uptime list-configs \
    --filter="displayName='${DISPLAY}'" --format="value(name.basename())" 2>/dev/null | head -1)
  if [[ -z "${CHECK_ID}" ]]; then
    "${GC[@]}" monitoring uptime create "${DISPLAY}" \
      --resource-labels="host=${HOST},project_id=${PROJECT}" \
      --protocol=https --port=443 --path="${PATH_}" \
      --period=5 --timeout=10
    CHECK_ID=$("${GC[@]}" monitoring uptime list-configs \
      --filter="displayName='${DISPLAY}'" --format="value(name.basename())" | head -1)
    echo "   created uptime check id: ${CHECK_ID}"
  else
    echo "   reusing uptime check id: ${CHECK_ID}"
  fi

  echo "== 3. alert policy: ${DISPLAY} failing -> email =="
  POLICY_FILE="$(mktemp)"
  cat > "${POLICY_FILE}" <<JSON
{
  "displayName": "ALERT: ${DISPLAY} unreachable / DB-down",
  "combiner": "OR",
  "conditions": [{
    "displayName": "${DISPLAY} uptime check failing",
    "conditionThreshold": {
      "filter": "metric.type=\"monitoring.googleapis.com/uptime_check/check_passed\" AND resource.type=\"uptime_url\" AND metric.label.\"check_id\"=\"${CHECK_ID}\"",
      "aggregations": [{
        "alignmentPeriod": "300s",
        "perSeriesAligner": "ALIGN_FRACTION_TRUE",
        "crossSeriesReducer": "REDUCE_MEAN",
        "groupByFields": ["resource.label.host"]
      }],
      "comparison": "COMPARISON_LT",
      "thresholdValue": 0.5,
      "duration": "300s",
      "trigger": {"count": 1}
    }
  }],
  "notificationChannels": ["${CH_NAME}"],
  "documentation": {
    "content": "DaaS /readyz is failing from Google's external probers — the NIDP VM is unreachable or Postgres is down (disk-full?). This alarm runs OFF the VM so it fires even when the VM is dead. Runbook: HANDOFF-FEED-RELIABILITY.md / prod-daas-disk-full-failure-mode.",
    "mimeType": "text/markdown"
  }
}
JSON
  EXIST=$("${GC[@]}" alpha monitoring policies list \
    --filter="displayName='ALERT: ${DISPLAY} unreachable / DB-down'" \
    --format="value(name)" 2>/dev/null | head -1)
  if [[ -z "${EXIST}" ]]; then
    "${GC[@]}" alpha monitoring policies create --policy-from-file="${POLICY_FILE}"
    echo "   created alert policy"
  else
    echo "   policy exists: ${EXIST}"
  fi
  rm -f "${POLICY_FILE}"
done

echo "== done. External uptime alarms on /readyz -> ${ALERT_EMAIL}. =="
echo "   (prod check needs /readyz deployed on data.niveshcopilot.com; staging is live.)"
