#!/usr/bin/env bash
#
# setup-mailpit-vm.sh — shared Mailpit email catcher for a VM where the
# backend runs in Docker on the SAME host.
#
# Run this ON the VM. It stands up Mailpit as a Docker service that CATCHES the
# app's magic-link emails into a web inbox. Mailpit does NOT deliver mail to
# real inboxes — it's a test sink, so real users never receive the mail. Use it
# to exercise the flow yourself (open the inbox, click the validation link).
#
# Because the backend is a container on this host, Mailpit joins the backend's
# Docker network and the app reaches it as `mailpit:1025`. Nothing SMTP is
# exposed to the internet; only the web UI is published on 127.0.0.1 for
# SSH-tunnel access.
#
# ┌─ SECURITY ────────────────────────────────────────────────────────────────┐
# │ Caught emails contain magic-link VALIDATION TOKENS — anyone who reads the  │
# │ inbox can self-whitelist. So: SMTP requires auth, the UI requires a        │
# │ password, and the UI is bound to 127.0.0.1 only (never public).            │
# └────────────────────────────────────────────────────────────────────────────┘
#
# Usage (on the VM):
#   export SMTP_PASS='<smtp-password>'             # required (app authenticates with this)
#   export MAILPIT_UI_PASS='<ui-password>'         # required (web inbox login)
#   # optional: BACKEND_CONTAINER=<name>  SMTP_USER=staging  MAILPIT_UI_USER=admin
#   sudo -E ./setup-mailpit-vm.sh
#
# Read the inbox from your laptop:
#   gcloud compute ssh nivesh-app-vm --zone <zone> -- -L 8025:localhost:8025
#   open http://localhost:8025
#
set -euo pipefail

SMTP_USER="${SMTP_USER:-staging}"
SMTP_PASS="${SMTP_PASS:?Set SMTP_PASS (the password the app uses to authenticate to Mailpit)}"
MAILPIT_UI_USER="${MAILPIT_UI_USER:-admin}"
MAILPIT_UI_PASS="${MAILPIT_UI_PASS:?Set MAILPIT_UI_PASS (web inbox login password)}"
MAILPIT_CONTAINER="mailpit"
DATA_DIR="${DATA_DIR:-/var/lib/mailpit}"

command -v docker >/dev/null 2>&1 || { echo "• Installing Docker…"; curl -fsSL https://get.docker.com | sh; }

# 1) Find the backend container so we can share its Docker network.
if [ -z "${BACKEND_CONTAINER:-}" ]; then
  BACKEND_CONTAINER="$(docker ps --format '{{.Names}}' | grep -iE 'backend' | head -1 || true)"
fi
if [ -z "${BACKEND_CONTAINER}" ] || ! docker inspect "${BACKEND_CONTAINER}" >/dev/null 2>&1; then
  echo "ERROR: could not find the backend container."
  echo "       Set it explicitly, e.g.:  BACKEND_CONTAINER=nivesh-backend sudo -E ./setup-mailpit-vm.sh"
  echo "       Running containers:"; docker ps --format '   - {{.Names}}'
  exit 1
fi

# Pick the first user-defined network the backend is on (container-name DNS
# resolution requires a user-defined network — compose networks qualify).
NET="$(docker inspect -f '{{range $k,$v := .NetworkSettings.Networks}}{{$k}} {{end}}' "${BACKEND_CONTAINER}" | awk '{print $1}')"
if [ -z "${NET}" ] || [ "${NET}" = "bridge" ]; then
  echo "ERROR: backend container '${BACKEND_CONTAINER}' is on network '${NET:-none}'."
  echo "       It must be on a user-defined (compose) network for 'mailpit' DNS to resolve."
  exit 1
fi
echo "• Backend container : ${BACKEND_CONTAINER}"
echo "• Shared network    : ${NET}"

# 2) Persist caught mail across restarts.
mkdir -p "${DATA_DIR}"

# 3) (Re)create Mailpit on the backend's network. SMTP (1025) is reachable ONLY
#    inside that Docker network — not published to the host or internet. The web
#    UI is published on 127.0.0.1:8025 (SSH-tunnel to reach it). ALLOW_INSECURE
#    permits AUTH over the plaintext in-network link (app sets SMTP_STARTTLS=false).
docker rm -f "${MAILPIT_CONTAINER}" >/dev/null 2>&1 || true
echo "• Starting Mailpit…"
docker run -d --name "${MAILPIT_CONTAINER}" --restart always \
  --network "${NET}" \
  -p 127.0.0.1:8025:8025 \
  -v "${DATA_DIR}:/data" \
  -e MP_DATABASE=/data/mailpit.db \
  -e MP_SMTP_AUTH="${SMTP_USER}:${SMTP_PASS}" \
  -e MP_SMTP_AUTH_ALLOW_INSECURE=1 \
  -e MP_UI_AUTH="${MAILPIT_UI_USER}:${MAILPIT_UI_PASS}" \
  axllent/mailpit:latest >/dev/null

cat <<EOF

✅ Mailpit is running and attached to '${NET}'. The backend reaches it at mailpit:1025.

── Set these in Admin → Secrets (takes effect live, no restart) ───────────────
   SMTP_HOST      = mailpit
   SMTP_PORT      = 1025
   SMTP_USERNAME  = ${SMTP_USER}
   SMTP_PASSWORD  = <the SMTP_PASS you set>
   SMTP_FROM      = Nivesh <no-reply@niveshcopilot.com>
   SMTP_STARTTLS  = false
   PUBLIC_APP_URL = https://niveshcopilot.com

── Read the inbox (UI is NOT public — tunnel to it) ───────────────────────────
   gcloud compute ssh nivesh-app-vm --zone <zone> -- -L 8025:localhost:8025
   open http://localhost:8025        (login: ${MAILPIT_UI_USER} / <MAILPIT_UI_PASS>)

── Reminder ───────────────────────────────────────────────────────────────────
   This CATCHES mail; real users do NOT receive it. Use it to test the flow
   yourself. Switch SMTP_* to a real relay (Brevo/SES/SendGrid) before real
   users depend on magic-link delivery.
EOF
