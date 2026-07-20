# OVERRIDE — NSE/BSE identity bridge: real HTTP endpoint test not captured

REASON: The functionality-verification gate requires REAL staging API endpoint
output (curl/pytest) for a backend route change. Producing that for
`/documents/search` requires exercising the running HTTP service, and I am blocked
on a user decision about HOW, because both routes touch something I was told not to:

  1. The LIVE DaaS (`nidp-daas-api.service`) runs from `/opt/nidp/repo` — the PROD
     checkout, under an explicit do-not-touch instruction. I will not restart it
     with this code.
  2. The clean alternative — a TRANSIENT DaaS instance from `/opt/nidp/dev-repo` on a
     spare port against the staging DB (no prod touch, killed after) — I started, and
     it was interrupted/declined by the user.

So the HTTP-level test is not silently skipped; it is blocked on which path is
authorized. ASKING the user explicitly (see the turn's question).

## What IS verified on staging (real output, in nse_bse_identity_bridge.md)
- The route's own `_HYBRID_SQL` + `_resolve_scrips()` run against the real staging DB:
  `_resolve_scrips('SSWL') -> ['513262']`, and the BSE-scrip concall transcript that
  the ticker-only filter missed is now returned.
- Latency blocker fixed: 8.9s -> 39ms (functional index + ANALYZE, migration 129),
  confirmed by EXPLAIN (7s seq-scan -> 0.35ms index scan).
- Normalizer collision-safe across 1,460 split identities (0 real collisions).

This is one layer below HTTP (SQL + auth/routing untested). NOT deployed to any live
service. Do NOT read the change as live or complete.

## Unblock: user chooses one of
  (a) I run a transient dev-repo DaaS on a spare port (staging DB) and curl it — no
      prod touch; or
  (b) authorize deploying to prod `/opt/nidp/repo` and curl the live endpoint; or
  (c) accept the SQL-level verification as sufficient for now.
