#!/usr/bin/env bash
# Fires after a Bash command. If it was a real verification command, clear the
# "unverified changes" flag. Tuned for Nivesh.ai / NIDP. Keep in sync with the
# "Verify commands" in docs/BUILD_AND_DEPLOYMENT.md and the role checklists.
in=$(cat)
sid=$(jq -r '.session_id' <<<"$in")
cmd=$(jq -r '.tool_input.command' <<<"$in")

# Real verification commands for this project:
#   make verify (12 smoke tests) · yarn build · playwright · py_compile · pytest ·
#   NIDP ./test_locally.sh · post_deploy_migrate · docker build · health curls.
VERIFY_RE='(make verify|yarn build|yarn test|npx vite build|vite build|playwright test|py_compile|pytest|test_locally\.sh|\.claude/hooks/selftest\.sh|post_deploy_migrate|docker (compose )?build|redeploy\.sh|redeploy-staging\.sh|deploy/vm/deploy\.sh|curl .*(niveshcopilot\.com|data\.niveshcopilot\.com|localhost:(8001|8083|8090)).*(health|healthz))'

if echo "$cmd" | grep -Eq "$VERIFY_RE"; then
  rm -f "/tmp/cc-unverified-$sid"
fi
exit 0
