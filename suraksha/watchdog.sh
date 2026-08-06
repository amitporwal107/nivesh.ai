#!/usr/bin/env bash
# Keeps the SURAKSHA prototype alive. Installed by deploy_staging.sh into cron
# (@reboot + every minute), because the app is started with nohup and would
# otherwise die permanently on a VM reboot — which is exactly what happened on
# 2026-08-06 (staging 502'd for ~11 minutes after a host reboot).
#
# Idempotent and cheap: exits immediately if the app is already answering.
set -uo pipefail
cd "$(dirname "$0")" || exit 1

PIDF=run/suraksha.pid
BIND=$(cat run/bind 2>/dev/null || echo 127.0.0.1)
PORT=$(cat run/port 2>/dev/null || echo 8010)
HEALTH=$([ "$BIND" = "0.0.0.0" ] && echo 127.0.0.1 || echo "$BIND")
log() { echo "$(date -Is) $*" >> run/watchdog.log; }

# Already serving? nothing to do. (Check HTTP, not just the pid — a wedged
# process that holds the port is still an outage.)
if curl -sf -m 5 "http://$HEALTH:$PORT/api/window" >/dev/null 2>&1; then
    exit 0
fi

# A stale/wedged process would hold the port; clear it before restarting.
if [ -f "$PIDF" ] && kill -0 "$(cat "$PIDF")" 2>/dev/null; then
    log "process $(cat "$PIDF") is up but not answering — restarting it"
    kill "$(cat "$PIDF")" 2>/dev/null
    sleep 2
fi
rm -f "$PIDF"

# After a reboot, cron can fire before docker has created the bridge network,
# so the gateway address we bind to may not exist yet. Wait for it rather than
# starting a process that will die on "Cannot assign requested address".
if [ "$BIND" != "0.0.0.0" ] && [ "$BIND" != "127.0.0.1" ]; then
    if ! ip -4 addr show 2>/dev/null | grep -q "inet $BIND/"; then
        log "waiting for $BIND to exist (docker bridge not up yet)"
        exit 0
    fi
fi

SURAKSHA_HOST="$BIND" SURAKSHA_PORT="$PORT" \
    setsid nohup ./.venv/bin/python app.py >> run/suraksha.log 2>&1 &
echo $! > "$PIDF"

for _ in $(seq 1 20); do
    if curl -sf -m 5 "http://$HEALTH:$PORT/api/window" >/dev/null 2>&1; then
        log "started pid $(cat "$PIDF") on $BIND:$PORT"
        exit 0
    fi
    sleep 1
done

log "FAILED to come up on $BIND:$PORT — see run/suraksha.log"
rm -f "$PIDF"
exit 1
