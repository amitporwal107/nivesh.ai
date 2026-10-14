#!/bin/sh
# Container entrypoint for the public SURAKSHA demo.
#
# v0.1 opens its exam window one minute after start, closes it 30 minutes later,
# and from then on refuses every paper request (REFUSED_LATE). Its pages have no
# control to reopen the window, so a visitor arriving later would be locked out.
#
# This reopens the window on a fixed cycle through the app's own admin endpoint:
# closed for LEAD_MIN (long enough to try the "too early" refusal), then open
# until the next cycle. The app itself is unchanged.
CYCLE_SEC=${SURAKSHA_DEMO_CYCLE_SEC:-1800}
LEAD_MIN=${SURAKSHA_DEMO_LEAD_MIN:-2}

(
  while sleep "$CYCLE_SEC"; do
    python - "$CYCLE_SEC" "$LEAD_MIN" <<'PY' || echo "demo-entrypoint: window roll FAILED" >&2
import json, os, sys, urllib.request

cycle_min, lead_min = int(sys.argv[1]) / 60, float(sys.argv[2])
body = json.dumps({"minutes_from_now": lead_min,
                   "duration_minutes": cycle_min - lead_min}).encode()
req = urllib.request.Request(
    f"http://127.0.0.1:{os.environ.get('SURAKSHA_PORT', '8010')}/api/admin/set_window",
    data=body, headers={"Content-Type": "application/json"}, method="POST")
urllib.request.urlopen(req, timeout=10).read()
print(f"demo-entrypoint: window reopens in {lead_min} min for {cycle_min - lead_min} min", flush=True)
PY
  done
) &

exec python app.py
