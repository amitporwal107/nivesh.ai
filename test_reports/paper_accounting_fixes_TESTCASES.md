# Paper-trading accounting fixes: test cases (authored before implementation)

Branch `fix/paper-accounting` (from origin/dev 19263e08). Five defects, each verified by reading origin/dev:

1. `desk_strategy_trades.close_strategy_trade` never released the capital an F&O structure reserved (`paper_reserved_rs`), so every
   closed structure kept its capital blocked and its P&L never reached cash.
2. F&O exit rules ran only when someone loaded `GET /api/desk/paper-trades`; the evening job (`scripts/check_desk_alerts.py`) skipped
   strategy trades.
3. `paper_account.reserve` read the balance, then incremented: two concurrent requests could both see the same free cash and overdraw.
4. Two tests in `tests/test_desk_paper_sim.py` asserted the gap-fill rule that cace6500 (2026-10-22) replaced; the module docstring of
   `services/desk_trading.py` still described it.
5. `scripts/record_fno_forward.py` has no schedule in the repo, so the forward test never records anything.

MOCK: every test runs on the in-memory Mongo fakes and the fake data platform of `tests/test_desk_trading.py` (FIX* / FIXU rows are made up).

| ID | Type | Case | Expected |
|----|------|------|----------|
| PA-1 | pytest (route + service) | Open the worked bull call spread (1 lot of 250, 1300/1360 calls, exposure = 60 × 250 = ₹15,000), close it by hand at the 14 Oct marks | account blocked returns to 0; cash = 1,000,000 + the trade's stored `net_pnl_rs` (gross −1,250, costs 91.875, net ≈ −1,341.88); one `release` ledger row with amount 15,000 |
| PA-2 | pytest (route) | Same structure, the list read fires the target exit (15 Oct marks, an automatic close through `apply_exits`) | blocked 0; cash = 1,000,000 + net ≈ +6,141.88 (gross 6,250 − costs 108.125) |
| PA-3 | pytest (service) | `close_strategy_trade` called twice with the same open copy (a manual close racing an automatic one) | first call closes (True), second returns False; exactly ONE release ledger row; blocked and cash moved once |
| PA-4 | pytest (service) | A strategy trade with no `paper_reserved_rs` (opened before the account existed) closed with a net P&L | nothing unblocked; cash moves by the net P&L only (the cash-close rule) |
| PA-5 | pytest (service) | Closing a structure whose net P&L is unknown (a leg has no mark) | the reservation is returned; cash unchanged (nothing assumed) |
| PA-6 | pytest (account) | Two reserves of ₹600,000 run concurrently on a ₹1,000,000 account, with a fake that yields between every await (both read before either writes) | exactly one succeeds, the other raises InsufficientFunds; blocked = 600,000, never 1,200,000; one `reserve` ledger row. The same test against the old read-then-increment code overdraws (shown once, then removed) |
| PA-7 | pytest (account) | The refusal carries real numbers: reserve 600,000 after 600,000 is blocked | needed 600,000, available 400,000, cash 1,000,000, blocked 600,000 (re-read after the conditional update missed) |
| PA-8 | pytest (account) | The conditional update is the gate: filter carries `$expr` cash − blocked ≥ amount with `$inc` in the same write | the update filter on the accounts collection has `$expr`; the fakes evaluate it rather than ignore it |
| PA-9 | pytest (account) | Existing behaviour kept: exactly the available amount allowed, `None` refused, first reserve on a fresh account keeps the opening balance (`ensure`), per-user isolation, ledger unchanged | existing tests in `tests/test_paper_account.py` still pass |
| PA-10 | pytest (script) | `check_desk_alerts.run(dry_run=True)` with an open strategy trade whose target fired | trade stays open, no trade or account write, `strategy_exits` reports `{"target": 1}` |
| PA-11 | pytest (script) | `check_desk_alerts.run()` (persist) on the same | trade closed with `exit_reason` target; capital released with its net P&L; a rerun writes nothing and releases nothing |
| PA-12 | pytest (script) | Strategy price reads fail and there is nothing else to check | `strategy_not_checked` = 1 and `ok` False (exit 1 from main) |
| PA-13 | pytest (sim) | Gap through the stop (open 93 under stop 95), renamed test | exit at the open 93.0, not the stop; `gap_through_stop` flag with price 93 |
| PA-14 | pytest (sim) | Break-above entry on a session that opens at 105 beyond the 103 trigger, renamed test | fill 105.0 (the open), `entry_gap` flag with price 105 |
| PA-15 | static (pytest) | The F&O forward-test cron entry exists in the repo: `deploy/nivesh-staging/fno-forward.cron` runs `scripts.record_fno_forward` Mon-Fri at 22:45 IST (after the 22:15 F&O bhavcopy retry), `CRON_TZ=Asia/Kolkata`, same `docker exec nivesh-staging-app-backend` style; the installer exists | test reads the files and asserts the line |
| PA-16 | compile | `python -m compileall -q services scripts` | exit 0, no output |
