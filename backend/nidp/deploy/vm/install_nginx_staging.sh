#!/usr/bin/env bash
# install_nginx_staging.sh — add the staging nginx vhost for data.staging.niveshcopilot.com.
#
# Idempotent. Pulls staging TLS material from GCP Secret Manager
# (nidp-tls-cert-staging, nidp-tls-key-staging) using the VM's SA.
#
# Run AFTER install_nginx.sh (prod vhost must already be in place).
#
# Usage (on the VM, as root):
#   sudo bash /opt/nidp/repo/backend/nidp/deploy/vm/install_nginx_staging.sh
#
# TLS certs for staging can be:
#   • A Cloudflare Origin CA cert (preferred — generated in CF dashboard)
#   • A Let's Encrypt cert for data.staging.niveshcopilot.com
#   • A self-signed cert (Cloudflare Full mode accepts self-signed from origin)
#
# To generate a self-signed staging cert (operator one-liner):
#   openssl req -x509 -newkey rsa:2048 -keyout /tmp/stag.key -out /tmp/stag.crt \
#     -days 3650 -nodes -subj "/CN=data.staging.niveshcopilot.com"
#   printf "%s" "$(cat /tmp/stag.crt)" | \
#     gcloud secrets create nidp-tls-cert-staging --replication-policy=automatic \
#       --data-file=- --project=niveshdataintelligence
#   printf "%s" "$(cat /tmp/stag.key)" | \
#     gcloud secrets create nidp-tls-key-staging --replication-policy=automatic \
#       --data-file=- --project=niveshdataintelligence

set -euo pipefail

PROJECT="niveshdataintelligence"
CONF_SRC="/opt/nidp/dev-repo/nivesh.ai/backend/nidp/deploy/vm/nginx.staging.conf"
CONF_DST="/etc/nginx/sites-available/nidp-staging"
SSL_DIR="/etc/nginx/ssl"
# Staging reuses the prod wildcard cert (*.niveshcopilot.com covers data.staging.*)
CERT_FILE="$SSL_DIR/data.crt"
KEY_FILE="$SSL_DIR/data.key"

log()  { printf '\033[1;36m[install_nginx_staging]\033[0m %s\n' "$*"; }
fail() { printf '\033[1;31m[install_nginx_staging]\033[0m %s\n' "$*"; exit 1; }

[[ $EUID -eq 0 ]] || fail "must be run as root (use sudo)"
[[ -f "$CONF_SRC" ]] || fail "missing $CONF_SRC — pull latest repo first"
command -v gcloud >/dev/null 2>&1 || fail "gcloud not on PATH"
command -v nginx  >/dev/null 2>&1 || fail "nginx not installed — run install_nginx.sh first"

# ── 1. TLS material — reuse prod wildcard cert (*.niveshcopilot.com) ──
install -d -m 0750 -o root -g root "$SSL_DIR"

if [[ -f "$CERT_FILE" && -f "$KEY_FILE" ]]; then
    log "prod wildcard cert already present at $CERT_FILE — skipping fetch"
else
    log "fetching nidp-tls-cert from Secret Manager (shared wildcard)"
    gcloud secrets versions access latest \
        --secret=nidp-tls-cert --project="$PROJECT" \
        | install -m 0644 -o root -g root /dev/stdin "$CERT_FILE"

    log "fetching nidp-tls-key from Secret Manager (shared wildcard)"
    gcloud secrets versions access latest \
        --secret=nidp-tls-key --project="$PROJECT" \
        | install -m 0600 -o root -g root /dev/stdin "$KEY_FILE"
fi

openssl x509 -in "$CERT_FILE" -noout -subject -dates >/dev/null \
    || fail "cert at $CERT_FILE is not a valid X.509 PEM"

# ── 2. Install site config ─────────────────────────────────────────────
log "installing $CONF_DST"
install -m 0644 -o root -g root "$CONF_SRC" "$CONF_DST"
ln -sf "$CONF_DST" /etc/nginx/sites-enabled/nidp-staging

# ── 3. Validate and reload ─────────────────────────────────────────────
log "running nginx -t"
nginx -t

if systemctl is-active --quiet nginx; then
    log "reloading nginx"
    systemctl reload nginx
else
    log "starting nginx"
    systemctl enable --now nginx
fi

# ── 4. Liveness check ─────────────────────────────────────────────────
sleep 1
if curl -sf -k -H "Host: data.staging.niveshcopilot.com" \
        https://127.0.0.1/health 2>/dev/null | grep -q "ok-staging"; then
    log "✓ staging vhost health OK"
else
    log "⚠ health probe returned unexpected response — nginx may still be warming up"
    log "  Check: curl -sf -k -H 'Host: data.staging.niveshcopilot.com' https://127.0.0.1/health"
fi

log "================================================================"
log "✓ staging nginx vhost installed"
log "  Verify externally (after Cloudflare DNS propagates):"
log "    curl -sf https://data.staging.niveshcopilot.com/health"
log "  Query API staging must be running on port 8091:"
log "    NIDP_QUERY_API_PORT=8091 sudo bash install_query_api_staging.sh"
log "================================================================"
