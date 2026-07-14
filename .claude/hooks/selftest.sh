#!/usr/bin/env bash
# Recognized "verify command" for changes under .claude/hooks/ (see clear-if-verified.sh).
# Exercises the functionality-verification hooks against synthetic payloads and prints
# PASS/FAIL. Exits non-zero on any failure. Uses a throwaway session id + scratch project
# dir, and cleans up — it never touches real session markers or the real test_reports/.
set -u
cd "$(dirname "$0")/../.." || exit 2
HOOKS=".claude/hooks"
fail=0
chk() { if [ "$2" = "$3" ]; then echo "  ok  : $1"; else echo "  FAIL: $1 (got '$2' want '$3')"; fail=1; fi; }

SID="SELFTEST_$$"
FDIR="/tmp/cc-fnv-$SID"
PROJ="/tmp/cc-selftest-$$"
rm -rf "$FDIR" "$PROJ"; mkdir -p "$PROJ/test_reports"

edit() { echo "{\"session_id\":\"$SID\",\"tool_name\":\"Edit\",\"tool_input\":{\"file_path\":\"$1\"}}" | "$HOOKS/mark-functionality.sh" >/dev/null 2>&1; }
gate() { echo "{\"session_id\":\"$SID\",\"stop_hook_active\":false}" | CLAUDE_PROJECT_DIR="$PROJ" "$HOOKS/require-functionality-verification.sh" >/dev/null 2>&1; echo $?; }

echo "[classifier]"
edit "/app/frontend-v5/src/pages/X.tsx"
chk "frontend edit arms marker"      "$([ -f "$FDIR/frontend" ] && echo y || echo n)" "y"
edit "/app/backend/routes/x.py"
chk "backend edit arms marker"       "$([ -f "$FDIR/backend" ]  && echo y || echo n)" "y"
edit "/app/docs/x.md"; edit "/app/backend/tests/test_x.py"; edit "/app/backend/nidp/migrations/1.sql"
chk "excluded edits add no markers"  "$(ls "$FDIR" 2>/dev/null | grep -Ec 'backend|frontend')" "2"

echo "[stop gate]"
chk "empty reports -> block"         "$(gate)" "2"
cat > "$PROJ/test_reports/r.md" <<'R'
## Test Cases
## API / Endpoint Tests (staging) endpoint
## Playwright
## Verdict: PASS
R
chk "fresh PASS report -> allow"     "$(gate)" "0"
printf '## Test Cases\n## Verdict: BLOCKED\n' > "$PROJ/test_reports/r.md"
chk "non-PASS verdict -> block"      "$(gate)" "2"
rm -f "$PROJ"/test_reports/*.md
printf 'REASON: blocked awaiting user session token\n' > "$PROJ/test_reports/OVERRIDE_x.md"
chk "override with reason -> allow"  "$(gate)" "0"

echo "[injector]"
echo '{}' | "$HOOKS/inject-verification-protocol.sh" | jq -e '.hookSpecificOutput.additionalContext' >/dev/null 2>&1
chk "SessionStart emits context"     "$?" "0"

rm -rf "$FDIR" "$PROJ"
if [ "$fail" = 0 ]; then echo "SELFTEST: PASS"; exit 0; else echo "SELFTEST: FAIL"; exit 1; fi
