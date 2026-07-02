#!/usr/bin/env bash
# Stop hook — runs AFTER require-functionality-verification.sh.
#
# When a session's functionality gate has PASSED (a fresh test_reports report
# ending in a line exactly '## Verdict: PASS'), auto-append a DRAFT release note
# to the deployed Release Management store via the secret-guarded ingest endpoint
# (POST /api/release-docs/ingest-draft). The draft then shows in Settings →
# Release Management for an admin to review and finalise.
#
# CONTRACT: this hook NEVER blocks the turn — it always exits 0. It is a silent
# no-op when: the ingest secret is unset, there is no fresh PASS report, or the
# newest PASS report was already ingested (deduped). Failures are logged, not raised.
set -uo pipefail

ROOT="${CLAUDE_PROJECT_DIR:-/app}"
LOG="$ROOT/.claude/.release-draft.log"
STATE="$ROOT/.claude/.release-draft.state"   # last-ingested "path:mtime"
log(){ echo "[$(date -u +%FT%TZ)] $*" >>"$LOG" 2>/dev/null || true; }

# Secret: env first, then an untracked local file. No secret → feature off.
SECRET="${RELEASE_INGEST_SECRET:-}"
if [ -z "$SECRET" ] && [ -f "$ROOT/.claude/.release-ingest-secret" ]; then
  SECRET="$(head -n1 "$ROOT/.claude/.release-ingest-secret" 2>/dev/null)"
fi
[ -z "$SECRET" ] && { log "no ingest secret configured — skip"; exit 0; }

API="${RELEASE_INGEST_URL:-https://staging.niveshcopilot.com}"
reports="$ROOT/test_reports"
[ -d "$reports" ] || { log "no test_reports/ — skip"; exit 0; }

# Newest real report (skip _TEMPLATE / OVERRIDE) that ends in '## Verdict: PASS'.
newest=""; newest_m=0
for f in "$reports"/*.md; do
  [ -f "$f" ] || continue
  case "$(basename "$f")" in _*|OVERRIDE_*) continue;; esac
  tail -n 40 "$f" | grep -q '^## Verdict: PASS' || continue
  m=$(stat -c %Y "$f" 2>/dev/null || echo 0)
  if [ "$m" -gt "$newest_m" ]; then newest_m=$m; newest="$f"; fi
done
[ -z "$newest" ] && { log "no fresh PASS report — skip"; exit 0; }

key="$newest:$newest_m"
if [ -f "$STATE" ] && [ "$(cat "$STATE" 2>/dev/null)" = "$key" ]; then
  log "already ingested $key — skip"; exit 0
fi

branch="$(git -C "$ROOT" rev-parse --abbrev-ref HEAD 2>/dev/null || echo unknown)"
commit="$(git -C "$ROOT" rev-parse --short HEAD 2>/dev/null || echo '')"

RELEASE_INGEST_API="$API" RD_SECRET="$SECRET" RD_REPORT="$newest" \
RD_BRANCH="$branch" RD_COMMIT="$commit" python3 - <<'PY' >>"$LOG" 2>&1
import json, os, re, ssl, urllib.request, datetime
report = os.environ["RD_REPORT"]
txt = open(report, encoding="utf-8", errors="replace").read()
title = (re.search(r'^#\s+(.+)$', txt, re.M) or [None, os.path.basename(report)])[1]
m = re.search(r'##\s*Summary\s*\n(.+?)(?:\n##\s|\Z)', txt, re.S)
summary = (m.group(1).strip() if m else "")
cm = re.search(r'Changed areas:\**\s*(.+)', txt)
changed = cm.group(1).strip()[:300] if cm else ""
body = (summary[:4000] or f"Verified change: {title}")
payload = {
    "summary": f"**{title}**\n\n{body}",
    "branch": os.environ.get("RD_BRANCH", "unknown"),
    "commit": os.environ.get("RD_COMMIT", ""),
    "changed_areas": changed,
    "verified_at": datetime.datetime.utcnow().replace(microsecond=0).isoformat() + "Z",
}
url = os.environ["RELEASE_INGEST_API"].rstrip("/") + "/api/release-docs/ingest-draft"
req = urllib.request.Request(
    url, data=json.dumps(payload).encode(),
    headers={"Content-Type": "application/json", "X-Release-Ingest-Secret": os.environ["RD_SECRET"]},
    method="POST",
)
try:
    with urllib.request.urlopen(req, timeout=20, context=ssl.create_default_context()) as r:
        print("ingest OK", r.status, r.read(300).decode(errors="replace"))
except Exception as e:
    print("ingest FAILED (non-blocking):", repr(e))
PY

echo "$key" >"$STATE" 2>/dev/null || true
log "processed $key (branch=$branch commit=$commit)"
exit 0
