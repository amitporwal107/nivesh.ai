#!/usr/bin/env bash
# NIDP disk hygiene — prune stale temp files + old raw feed archives so the
# nidp-stack-vm root disk (49G) doesn't fill up. Runs daily as root via
# /etc/cron.d/nidp-disk-cleanup. Retention window: 7 days. All targets are
# regenerable or already-ingested — nothing live is touched.
set -uo pipefail

RETAIN_DAYS=7
LOG=/opt/nidp/logs/disk-cleanup.log
mkdir -p "$(dirname "$LOG")"
ts()   { date -Iseconds; }
freef() { df -h / | awk 'NR==2 {print $4" free ("$5" used)"}'; }

{
  echo "$(ts) === disk-cleanup start — $(freef) ==="

  # 1. Stale /tmp entries — anything untouched for RETAIN_DAYS (old worktrees,
  #    scratchpads, playwright/esbuild temp from finished code-server sessions).
  find /tmp -mindepth 1 -maxdepth 1 -mtime +"$RETAIN_DAYS" -exec rm -rf {} + 2>/dev/null || true

  # 2. Old raw feed-archive date folders: archive/<feed>/<YYYY-MM-DD>. The data
  #    is already ingested into the DB; keep the last RETAIN_DAYS for replay.
  if [ -d /opt/nidp/archive ]; then
    find /opt/nidp/archive -mindepth 2 -maxdepth 2 -type d -mtime +"$RETAIN_DAYS" \
      -exec rm -rf {} + 2>/dev/null || true
  fi

  # 3. Cap the systemd journal and drop dangling docker images (both regenerable).
  journalctl --vacuum-size=100M >/dev/null 2>&1 || true
  docker image prune -f       >/dev/null 2>&1 || true

  # 4. pip download cache (re-created on next install).
  rm -rf /root/.cache/pip /opt/nidp/.cache/pip 2>/dev/null || true

  echo "$(ts) === disk-cleanup done  — $(freef) ==="
} >> "$LOG" 2>&1
