#!/usr/bin/env bash
# Two-hourly disk cleanup for nivesh-app-vm (prod + staging share its 79 GB disk; owner request 2026-09-19).
# Cron calls this script with no arguments: never put a literal percent sign in a cron line (cron turns it into a newline).
#   DRY_RUN=1          report only, delete nothing
#   ARCHIVE_DELETE=1   allow archive deletion — ONLY files older than RETENTION_DAYS that have a verified copy in GCS
# Never touched: Docker volumes, running containers, images in use, /var/lib/containerd, database data (/mnt/nidp-nfs/staging-postgres).
set -uo pipefail
LOG=${LOG:-/var/log/disk-cleanup.log}
DRY_RUN=${DRY_RUN:-0}
ARCHIVE_DELETE=${ARCHIVE_DELETE:-0}
RETENTION_DAYS=${RETENTION_DAYS:-30}
TMP_AGE_MIN=${TMP_AGE_MIN:-1440}                       # temp files untouched for a day
ARCHIVE_DIRS=${ARCHIVE_DIRS:-}                         # set after inspecting the VM (space separated)
GCS_PREFIX=${GCS_PREFIX:-}                             # e.g. gs://nidp-raw-niveshdataintelligence/<layout> — set after inspection
free_mb() { df -Pm / | awk 'NR==2{print $4}'; }
log() { echo "$(date -Is) $*" >> "$LOG"; }
run() { if [ "$DRY_RUN" = 1 ]; then log "DRY_RUN would run: $*"; else "$@" >> "$LOG" 2>&1; fi; }

before=$(free_mb); log "start free=${before}MB dry_run=${DRY_RUN} archive_delete=${ARCHIVE_DELETE}"

# 0. Never prune while a build or deploy is running (pruning mid-deploy made a build cold and filled the disk, 2026-09-19).
if ps -eo args | grep -Eq '[d]ocker(-compose| compose) .*build|[r]edeploy-staging\.sh|[b]uildkitd .*solve'; then
  log "SKIP: a docker build or redeploy is running"; exit 0
fi

# 1. Docker: build cache and dangling images only.
run docker builder prune -af
run docker image prune -f

# 2. Oversized container logs (> 50 MB) truncated in place — the container keeps its file handle.
for f in /var/lib/docker/containers/*/*-json.log; do
  [ -f "$f" ] || continue
  if [ "$(stat -c%s "$f")" -gt 52428800 ]; then if [ "$DRY_RUN" = 1 ]; then log "DRY_RUN would truncate $f ($(stat -c%s "$f") bytes)"; else log "truncate $f ($(stat -c%s "$f") bytes)"; : > "$f"; fi; fi
done

# 3. Temp files not modified for TMP_AGE_MIN minutes (regular files only; sockets, systemd private dirs and live files untouched).
find /tmp /var/tmp -xdev -type f -mmin +"$TMP_AGE_MIN" -not -path '*/systemd-private-*' -not -path '/tmp/claude-*' -print0 2>/dev/null \
  | { if [ "$DRY_RUN" = 1 ]; then tr '\0' '\n' | sed 's/^/DRY_RUN would delete temp: /' >> "$LOG"; else xargs -0 -r rm -f --; fi; }

# 4. Journal and apt caches.
run journalctl --vacuum-size=100M
run apt-get clean

# 5. Archives: only older than RETENTION_DAYS AND present in GCS with the same size. Otherwise report, never delete.
if [ -n "$ARCHIVE_DIRS" ]; then
  for d in $ARCHIVE_DIRS; do
    [ -d "$d" ] || continue
    find "$d" -xdev -type f -mtime +"$RETENTION_DAYS" -print0 2>/dev/null | while IFS= read -r -d '' f; do
      rel=${f#"$d"/}; size=$(stat -c%s "$f")
      remote_size=""
      if [ -n "$GCS_PREFIX" ]; then remote_size=$(gcloud storage ls -l "$GCS_PREFIX/$rel" 2>/dev/null | awk 'NR==1{print $1}'); fi
      if [ "$ARCHIVE_DELETE" = 1 ] && [ "$DRY_RUN" != 1 ] && [ -n "$remote_size" ] && [ "$remote_size" = "$size" ]; then
        rm -f -- "$f" && log "archive deleted (verified in GCS, $size bytes): $f"
      else
        log "archive kept (${remote_size:+gcs_size=$remote_size }local_size=$size; delete requires ARCHIVE_DELETE=1 and a verified GCS copy): $f"
      fi
    done
  done
fi

after=$(free_mb); log "end free=${after}MB reclaimed=$((after - before))MB"
