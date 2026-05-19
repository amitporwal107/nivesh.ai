#!/usr/bin/env bash
# restore_firewall.sh — re-create the pre-migration public firewall rules
# for nidp-stack-vm if a rollback from the HTTPS cutover is needed.
#
# Re-opens 8083 (DaaS), 8090 (Query), 3000 (Grafana) to 0.0.0.0/0 on the
# nidp-stack tag. Use only if the new HTTPS path proves unworkable and
# you need consumers to fall back to direct-IP HTTP access.
#
# Usage:
#   bash /opt/nidp/repo/backend/nidp/deploy/vm/restore_firewall.sh
#
# Requires: gcloud authenticated as a principal with compute.firewalls.create.

set -euo pipefail

PROJECT="niveshdataintelligence"
NETWORK="default"

log() { printf '\033[1;36m[restore_firewall]\033[0m %s\n' "$*"; }

log "Re-creating allow-nidp-daas-api"
gcloud compute firewall-rules create allow-nidp-daas-api \
  --project="$PROJECT" --network="$NETWORK" \
  --direction=INGRESS --action=ALLOW \
  --rules=tcp:8083 --source-ranges=0.0.0.0/0 \
  --target-tags=nidp-stack \
  --description="DaaS API public ingress (restored)" \
  2>/dev/null || log "  (already exists — skipping)"

log "Re-creating nidp-allow-query-api"
gcloud compute firewall-rules create nidp-allow-query-api \
  --project="$PROJECT" --network="$NETWORK" \
  --direction=INGRESS --action=ALLOW \
  --rules=tcp:8090,tcp:3000 --source-ranges=0.0.0.0/0 \
  --target-tags=nidp-stack \
  --description="Query API + Grafana public ingress (restored)" \
  2>/dev/null || log "  (already exists — skipping)"

log "Done. Verify with:"
log "  gcloud compute firewall-rules list --project=$PROJECT --filter='name~nidp'"
