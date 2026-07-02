#!/usr/bin/env bash
# Fires when the agent tries to end its turn. Blocks if code was edited but no
# verification command ran this session. Exit code 2 = block; stderr is fed back.
in=$(cat)
sid=$(jq -r '.session_id' <<<"$in")

# CRITICAL: prevent an infinite loop when we ourselves blocked the stop.
if [ "$(jq -r '.stop_hook_active' <<<"$in")" = "true" ]; then
  exit 0
fi

if [ -f "/tmp/cc-unverified-$sid" ]; then
  echo "You edited code but ran no verification command this session. Run the relevant test/build/curl per docs/BUILD_AND_DEPLOYMENT.md, paste its real output, and confirm the result before finishing. Do not claim 'fixed/working/done' without that evidence." >&2
  exit 2
fi
exit 0
