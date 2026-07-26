#!/usr/bin/env bash
# deploy_staging.sh — direct deploy of the SURAKSHA prototype to the staging VM.
#
# The prototype is a standalone single-process app; it is NOT part of the Nivesh
# staging docker-compose stack and has no Jenkins/git redeploy pipeline. This script
# is that pipeline: it ships the source, builds an isolated venv on the host, and
# runs the app under its own pid file. Nothing else on the VM is touched — no sudo,
# no nginx change, no docker, no shared-stack restart.
#
#   ./deploy_staging.sh              # deploy + health-check
#   ./deploy_staging.sh --status     # is it up?
#   ./deploy_staging.sh --stop       # stop it and leave the VM as it was
#   ./deploy_staging.sh --logs       # tail the remote log
#
# Overridable: SURAKSHA_SSH_HOST, SURAKSHA_SSH_KEY, SURAKSHA_PORT, SURAKSHA_BIND,
#              SURAKSHA_REMOTE_DIR
set -euo pipefail

SSH_HOST=${SURAKSHA_SSH_HOST:-aporwal107_gmail_com@34.47.250.214}
SSH_KEY=${SURAKSHA_SSH_KEY:-$HOME/.ssh/google_compute_engine}
PORT=${SURAKSHA_PORT:-8010}
BIND=${SURAKSHA_BIND:-127.0.0.1}          # localhost-only by default: the app has no auth
REMOTE_DIR=${SURAKSHA_REMOTE_DIR:-\$HOME/suraksha-staging}
LOCAL_DIR=$(cd "$(dirname "$0")" && pwd)

SSH=(ssh -i "$SSH_KEY" -o StrictHostKeyChecking=no -o ConnectTimeout=20 "$SSH_HOST")

case "${1:-deploy}" in
  --status) exec "${SSH[@]}" "cd $REMOTE_DIR 2>/dev/null && \
      { kill -0 \$(cat run/suraksha.pid 2>/dev/null) 2>/dev/null && echo \"RUNNING pid \$(cat run/suraksha.pid)\" || echo 'NOT RUNNING'; \
        curl -sf http://127.0.0.1:$PORT/api/window || echo ' (no HTTP response)'; }" ;;
  --stop)   exec "${SSH[@]}" "cd $REMOTE_DIR 2>/dev/null && \
      { kill \$(cat run/suraksha.pid) 2>/dev/null && echo 'stopped' || echo 'was not running'; }" ;;
  --logs)   exec "${SSH[@]}" "tail -n 60 $REMOTE_DIR/run/suraksha.log" ;;
esac

echo "==> packaging $LOCAL_DIR"
TAR=$(mktemp /tmp/suraksha-XXXXXX.tar.gz)
trap 'rm -f "$TAR"' EXIT
tar czf "$TAR" -C "$LOCAL_DIR" \
    --exclude=.venv --exclude=node_modules --exclude=test-results \
    --exclude=__pycache__ --exclude='*.db' --exclude='.shot.mjs' .
echo "    $(du -h "$TAR" | cut -f1)"

echo "==> shipping to $SSH_HOST"
scp -i "$SSH_KEY" -o StrictHostKeyChecking=no -q "$TAR" "$SSH_HOST:/tmp/suraksha-deploy.tar.gz"

echo "==> installing and starting on $BIND:$PORT"
"${SSH[@]}" "bash -s" <<REMOTE
set -euo pipefail
DIR=$REMOTE_DIR
mkdir -p "\$DIR/run"

# stop a previous instance before overwriting its code (pid file, never pkill:
# a -f pattern would match this very shell's command line)
if [ -f "\$DIR/run/suraksha.pid" ] && kill -0 "\$(cat "\$DIR/run/suraksha.pid")" 2>/dev/null; then
  kill "\$(cat "\$DIR/run/suraksha.pid")"; sleep 2
  echo "    stopped previous instance"
fi

tar xzf /tmp/suraksha-deploy.tar.gz -C "\$DIR"
rm -f /tmp/suraksha-deploy.tar.gz

if [ ! -x "\$DIR/.venv/bin/python" ]; then
  echo "    creating venv"
  python3 -m venv "\$DIR/.venv"
fi
"\$DIR/.venv/bin/pip" install -q --upgrade pip
"\$DIR/.venv/bin/pip" install -q -r "\$DIR/requirements.txt"
echo "    deps: \$("\$DIR/.venv/bin/pip" list 2>/dev/null | grep -ciE '^(fastapi|uvicorn|cryptography) ') / 3 present"

# fresh demo state: the master key is ephemeral, so old ciphertext is undecryptable
rm -f "\$DIR/suraksha.db"

cd "\$DIR"
SURAKSHA_HOST=$BIND SURAKSHA_PORT=$PORT \
  setsid nohup ./.venv/bin/python app.py > run/suraksha.log 2>&1 &
echo \$! > run/suraksha.pid

for i in \$(seq 1 30); do
  if curl -sf "http://127.0.0.1:$PORT/api/window" >/dev/null 2>&1; then
    echo "    up after \${i}s (pid \$(cat run/suraksha.pid))"; break
  fi
  [ "\$i" = 30 ] && { echo "    FAILED to come up"; tail -20 run/suraksha.log; exit 1; }
  sleep 1
done
echo "--- startup banner ---"; head -6 run/suraksha.log
echo "--- health ---"; curl -s "http://127.0.0.1:$PORT/api/window"; echo
REMOTE

echo "==> deployed. Reach it with a tunnel:"
echo "    ssh -i $SSH_KEY -N -L $PORT:127.0.0.1:$PORT $SSH_HOST"
echo "    then open http://127.0.0.1:$PORT"
