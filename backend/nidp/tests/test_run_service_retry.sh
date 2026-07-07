#!/usr/bin/env bash
# Tests the bounded-retry logic in deploy/vm/run_service.sh using the
# NIDP_RUN_CMD test seam (a fake command that fails N times then succeeds).
set -uo pipefail

HERE="$(cd "$(dirname "$0")" && pwd)"
SCRIPT="$HERE/../deploy/vm/run_service.sh"
TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT

export NIDP_HOME="$TMP"
mkdir -p "$TMP/repo/backend" "$TMP/logs" "$TMP/run"
export NIDP_RETRY_BACKOFF_S=0     # no real sleeping in tests

fails=0

# ── TC-11: fail twice then succeed, MAX=3 → exit 0 after 3 attempts ──
CNT="$TMP/c1"; echo 0 > "$CNT"
cat > "$TMP/twice.sh" <<EOF
#!/usr/bin/env bash
n=\$(cat "$CNT"); n=\$((n+1)); echo \$n > "$CNT"
[[ \$n -lt 3 ]] && exit 1 || exit 0
EOF
chmod +x "$TMP/twice.sh"
NIDP_MAX_ATTEMPTS=3 NIDP_RUN_CMD="$TMP/twice.sh" bash "$SCRIPT" svc1 >/dev/null 2>&1
rc=$?; n=$(cat "$CNT")
if [[ $rc -eq 0 && $n -eq 3 ]]; then echo "TC-11 PASS (rc=$rc attempts=$n)"; else echo "TC-11 FAIL (rc=$rc attempts=$n)"; fails=$((fails+1)); fi

# ── TC-12: exit code 2 (usage) → not retried, single attempt, exit 2 ──
CNT="$TMP/c2"; echo 0 > "$CNT"
cat > "$TMP/usage.sh" <<EOF
#!/usr/bin/env bash
n=\$(cat "$CNT"); n=\$((n+1)); echo \$n > "$CNT"
exit 2
EOF
chmod +x "$TMP/usage.sh"
NIDP_MAX_ATTEMPTS=3 NIDP_RUN_CMD="$TMP/usage.sh" bash "$SCRIPT" svc2 >/dev/null 2>&1
rc=$?; n=$(cat "$CNT")
if [[ $rc -eq 2 && $n -eq 1 ]]; then echo "TC-12 PASS (rc=$rc attempts=$n)"; else echo "TC-12 FAIL (rc=$rc attempts=$n)"; fails=$((fails+1)); fi

# ── TC-13: MAX=1 (legacy one-shot) → single attempt, failure propagates ──
CNT="$TMP/c3"; echo 0 > "$CNT"
cat > "$TMP/fail.sh" <<EOF
#!/usr/bin/env bash
n=\$(cat "$CNT"); n=\$((n+1)); echo \$n > "$CNT"
exit 1
EOF
chmod +x "$TMP/fail.sh"
NIDP_MAX_ATTEMPTS=1 NIDP_RUN_CMD="$TMP/fail.sh" bash "$SCRIPT" svc3 >/dev/null 2>&1
rc=$?; n=$(cat "$CNT")
if [[ $rc -eq 1 && $n -eq 1 ]]; then echo "TC-13 PASS (rc=$rc attempts=$n)"; else echo "TC-13 FAIL (rc=$rc attempts=$n)"; fails=$((fails+1)); fi

if [[ $fails -eq 0 ]]; then echo "ALL BASH RETRY TESTS PASS"; exit 0; else echo "$fails bash test(s) FAILED"; exit 1; fi
