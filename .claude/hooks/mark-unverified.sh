#!/usr/bin/env bash
# Fires after any code edit. Marks this session as having unverified changes.
in=$(cat)
sid=$(jq -r '.session_id' <<<"$in")
touch "/tmp/cc-unverified-$sid"
exit 0
