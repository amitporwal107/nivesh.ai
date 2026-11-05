# OVERRIDE — SPT slice C (paper orders → execution → positions → monitor) not verified on staging

REASON: slice C is not wired into the running app (server.py — router, monitor start()/stop() — belongs to the
integrator per docs/scanner_paper_trading/DESIGN.md §2), and the overnight brief forbids any write to staging (Mongo,
Redis, Postgres, containers). There is therefore no staging API endpoint to call and no staging data to check tonight.

What WAS verified (real output in test_reports/spt_c_pytest.txt): the slice C unit suites (in-memory Mongo fakes; the
paper account and the risk controls run for real on them) and the neighbour suites test_paper*, test_desk_trading*,
test_exit_rules*, in the nivesh/backend:staging image with no network.

UNVERIFIED until the integrator's staging step:
- the routes under the real auth dependency and the real Mongo (unique indexes, partial index on open positions,
  `$expr` / `$max` / `$min` updates);
- the monitor against the live quote cache (day_quote.day_quotes, Redis, the feed snapshot) in a session, and the
  evening pass against desk_trading.fetch_bars;
- the calls between slices: slice B's create_entry_order call (DESIGN §4), B's `check_modification`, B's
  `kill_switch_state` (optional) and B's `pipeline.place_entry_order` (a new contract named here; see the test cases
  file, X14 / X15).

Next step: the integrator wires `routes.spt_paper.router` and `services.spt.paper.monitor.start()/stop()` into server.py,
deploys to staging with SPT_C_ENABLED unset (on by APP_ENV=staging) or 0, and runs the staging checks (an approval-mode
proposal → order → fill in the session → stop / target exit → release, then GET /api/v1/paper/reconcile ok).
