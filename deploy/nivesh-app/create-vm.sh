#!/usr/bin/env bash
# create-vm.sh — One-shot GCP VM provisioner for the nivesh-app stack.
# Run this from your laptop (needs gcloud auth).
#
# Usage:
#   bash deploy/nivesh-app/create-vm.sh

set -euo pipefail

PROJECT="niveshdataintelligence"
ZONE="asia-south1-a"
REGION="asia-south1"
VM_NAME="nivesh-app-vm"
MACHINE_TYPE="e2-standard-4"   # 4 vCPU, 16 GB RAM
DISK_SIZE="80GB"
DISK_TYPE="pd-ssd"
IMAGE_FAMILY="debian-12"
IMAGE_PROJECT="debian-cloud"
NETWORK="default"

log() { printf '\033[1;36m[create-vm]\033[0m %s\n' "$*"; }

# ── 1. Create VM ──────────────────────────────────────────────────────────────
log "Creating VM $VM_NAME in $ZONE ($MACHINE_TYPE, $DISK_SIZE SSD)..."
gcloud compute instances create "$VM_NAME" \
  --project="$PROJECT" \
  --zone="$ZONE" \
  --machine-type="$MACHINE_TYPE" \
  --boot-disk-size="$DISK_SIZE" \
  --boot-disk-type="$DISK_TYPE" \
  --image-family="$IMAGE_FAMILY" \
  --image-project="$IMAGE_PROJECT" \
  --network="$NETWORK" \
  --tags="nivesh-app,http-server" \
  --scopes="cloud-platform"

# ── 2. Firewall: HTTP ingress on port 80 ──────────────────────────────────────
log "Creating firewall rule: HTTP (80) ingress for nivesh-app..."
gcloud compute firewall-rules create allow-http-nivesh-app \
  --project="$PROJECT" \
  --network="$NETWORK" \
  --action=ALLOW \
  --rules=tcp:80 \
  --source-ranges=0.0.0.0/0 \
  --target-tags=nivesh-app \
  --description="HTTP ingress for nivesh-app VM (Nginx)" \
  2>/dev/null || log "firewall rule already exists — skipping"

# ── 3. Internal: nivesh-app → nidp-stack-vm (port 8083 DaaS, 8090 Query) ─────
log "Creating internal firewall: nivesh-app → nidp-stack-vm..."
gcloud compute firewall-rules create allow-nivesh-to-nidp \
  --project="$PROJECT" \
  --network="$NETWORK" \
  --action=ALLOW \
  --rules=tcp:8083,tcp:8090 \
  --source-tags=nivesh-app \
  --target-tags=nidp-stack \
  --description="Allow nivesh-app to reach NIDP DaaS/Query APIs" \
  2>/dev/null || log "internal firewall rule already exists — skipping"

# ── 4. Print next steps ───────────────────────────────────────────────────────
EXTERNAL_IP=$(gcloud compute instances describe "$VM_NAME" \
  --project="$PROJECT" --zone="$ZONE" \
  --format="get(networkInterfaces[0].accessConfigs[0].natIP)")

log ""
log "✅ VM created!"
log "   Name:        $VM_NAME"
log "   External IP: $EXTERNAL_IP"
log "   Zone:        $ZONE"
log ""
log "Next steps (run in order):"
log ""
log "  1. Copy deploy files to VM:"
log "       gcloud compute scp --recurse deploy/nivesh-app/ $VM_NAME:~ --project=$PROJECT --zone=$ZONE"
log ""
log "  2. SSH into VM:"
log "       gcloud compute ssh $VM_NAME --project=$PROJECT --zone=$ZONE"
log ""
log "  3. On the VM — run bootstrap (installs Docker, sets up dirs):"
log "       sudo bash ~/nivesh-app/bootstrap.sh"
log ""
log "  4. On the VM — run deploy (builds images, starts all services):"
log "       sudo EXTERNAL_IP=$EXTERNAL_IP bash ~/nivesh-app/deploy.sh"
log ""
log "  App will be live at: http://$EXTERNAL_IP"
log ""
log "  ⚠️  Also update Google OAuth Console:"
log "     Add http://$EXTERNAL_IP to Authorized Redirect URIs"
