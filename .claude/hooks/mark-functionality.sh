#!/usr/bin/env bash
# PostToolUse (Edit|Write|MultiEdit).
# Classifies the edited file into a "functionality area" and records a per-session
# marker. These markers arm the functionality-verification Stop gate
# (require-functionality-verification.sh). Area-based scope (confirmed with the user):
#   backend routes / services / *routers  -> staging API endpoint tests required
#   frontend-v5/src or frontend/src       -> Playwright UI tests required
# Docs, migrations, seeds, config, tests, e2e, mocks, reports, images, .claude/ are
# NOT treated as gated functionality. Keep in sync with .claude/VERIFICATION_PROTOCOL.md.
in=$(cat)
sid=$(jq -r '.session_id // "unknown"' <<<"$in")
sid=${sid//[^a-zA-Z0-9_-]/_}

# file_path for Edit/Write, or the first edit's file_path for MultiEdit
fp=$(jq -r '.tool_input.file_path // (.tool_input.edits[0].file_path) // ""' <<<"$in")
[ -z "$fp" ] && exit 0

dir="/tmp/cc-fnv-$sid"

# --- exclusions first: never gated as functionality ---
case "$fp" in
  */test_reports/*|*.md|*/docs/*|*/.claude/*) exit 0 ;;
  *.sql|*/migrations/*|*/seeds/*) exit 0 ;;
  *.test.*|*.spec.*|*/e2e/*|*/tests/*|*/__tests__/*|*/mock/*|*/mocks/*) exit 0 ;;
  *.json|*.yml|*.yaml|*.lock|*.png|*.jpg|*.jpeg|*.svg|*.ico|*.css|*.scss) exit 0 ;;
esac

marked=""
# --- backend API surface ---
case "$fp" in
  */backend/routes/*|*/backend/services/*|*/backend/*routers/*)
    mkdir -p "$dir"; touch "$dir/backend"; marked="backend" ;;
esac
# --- frontend product code ---
case "$fp" in
  */frontend-v5/src/*|*/frontend/src/*)
    mkdir -p "$dir"; touch "$dir/frontend"; marked="${marked:+$marked+}frontend" ;;
esac

[ -z "$marked" ] && exit 0

# One-time-per-session nudge: enforce test-cases-up-front + name the gate.
if [ ! -f "$dir/.nudged" ]; then
  touch "$dir/.nudged"
  jq -n --arg m "Functionality-verification gate ARMED (edited: $marked). Per .claude/VERIFICATION_PROTOCOL.md: (1) test cases must be authored BEFORE implementation; (2) this turn cannot end until test_reports/ has a FRESH report with 'VERDICT: PASS' covering the changed areas (backend->staging API tests, frontend->Playwright), or a loud test_reports/OVERRIDE_*.md with a REASON. Ask the user explicitly for any session token / CAS document / secret you need; never fabricate it. Template: test_reports/_TEMPLATE_functionality.md" \
    '{hookSpecificOutput:{hookEventName:"PostToolUse", additionalContext:$m}}'
fi
exit 0
