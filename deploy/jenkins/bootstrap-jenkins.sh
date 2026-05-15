#!/usr/bin/env bash
# bootstrap-jenkins.sh — Install Jenkins as a Docker container on nivesh-app-vm.
#
# Jenkins runs on port 8080 (internal, behind nginx).
# GitHub webhooks → http://<VM_IP>:8080/github-webhook/
#
# Usage (run as root on nivesh-app-vm):
#   bash /opt/nivesh/deploy/jenkins/bootstrap-jenkins.sh

set -euo pipefail

JENKINS_HOME="/opt/jenkins/data"
JENKINS_IMAGE="jenkins/jenkins:lts-jdk21"
CONTAINER_NAME="nivesh-jenkins"
HTTP_PORT="8080"
AGENT_PORT="50000"

log()  { printf '\033[1;36m[jenkins]\033[0m %s\n' "$*"; }
ok()   { printf '\033[1;32m[jenkins]\033[0m %s\n' "$*"; }
fail() { printf '\033[1;31m[jenkins]\033[0m %s\n' "$*"; exit 1; }

[[ $EUID -ne 0 ]] && exec sudo "$0" "$@"

# ── 1. Ensure Docker is installed ────────────────────────────────────────────
command -v docker &>/dev/null || fail "Docker is not installed. Install it first."
log "Docker found: $(docker --version)"

# ── 2. Prepare Jenkins home ───────────────────────────────────────────────────
mkdir -p "$JENKINS_HOME"
chown -R 1000:1000 "$JENKINS_HOME"   # Jenkins container runs as uid 1000
log "Jenkins home: $JENKINS_HOME"

# ── 3. Pull image ─────────────────────────────────────────────────────────────
log "Pulling $JENKINS_IMAGE ..."
docker pull "$JENKINS_IMAGE"

# ── 4. Stop existing container if any ────────────────────────────────────────
docker rm -f "$CONTAINER_NAME" 2>/dev/null || true

# ── 5. Start Jenkins ─────────────────────────────────────────────────────────
log "Starting Jenkins container..."
docker run -d \
  --name "$CONTAINER_NAME" \
  --restart unless-stopped \
  -p "127.0.0.1:${HTTP_PORT}:8080" \
  -p "127.0.0.1:${AGENT_PORT}:50000" \
  -v "$JENKINS_HOME:/var/jenkins_home" \
  -v /var/run/docker.sock:/var/run/docker.sock \
  "$JENKINS_IMAGE"

# ── 6. Install Docker CLI inside Jenkins ──────────────────────────────────────
log "Installing Docker CLI inside Jenkins container..."
docker exec -u root "$CONTAINER_NAME" bash -c "
  apt-get update -qq &&
  apt-get install -y --no-install-recommends docker.io rsync &&
  usermod -aG docker jenkins
" 2>&1 | tail -5

# ── 7. Wait for Jenkins to start ──────────────────────────────────────────────
log "Waiting for Jenkins to start (up to 90s)..."
for i in $(seq 1 30); do
  if curl -sf "http://localhost:${HTTP_PORT}/login" &>/dev/null; then
    ok "Jenkins is up."
    break
  fi
  sleep 3
  [[ $i -eq 30 ]] && fail "Jenkins did not start in 90s. Check: docker logs $CONTAINER_NAME"
done

# ── 8. Print initial admin password ──────────────────────────────────────────
INIT_PWD=$(docker exec "$CONTAINER_NAME" \
  cat /var/jenkins_home/secrets/initialAdminPassword 2>/dev/null || echo "not ready yet")

ok ""
ok "✅ Jenkins is running!"
ok ""
ok "   URL:              http://localhost:${HTTP_PORT}"
ok "   Initial password: $INIT_PWD"
ok ""
ok "Next steps:"
ok "  1. Open Jenkins and complete the setup wizard."
ok "  2. Install plugins: Pipeline, GitHub, SSH Agent, Blue Ocean (optional)."
ok "  3. Add GitHub webhook: https://github.com/amitporwal107/nivesh.ai/settings/hooks"
ok "     Payload URL: http://<VM_EXTERNAL_IP>:${HTTP_PORT}/github-webhook/"
ok "     Content type: application/json"
ok "     Events: Push, Pull request"
ok "  4. Configure credentials (Manage Jenkins → Credentials):"
ok "     - SSH key for nivesh-app-vm  (ID: nivesh-app-vm-ssh)"
ok "     - SSH key for nidp-stack-vm  (ID: nidp-stack-vm-ssh)"
ok ""
ok "  To expose Jenkins via nginx (recommended), add to /opt/nivesh/deploy/nginx.conf:"
ok "    location /jenkins/ { proxy_pass http://127.0.0.1:${HTTP_PORT}/jenkins/; }"
