#!/usr/bin/env bash
# Stop gate — the enforcement floor for "functionality complete".
# If this session edited gated functionality (see mark-functionality.sh) and there is
# no FRESH passing test report, nor a fresh loud OVERRIDE, block the turn from ending.
# Enforcement model chosen by the user: HARD BLOCK + LOUD OVERRIDE (never a silent skip).
# Exit code 2 = block; stderr is fed back to Claude. We deliberately do NOT bail on
# stop_hook_active: the sanctioned way out is to produce the report OR write a reasoned
# OVERRIDE file (a single Write) — so there is always a clean, loud exit, no dead-loop.
in=$(cat)
sid=$(jq -r '.session_id // "unknown"' <<<"$in")
sid=${sid//[^a-zA-Z0-9_-]/_}
dir="/tmp/cc-fnv-$sid"
root="${CLAUDE_PROJECT_DIR:-$PWD}"
reports="$root/test_reports"

# nothing gated this session -> allow
[ -d "$dir" ] || exit 0
need_be=false; need_fe=false
[ -f "$dir/backend" ]  && need_be=true
[ -f "$dir/frontend" ] && need_fe=true
$need_be || $need_fe || exit 0

# freshness reference = newest area marker (i.e. the last gated edit)
ref=$(ls -t "$dir"/backend "$dir"/frontend 2>/dev/null | head -1)
# candidate is acceptable only if it is not older than the last gated edit
ge_ref() { [ -e "$1" ] && ! [ "$ref" -nt "$1" ]; }

shopt -s nullglob

# 1) LOUD OVERRIDE: test_reports/OVERRIDE_*.md, fresh, with a non-empty REASON:
for f in "$reports"/OVERRIDE_*.md; do
  ge_ref "$f" || continue
  if grep -Eqi '^[[:space:]]*(##[[:space:]]*)?reason:[[:space:]]*[^[:space:]]' "$f"; then
    printf '{"systemMessage":"⚠️ Functionality verification DEFERRED via %s — reason recorded in the file. This is a LOUD, non-silent skip; resolve it before merge."}\n' "$(basename "$f")"
    exit 0
  fi
done

# 2) a FRESH passing report covering every edited area
for f in "$reports"/*.md; do
  case "$(basename "$f")" in _*|OVERRIDE_*) continue ;; esac
  ge_ref "$f" || continue
  grep -qi 'test cases' "$f" || continue
  # verdict line must be exactly PASS (a copied template says BLOCKED and will not match)
  grep -Eqi '^[[:space:]]*(##[[:space:]]*)?verdict:[[:space:]]*pass[[:space:]]*$' "$f" || continue
  if $need_be; then { grep -qi 'staging' "$f" && grep -Eqi 'endpoint|api' "$f"; } || continue; fi
  if $need_fe; then grep -qi 'playwright' "$f" || continue; fi
  exit 0   # satisfied
done

# --- not satisfied: block ---
{
  echo "🔴 FUNCTIONALITY-VERIFICATION GATE (unsatisfied). You edited product code this session:"
  $need_be && echo "   • backend routes/services  → staging API endpoint tests are REQUIRED"
  $need_fe && echo "   • frontend src             → Playwright UI tests are REQUIRED"
  echo ""
  echo "You cannot mark this complete / end the turn until ONE of these is true:"
  echo "  (A) A FRESH report exists under test_reports/ (newer than your last edit) that:"
  echo "      - lists the Test Cases (authored up front),"
  $need_be && echo "      - shows REAL staging API endpoint results (curl/pytest output),"
  $need_fe && echo "      - shows REAL Playwright output (npx playwright test),"
  echo "      - ends with a line exactly: '## Verdict: PASS'."
  echo "      Start from test_reports/_TEMPLATE_functionality.md. Follow .claude/VERIFICATION_PROTOCOL.md."
  echo "  (B) You are genuinely blocked (staging down, or you need a session token / CAS"
  echo "      document / secret from the user). Then: ask the user for it explicitly, AND"
  echo "      write test_reports/OVERRIDE_<slug>.md with a 'REASON:' line. That is the only"
  echo "      sanctioned skip — loud and recorded, never silent."
  echo ""
  echo "Do NOT claim 'done/complete/verified' without the report present in this turn."
} >&2
exit 2
