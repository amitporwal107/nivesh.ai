#!/usr/bin/env bash
# SessionStart: keep the verify-before-complete protocol in context every session.
cat >/dev/null   # drain stdin (SessionStart payload); not needed
jq -n --arg m "$(cat <<'EOF'
VERIFY-BEFORE-COMPLETE is ENFORCED in this repo (see .claude/VERIFICATION_PROTOCOL.md):
1) After the API + UI are designed and BEFORE writing implementation, author the test cases.
2) When you edit backend routes/services → run the endpoint tests on STAGING (real output).
   When you edit frontend src → run Playwright (npx playwright test) on the changed screens.
   Ask the user explicitly for any session token / CAS document / secret you need — never fake it.
3) A turn that edited product code cannot end until test_reports/ holds a FRESH report with a
   final line '## Verdict: PASS' covering the changed areas — or a loud test_reports/OVERRIDE_*.md
   with a REASON. Only then is the functionality COMPLETE. Template: test_reports/_TEMPLATE_functionality.md
EOF
)" '{hookSpecificOutput:{hookEventName:"SessionStart", additionalContext:$m}}'
exit 0
