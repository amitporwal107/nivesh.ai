#!/usr/bin/env bash
# phase4_robust.sh — robust phase-4 (VM data plane bring-up).
#
# Replaces the inline phase 4 in gcp_full_setup.sh with retries +
# auto-grow-partition + docker-via-official-script. Run this once
# end-to-end; idempotent — safe to re-run if anything fails midway.
#
# Usage:
#   ./phase4_robust.sh
#
# Env (with sensible defaults):
#   GCP_PROJECT, GCP_REGION, GCP_ZONE, NIDP_VM_NAME

set -euo pipefail

PROJECT="${GCP_PROJECT:-niveshdataintelligence}"
REGION="${GCP_REGION:-asia-south1}"
ZONE="${GCP_ZONE:-${REGION}-a}"
VM="${NIDP_VM_NAME:-nidp-stack-vm}"

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
DEPLOY_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"

log()  { echo -e "\033[1;36m[phase4]\033[0m $*"; }
warn() { echo -e "\033[1;33m[phase4]\033[0m $*"; }
err()  { echo -e "\033[1;31m[phase4]\033[0m $*" >&2; }

# 1. Wait for SSH to come online (up to 5 min).
log "waiting for VM ${VM} SSH to become available..."
for i in $(seq 1 30); do
    if gcloud compute ssh "$VM" --zone="$ZONE" --project="$PROJECT" --quiet \
            --command='echo ssh-ok' &>/dev/null; then
        log "  ✓ SSH ready (attempt $i)"
        break
    fi
    if [[ $i -eq 30 ]]; then
        err "SSH never came up after 5 min. Inspect with:"
        err "  gcloud compute instances describe $VM --zone=$ZONE --project=$PROJECT"
        exit 1
    fi
    sleep 10
    echo -n "."
done

# 2. Grow root partition + filesystem to fill the 50GB disk (idempotent).
log "growing root partition + filesystem (idempotent)..."
gcloud compute ssh "$VM" --zone="$ZONE" --project="$PROJECT" --quiet --command='
    set -e
    if ! command -v growpart >/dev/null; then
        sudo apt-get update -qq
        sudo apt-get install -y -qq cloud-guest-utils
    fi
    # Detect root device — sda or nvme0n1 depending on machine type
    ROOT_PART=$(findmnt / -no SOURCE)        # /dev/sda1 or /dev/nvme0n1p1
    if [[ "$ROOT_PART" =~ ^/dev/(sd[a-z]|nvme[0-9]+n[0-9]+)p?([0-9]+)$ ]]; then
        DISK="/dev/${BASH_REMATCH[1]}"
        PART_NUM="${BASH_REMATCH[2]}"
        sudo growpart "$DISK" "$PART_NUM" 2>&1 || echo "(growpart noop)"
        sudo resize2fs "$ROOT_PART"
    fi
    echo "--- df ---"
    df -h /
'

# 3. Install Docker via the official script (handles compose plugin).
log "installing docker (skipped if already present)..."
gcloud compute ssh "$VM" --zone="$ZONE" --project="$PROJECT" --quiet --command='
    set -e
    if ! command -v docker >/dev/null; then
        curl -fsSL https://get.docker.com -o /tmp/get-docker.sh
        sudo sh /tmp/get-docker.sh
    fi
    sudo docker --version
    sudo docker compose version
'

# 4. Pre-create destination dir (pscp on Windows requires it).
log "ensuring /tmp/nidp exists on VM..."
gcloud compute ssh "$VM" --zone="$ZONE" --project="$PROJECT" --quiet \
    --command='sudo mkdir -p /tmp/nidp && sudo chmod 777 /tmp/nidp'

# 5. Push compose stack.
log "pushing docker-compose.dev.yml + prometheus.yml + grafana/ to VM..."
gcloud compute scp --recurse \
    "$DEPLOY_DIR/docker-compose.dev.yml" \
    "$DEPLOY_DIR/prometheus.yml" \
    "$DEPLOY_DIR/grafana" \
    "${VM}:/tmp/nidp/" \
    --zone="$ZONE" --project="$PROJECT" --quiet

# 6. Stage to /opt/nidp and bring stack up.
log "starting docker-compose stack (this takes 2-4 min on first pull)..."
gcloud compute ssh "$VM" --zone="$ZONE" --project="$PROJECT" --quiet --command='
    set -e
    sudo mkdir -p /opt/nidp
    sudo cp -r /tmp/nidp/* /opt/nidp/
    cd /opt/nidp
    # Clean any partial pulls from previous failed runs
    sudo docker system prune -f 2>&1 | tail -1 || true
    sudo docker compose -f docker-compose.dev.yml pull --quiet || true
    sudo docker compose -f docker-compose.dev.yml up -d
    sleep 8
    echo "--- container status ---"
    sudo docker compose -f docker-compose.dev.yml ps
    echo "--- disk ---"
    df -h /
'

# 7. Verify all expected containers are running.
log "verifying stack health..."
EXPECTED=(nidp-postgres nidp-redpanda nidp-schema-registry nidp-redis nidp-minio nidp-prometheus nidp-grafana)
RUNNING=$(gcloud compute ssh "$VM" --zone="$ZONE" --project="$PROJECT" --quiet \
    --command='sudo docker ps --format "{{.Names}}"' 2>/dev/null | tr -d '\r')
MISSING=()
for c in "${EXPECTED[@]}"; do
    if ! grep -q "^${c}$" <<< "$RUNNING"; then
        MISSING+=("$c")
    fi
done

if [[ ${#MISSING[@]} -eq 0 ]]; then
    log "✅ all 7 containers running on $VM"
    log "   next: ./gcp_full_setup.sh --project=$PROJECT --phase=5 --confirm"
else
    warn "missing containers: ${MISSING[*]}"
    warn "  inspect with: gcloud compute ssh $VM --zone=$ZONE --project=$PROJECT \\"
    warn "                  --command='sudo docker compose -f /opt/nidp/docker-compose.dev.yml logs --tail=50'"
    exit 1
fi
