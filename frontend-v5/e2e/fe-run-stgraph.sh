#!/usr/bin/env bash
# Run e2e/tests/copilot-app-desk-strategy-graphs.spec.ts, the one spec that needs the test-only
# strategy-graphs harness. TradingDesk.tsx registers ?tab=more&view=strategy-graphs only in a build
# made with VITE_STRATEGY_HARNESS=1. A normal build (npm run build, the Dockerfile, the standard
# `vite build` + `vite preview` + pw.copilot-app.config.ts recipe) never sets that flag, so the spec
# fails there by design.
#
# This script makes its own production build WITH the flag into a separate, throwaway output
# directory (never dist/). It serves that build with `vite preview`, runs only this spec against it
# with pw.copilot-app.config.ts, and then stops the server. Every /api call in the spec is
# route-mocked, so it needs no network and no session.
#
# Run from anywhere (paths resolve relative to this script), with frontend-v5/node_modules installed
# and the Playwright browser available:
#
#   bash frontend-v5/e2e/fe-run-stgraph.sh                    # the whole spec
#   bash frontend-v5/e2e/fe-run-stgraph.sh -g "SG-4"          # extra args go to `playwright test`
#
# Environment:
#   STGRAPH_OUT_DIR   build output directory (default: a fresh temp dir, removed on exit)
#   STGRAPH_PORT      preview port (default 5174, the config's baseURL). The port is strict, and the
#                     script checks that the server answering is serving THIS build, so a dev server
#                     already on the port fails the run rather than being tested by mistake.
#
# No Node on the host (the CloudPe staging VM): run it in the Playwright image. Mount a COPY of
# frontend-v5 without node_modules (the container writes test-results/ into it), plus the
# node_modules and browser volumes:
#
#   rsync -a --delete --exclude node_modules frontend-v5/ /tmp/fe-copy/
#   sudo docker run --rm --network none -v /tmp/fe-copy:/app -v wl-fe-node-modules:/app/node_modules \
#     -v pw-browsers-1223:/pw -e PLAYWRIGHT_BROWSERS_PATH=/pw -w /app \
#     mcr.microsoft.com/playwright:v1.47.0-jammy bash e2e/fe-run-stgraph.sh --output /tmp/pw-out
set -euo pipefail

cd "$(dirname "$0")/.."   # frontend-v5/

SPEC=e2e/tests/copilot-app-desk-strategy-graphs.spec.ts
PORT="${STGRAPH_PORT:-5174}"
if [ -n "${STGRAPH_OUT_DIR:-}" ]; then
  OUT="$STGRAPH_OUT_DIR"
  REMOVE_OUT=0
else
  OUT="$(mktemp -d)"
  REMOVE_OUT=1
fi
BUILD_LOG="$(mktemp)"
PREVIEW_LOG="$(mktemp)"
PREVIEW_PID=""

cleanup() {
  if [ -n "$PREVIEW_PID" ]; then
    kill "$PREVIEW_PID" 2>/dev/null || true
  fi
  if [ "$REMOVE_OUT" = 1 ]; then
    rm -rf "$OUT"
  fi
  rm -f "$BUILD_LOG" "$PREVIEW_LOG"
}
trap cleanup EXIT

echo "fe-run-stgraph: building with VITE_STRATEGY_HARNESS=1 into $OUT"
if ! VITE_STRATEGY_HARNESS=1 VITE_USE_MOCK_API=false VITE_BASE=/v5/ \
    npx vite build --outDir "$OUT" --emptyOutDir >"$BUILD_LOG" 2>&1; then
  tail -40 "$BUILD_LOG" >&2
  echo "fe-run-stgraph: vite build FAILED" >&2
  exit 1
fi

# The flag must actually have reached the bundle. Without this check, a build that dropped it would
# show up as 31 confusing spec failures instead of one clear error.
HARNESS_CHUNK="$(find "$OUT/assets" -maxdepth 1 -name 'StrategyGraphsHarness-*.js' | head -n 1)"
if [ -z "$HARNESS_CHUNK" ]; then
  echo "fe-run-stgraph: the build has no StrategyGraphsHarness chunk; VITE_STRATEGY_HARNESS=1 did not apply" >&2
  exit 1
fi
echo "fe-run-stgraph: build ok, harness chunk $(basename "$HARNESS_CHUNK")"

VITE_BASE=/v5/ npx vite preview --outDir "$OUT" --port "$PORT" --strictPort >"$PREVIEW_LOG" 2>&1 &
PREVIEW_PID=$!

# Wait until the server on PORT serves THIS build's harness chunk, byte for byte.
if ! node -e '
  const fs = require("fs");
  const [url, file] = process.argv.slice(1);
  const want = fs.readFileSync(file, "utf8");
  const until = Date.now() + 30000;
  (async function poll() {
    try {
      const res = await fetch(url);
      if (res.ok && (await res.text()) === want) process.exit(0);
    } catch {}
    if (Date.now() > until) process.exit(1);
    setTimeout(poll, 500);
  })();
' "http://localhost:$PORT/v5/assets/$(basename "$HARNESS_CHUNK")" "$HARNESS_CHUNK"; then
  cat "$PREVIEW_LOG" >&2
  echo "fe-run-stgraph: vite preview on :$PORT is not serving the harness build (port taken, or it failed to start)" >&2
  exit 1
fi
echo "fe-run-stgraph: vite preview serving the harness build on :$PORT"

status=0
PW_BASE_URL="http://localhost:$PORT" npx playwright test --config pw.copilot-app.config.ts "$SPEC" "$@" || status=$?
exit "$status"
