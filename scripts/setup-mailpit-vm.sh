#!/usr/bin/env bash
#
# setup-mailpit-vm.sh — shared Mailpit email catcher for a staging/test VM.
#
# Run this ON the GCP VM (Debian/Ubuntu). It stands up Mailpit as a Docker
# service that CATCHES the app's magic-link emails into a web inbox. Mailpit
# does NOT deliver mail to real inboxes — it's a test sink, so real users never
# receive staging mail.
#
# ┌─ SECURITY (read this) ────────────────────────────────────────────────────┐
# │ Caught emails contain magic-link VALIDATION TOKENS. Anyone who can read    │
# │ the inbox can self-whitelist. Therefore this script:                       │
# │   1. Requires real SMTP AUTH creds (no "accept any") on port 1025.         │
# │   2. Password-protects the web UI.                                         │
# │   3. Binds the web UI to 127.0.0.1 ONLY — you reach it via SSH tunnel,     │
# │      it is never exposed to the internet.                                  │
# │   4. Prints the GCP firewall rule to restrict :1025 to your app's egress.  │
# └────────────────────────────────────────────────────────────────────────────┘
#
# Usage (on the VM):
#   export SMTP_PASS='<strong-smtp-password>'      # required
#   export MAILPIT_UI_PASS='<strong-ui-password>'  # required
#   # optional overrides: SMTP_USER (default 'staging'), MAILPIT_UI_USER (default 'admin')
#   sudo -E ./setup-mailpit-vm.sh
#
# Reach the web inbox from your laptop:
#   gcloud compute ssh <vm-name> --zone <zone> -- -L 8025:localhost:8025
#   # then open http://localhost:8025
#
set -euo pipefail

SMTP_USER="${SMTP_USER:-staging}"
SMTP_PASS="${SMTP_PASS:?Set SMTP_PASS to a strong password the app will use to authenticate}"
MAILPIT_UI_USER="${MAILPIT_UI_USER:-admin}"
MAILPIT_UI_PASS="${MAILPIT_UI_PASS:?Set MAILPIT_UI_PASS to a strong password for the web inbox}"
MAILPIT_CONTAINER="mailpit"
DATA_DIR="${DATA_DIR:-/var/lib/mailpit}"

# 1) Ensure Docker is present (idempotent).
if ! command -v docker >/dev/null 2>&1; then
  echo "• Installing Docker…"
  curl -fsSL https://get.docker.com | sh
fi

# 2) Persist caught mail across restarts.
mkdir -p "${DATA_DIR}"

# 3) (Re)create the Mailpit container.
#    - SMTP on 0.0.0.0:1025 with REQUIRED auth (lock down with the firewall rule
#      printed below). ALLOW_INSECURE permits AUTH over the plaintext link the
#      app uses (SMTP_STARTTLS=false) — fine because access is firewalled.
#    - Web UI bound to 127.0.0.1:8025 only → not internet-reachable; SSH-tunnel
#      to it. Basic-auth protected as defense in depth.
docker rm -f "${MAILPIT_CONTAINER}" >/dev/null 2>&1 || true
echo "• Starting Mailpit…"
docker run -d --name "${MAILPIT_CONTAINER}" --restart always \
  -p 0.0.0.0:1025:1025 \
  -p 127.0.0.1:8025:8025 \
  -v "${DATA_DIR}:/data" \
  -e MP_DATABASE=/data/mailpit.db \
  -e MP_SMTP_AUTH="${SMTP_USER}:${SMTP_PASS}" \
  -e MP_SMTP_AUTH_ALLOW_INSECURE=1 \
  -e MP_UI_AUTH="${MAILPIT_UI_USER}:${MAILPIT_UI_PASS}" \
  axllent/mailpit:latest >/dev/null

# 4) Show the app-side config + the firewall rule to apply.
HOST_HINT="$(hostname -f 2>/dev/null || hostname)"
cat <<EOF

✅ Mailpit is running on this VM.

── Point the staging app at it (Admin → Secrets, or staging env) ──────────────
   SMTP_HOST      = <this VM's hostname or internal IP>   # e.g. ${HOST_HINT}
   SMTP_PORT      = 1025
   SMTP_USERNAME  = ${SMTP_USER}
   SMTP_PASSWORD  = <the SMTP_PASS you set>
   SMTP_FROM      = Nivesh (staging) <no-reply@nivesh.local>
   SMTP_STARTTLS  = false
   PUBLIC_APP_URL = https://staging.niveshcopilot.com      # so links are absolute

── Read the inbox (from your laptop — UI is NOT public) ───────────────────────
   gcloud compute ssh <vm-name> --zone <zone> -- -L 8025:localhost:8025
   open http://localhost:8025      (login: ${MAILPIT_UI_USER} / <MAILPIT_UI_PASS>)

── Lock down SMTP :1025 to ONLY your app's egress IP (run locally w/ gcloud) ──
   gcloud compute firewall-rules create allow-mailpit-smtp \\
     --direction=INGRESS --action=ALLOW --rules=tcp:1025 \\
     --source-ranges=<APP_EGRESS_CIDR> \\
     --target-tags=mailpit
   # …and add the network tag 'mailpit' to this VM. Do NOT open :1025 to
   # 0.0.0.0/0, and never publish :8025 publicly.
EOF
