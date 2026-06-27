#!/usr/bin/env bash
#
# setup-mailpit.sh — local "SMTP server" for the magic-link flow.
#
# You can't send real internet mail from a laptop (port 25 is blocked, no
# sending reputation). For LOCAL dev what you actually want is a catcher:
# Mailpit runs a real SMTP server on :1025 and a web inbox on :8025, so the
# magic-link validation email lands there and you can open it + click the
# "Verify email" link to exercise the real backend endpoint.
#
# What this does (idempotent — safe to re-run):
#   1. Starts a Mailpit container that accepts any SMTP credentials over a
#      plaintext connection (the backend's email_service always does AUTH).
#   2. Attaches it to the backend's Docker network so the backend container
#      can reach it by the hostname `mailpit`.
#   3. Writes SMTP_* + PUBLIC_APP_URL into .env.local.
#   4. Restarts the backend so it picks up the new env.
#
# Usage:
#   ./scripts/local/setup-mailpit.sh
#   open http://localhost:8025
#
set -euo pipefail
cd "$(git rev-parse --show-toplevel 2>/dev/null || echo .)"

ENV_FILE="${ENV_FILE:-.env.local}"
BACKEND_CONTAINER="${BACKEND_CONTAINER:-nivesh-backend}"
MAILPIT_CONTAINER="mailpit"

command -v docker >/dev/null 2>&1 || { echo "ERROR: docker is required."; exit 1; }

# 1) Start Mailpit (idempotent). AUTH_ACCEPT_ANY + AUTH_ALLOW_INSECURE let the
#    backend's server.login() succeed without TLS, which is fine for local dev.
if [ -n "$(docker ps -q -f "name=^${MAILPIT_CONTAINER}$")" ]; then
  echo "• Mailpit already running."
else
  docker rm -f "${MAILPIT_CONTAINER}" >/dev/null 2>&1 || true
  echo "• Starting Mailpit…"
  docker run -d --name "${MAILPIT_CONTAINER}" --restart unless-stopped \
    -p 1025:1025 -p 8025:8025 \
    -e MP_SMTP_AUTH_ACCEPT_ANY=1 \
    -e MP_SMTP_AUTH_ALLOW_INSECURE=1 \
    axllent/mailpit:latest >/dev/null
fi

# 2) Reach Mailpit from the backend. If the backend runs in Docker, connect
#    Mailpit to its network and address it as `mailpit`; otherwise (backend on
#    the host) use localhost.
SMTP_HOST_VALUE="localhost"
if docker inspect "${BACKEND_CONTAINER}" >/dev/null 2>&1; then
  NET="$(docker inspect -f '{{range $k,$v := .NetworkSettings.Networks}}{{$k}} {{end}}' "${BACKEND_CONTAINER}" | awk '{print $1}')"
  if [ -n "${NET}" ]; then
    docker network connect "${NET}" "${MAILPIT_CONTAINER}" >/dev/null 2>&1 || true
    echo "• Connected Mailpit to backend network: ${NET}"
  fi
  SMTP_HOST_VALUE="mailpit"
else
  echo "• NOTE: container '${BACKEND_CONTAINER}' not found — assuming the backend runs on the host."
fi

# 3) Write SMTP_* + PUBLIC_APP_URL into .env.local (strip old values, re-append).
if [ ! -f "${ENV_FILE}" ]; then
  echo "ERROR: ${ENV_FILE} not found. Run 'make env' first to create it."
  exit 1
fi
tmp="$(mktemp)"
grep -vE '^(SMTP_HOST|SMTP_PORT|SMTP_USERNAME|SMTP_PASSWORD|SMTP_FROM|SMTP_STARTTLS|PUBLIC_APP_URL)=' "${ENV_FILE}" > "${tmp}" || true
cat >> "${tmp}" <<EOF

# ── Local magic-link email (Mailpit dev SMTP) — added by setup-mailpit.sh ──
SMTP_HOST=${SMTP_HOST_VALUE}
SMTP_PORT=1025
SMTP_USERNAME=dev
SMTP_PASSWORD=dev
SMTP_FROM=Nivesh (local) <no-reply@nivesh.local>
SMTP_STARTTLS=false
PUBLIC_APP_URL=http://localhost:8001
EOF
mv "${tmp}" "${ENV_FILE}"
echo "• Updated ${ENV_FILE} with SMTP_* settings."

# 4) Restart the backend so dotenv reloads (Docker path only).
if docker inspect "${BACKEND_CONTAINER}" >/dev/null 2>&1; then
  docker restart "${BACKEND_CONTAINER}" >/dev/null
  echo "• Restarted ${BACKEND_CONTAINER}."
fi

cat <<'EOF'

✅ Local SMTP is ready.
   • Web inbox : http://localhost:8025
   • SMTP      : localhost:1025 (host) · mailpit:1025 (compose network)

Test the magic-link flow:
   curl -i -X POST http://localhost:8001/api/auth/magic-link \
        -H 'Content-Type: application/json' \
        -d '{"email":"tester@gmail.com"}'

Then open http://localhost:8025, open the email, and click "Verify email →".
That hits the real backend validate endpoint and adds the address to
db.whitelisted_users. (The final redirect to /login will 404 on :8001 because
the SPA isn't served there in local dev — that's cosmetic; the whitelist row
is the real result. Verify with:  curl localhost:8001/... or check Mongo.)
EOF
