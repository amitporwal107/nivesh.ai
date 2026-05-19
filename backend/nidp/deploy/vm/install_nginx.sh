#!/usr/bin/env bash
# install_nginx.sh — install / refresh the nginx reverse proxy on nidp-stack-vm.
#
# Idempotent. Pulls TLS material from GCP Secret Manager
# (nidp-tls-cert, nidp-tls-key) using the VM's attached service account.
#
# Usage (on the VM, as root):
#   sudo bash /opt/nidp/repo/backend/nidp/deploy/vm/install_nginx.sh
#
# Or remotely:
#   gcloud compute ssh nidp-stack-vm --zone=asia-south1-a --command="\
#     sudo bash /opt/nidp/repo/backend/nidp/deploy/vm/install_nginx.sh"

set -euo pipefail

PROJECT="niveshdataintelligence"
CONF_SRC="/opt/nidp/repo/backend/nidp/deploy/vm/nginx.conf"
CONF_DST="/etc/nginx/sites-available/nidp"
SSL_DIR="/etc/nginx/ssl"
CERT_FILE="$SSL_DIR/data.crt"
KEY_FILE="$SSL_DIR/data.key"

log()  { printf '\033[1;36m[install_nginx]\033[0m %s\n' "$*"; }
fail() { printf '\033[1;31m[install_nginx]\033[0m %s\n' "$*"; exit 1; }

[[ $EUID -eq 0 ]] || fail "must be run as root (use sudo)"
[[ -f "$CONF_SRC" ]] || fail "missing $CONF_SRC — pull latest repo first"
command -v gcloud >/dev/null 2>&1 || fail "gcloud not on PATH"

# ── 1. nginx package (idempotent) ─────────────────────────────────────
if ! command -v nginx >/dev/null 2>&1; then
  log "installing nginx"
  DEBIAN_FRONTEND=noninteractive apt-get update -qq
  DEBIAN_FRONTEND=noninteractive apt-get install -y -qq nginx
else
  log "nginx already installed"
fi

# ── 2. TLS material from Secret Manager ───────────────────────────────
install -d -m 0750 -o root -g root "$SSL_DIR"

log "fetching nidp-tls-cert from Secret Manager"
gcloud secrets versions access latest \
  --secret=nidp-tls-cert --project="$PROJECT" \
  | install -m 0644 -o root -g root /dev/stdin "$CERT_FILE"

log "fetching nidp-tls-key from Secret Manager"
gcloud secrets versions access latest \
  --secret=nidp-tls-key --project="$PROJECT" \
  | install -m 0600 -o root -g root /dev/stdin "$KEY_FILE"

# Sanity-check: openssl can parse the cert
openssl x509 -in "$CERT_FILE" -noout -subject -dates >/dev/null \
  || fail "fetched cert is not a valid X.509 PEM"

# ── 3. Install site config ────────────────────────────────────────────
log "installing $CONF_DST"
install -m 0644 -o root -g root "$CONF_SRC" "$CONF_DST"
ln -sf "$CONF_DST" /etc/nginx/sites-enabled/nidp
rm -f /etc/nginx/sites-enabled/default

# ── 4. Validate and reload ────────────────────────────────────────────
log "running nginx -t"
nginx -t

if systemctl is-active --quiet nginx; then
  log "reloading nginx"
  systemctl reload nginx
else
  log "starting nginx"
  systemctl enable --now nginx
fi

# ── 5. Local liveness check ───────────────────────────────────────────
sleep 1
if curl -sf -k https://127.0.0.1/health >/dev/null; then
  log "✓ origin HTTPS health OK"
else
  fail "origin HTTPS health failed — check: journalctl -u nginx -n 50"
fi

log "================================================================"
log "✓ install complete"
log "  Verify externally:"
log "    curl -sf https://data.niveshcopilot.com/health"
log "    curl -sf https://data.niveshcopilot.com/daas/health"
log "    curl -sf https://data.niveshcopilot.com/query/health"
log "================================================================"
