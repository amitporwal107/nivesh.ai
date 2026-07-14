# WORK-0143 — Off-VM alert plane (GCP Cloud Monitoring) — APPLIED

- **Date:** 2026-07-07
- **Project:** niveshdataintelligence
- **Deliverable:** `backend/nidp/deploy/gcp/setup_offvm_alerts.sh` (reusable, idempotent)

## Why
Every monitor on `nidp-stack-vm` reads/writes the same DB/VM it watches, so a
disk-full → Postgres-down → VM-degraded outage blinds the monitoring AND kills its
ability to alert (HANDOFF §Theme B; the disk_monitor/notify path still *runs on* the
VM). This is an **external** alarm: Google's uptime probers hit the DaaS endpoints from
OUTSIDE the VM and Google's own pipeline emails on failure — it fires even if the VM is
completely dead/unreachable.

## Applied (LIVE) — real gcloud output
```
Created notification channel  …/notificationChannels/6847503309454751231  (email → aporwal107@gmail.com, enabled)
Created uptime  …/uptimeCheckConfigs/nidp-daas-liveness-prod-H97dMLDGuw4   (https data.niveshcopilot.com/daas/health, 5-min)
Created uptime  …/uptimeCheckConfigs/nidp-daas-readiness-staging-pTw1xR2JFlU (https staging-data.niveshcopilot.com/daas/readyz, 5-min)
Created alert policy …/alertPolicies/1567246470870787465  "ALERT: NIDP DaaS prod unreachable (off-VM uptime)"    → channel (enabled)
Created alert policy …/alertPolicies/1685530353168114254  "ALERT: NIDP DaaS staging unreachable (off-VM uptime)" → channel (enabled)
```
Verification: channel `enabled=True`; both policies `enabled=True` and wired to the
email channel. The checks pass now (both endpoints 200); if the VM/DB goes down (endpoint
unreachable, or staging `/readyz` → 503 on DB-down), the check fails and the policy emails
`aporwal107@gmail.com` after ~5 min — from Google's infra, independent of the VM.

## Verdict: PASS (resources live + enabled)

## Follow-ups
- **Prod DB-down coverage:** prod uses `/daas/health` (catches VM-unreachable) because
  `/daas/readyz` returns 404 on prod until the rollout. Re-run the script (adds a prod
  `/daas/readyz` check) after prod deploys `/readyz` → then prod also alerts on DB-down.
- **Email channel verification:** if the GCP Console shows it UNVERIFIED, click the
  verification link Google emails (channel is enabled; API-created email channels are
  typically active, but confirm receipt of the first test/alert).
- The pre-existing `[NIDP Console] Scheduled Job Failure` etc. policies still have empty
  notification channels — wire them to this channel too if you want those to page.
