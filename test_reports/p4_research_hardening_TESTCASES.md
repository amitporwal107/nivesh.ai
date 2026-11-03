# Test cases — Phase 4 research hardening (4.1 CI, payoff costs, 4.2 universe + reproducibility, 4.4 scope, RS63 readiness)

Authored 2026-10-27, after the design below and BEFORE implementation (VERIFICATION_PROTOCOL §1).
Branch `feat/p4-research-hardening` off origin/dev `ce923426`, worktree `/home/deploy/nivesh-p4-hardening`.

## Design (fixed before code)

1. **CI (4.1).** A new workflow `.github/workflows/backend-tests.yml`: `pull_request` to `dev` and `main`, Python 3.11 pinned,
   `uv` pinned, the repo's `backend/requirements.txt` resolved the way the production image resolves it (same overrides, the
   private-index package skipped), then `pytest` over an explicit allowlist of suites that collect and pass with no Mongo,
   Postgres or secrets (placeholder env only). The allowlist lives in the workflow; the excluded suites and the reason for each
   are in the PR body. The proposal file is removed (superseded).
2. **Payoff costs.** `services/strategy_plan/payoff.py` prices every leg side with the desk cost card
   (`services/desk_cost_card.order_side`): option legs on the premium (segment `options`), futures (`futures`), cash
   (`equity_delivery`); entry side = the leg's side, exit side = the opposite, the exit value = expiry intrinsic (options) or the
   price (cash, futures). The request's `costs.slippage_pct` / `costs.brokerage_per_side` still override the card's slippage and
   brokerage. The worthless-expiry convention is unchanged (no exit order in the net curve; charged in `capital_at_risk`).
   `CALCULATION_VERSION` `payoff-v1` → `payoff-v2`. `compute_payoff(body, today)` keeps its signature and every output key; the
   gross figures (`max_loss`, `max_profit`, breakevens, gross arrays) do not change.
3. **Point-in-time liquid EQ universe (4.2).** DSL universe `{"type": "market", "ref": "LIQUID_EQ"}`, rule `liquid-eq-v1`:
   on session d a symbol is a member when it has a series-EQ bar on d with a raw close ≥ ₹20, at least 20 EQ bars with a close
   and a volume among the 30 sessions ending at d, a median close × volume over its latest 20 of those ≥ ₹10 crore, and a name
   that is not an ETF (ends in BEES or ETF). Only data up to and including d is read. Both providers compute it with one pure
   function; the DaaS provider reads `GET /prices/eod?on=&series=EQ` per session (an existing endpoint, no NIDP change).
   It becomes the default for "all stocks" universes (screen→strategy default, first Broad Market card, page default). Index
   universes keep `universe_basis = latest_snapshot` and gain a `universe_warning` (survivorship bias) shown in the UI.
4. **Reproducibility (4.2).** Each run records `data_watermark` (+ `strategy_runs.snapshot_as_of`), `code_version`
   (git SHA, engine SHA-256 including the universe and DSL modules), `rule_version` (DSL version, spec SHA-256, strategy
   version id) and `cost_model` (version and parameters), gathered in `metrics.provenance`. `GET /runs/{id}` returns a
   `provenance` block for every run; a field an older run never recorded reads `null` with `not_recorded` listing it.
5. **Docs.** `docs/ai_research/P4_SCOPE_INTRADAY_BEARISH.md` (4.4) and `docs/ai_research/P4_POINT_IN_TIME_UNIVERSE.md`
   (rule + the NSE historical index import as an owner decision).
6. **RS63 readiness.** `research/p4_adx_rs/check_rs63_readiness.py`: counts signal dates after 2026-10-09 whose 10-session
   outcome is complete and their regime (Nifty 50 vs its 200-session average); READY only at ≥ 60 dates and ≥ 20 per regime.
   It reads sessions and Nifty 50 closes only, never prices of stocks or scores, so it cannot run the study early.

## Test cases

| ID | Area | Scenario | Type | Expected |
|----|------|----------|------|----------|
| TC-CI-1 | CI | workflow triggers, pins, env | static | `pull_request` → `dev`, `main`; Python 3.11 + uv pinned; no `secrets.` reference; placeholder env only |
| TC-CI-2 | CI | exact CI command in a clean `python:3.11` container with the repo's requirements | integration | install + tests exit 0, all selected suites pass, wall time ≲ 5 min |
| TC-CI-3 | CI | regression changes an expected number | negative control | same command on a copy with one PRD-example expectation altered exits non-zero |
| TC-CI-4 | CI | allowlist covers the named suites | static | `test_prd_worked_examples`, `test_exit_rules`, `test_order_path_guard` + this PR's suites are in the list |
| TC-CI-5 | CI | excluded suites | report | every excluded suite listed with its collection / environment reason |
| TC-PC-1 | payoff | bull call spread, both legs ITM at a scenario | unit | net = gross − card costs; each component (brokerage, STT, exchange, SEBI, stamp, GST, slippage) hand-derived |
| TC-PC-2 | payoff | `capital_at_risk` | unit | worst net loss with card costs on every side incl. worthless exits; re-derived |
| TC-PC-3 | payoff | costs block | unit | `model` = desk-cost-v2, `components` breakdown, `excluded` = DP / IPFT & clearing / income tax only |
| TC-PC-4 | payoff | request overrides | unit | `slippage_pct` / `brokerage_per_side` override the card's; statutory charges still applied |
| TC-PC-5 | payoff | version + compatibility | unit | `calculation_version` payoff-v2; signature unchanged; gross outputs identical to payoff-v1 |
| TC-PC-6 | payoff | parity with the paper trade | property | round-trip cost at an all-ITM expiry price = `desk_strategy_trades.strategy_cost_breakdown` at intrinsic marks, to the paisa |
| TC-PC-7 | payoff | pre-expiry net | unit | uses the card (exit side at the Black-76 value) |
| TC-PC-8 | payoff | cash leg / future leg segments | unit | cash → equity_delivery (STT both sides), future → futures (STT sell side) |
| TC-PC-9 | payoff | worthless expiry | edge | net curve: no exit order; capital_at_risk: exit brokerage + GST charged |
| TC-PC-10 | consumers | ideas, regime-fit, strategy_levels, F&O candidates, TradePlan, PRD examples | regression | suites pass; every changed expected number re-derived with its reason |
| TC-LU-1 | universe | each condition of liquid-eq-v1 | unit | in when all hold; out on close < 20, < 20 bars, median < ₹10 cr, not priced on d, ETF name, non-EQ series |
| TC-LU-2 | universe | point in time | property | membership at d identical with or without bars after d |
| TC-LU-3 | universe | survivorship | unit | a symbol that stops trading is a member while it traded, not after; the backtest can enter it on those dates |
| TC-LU-4 | universe | missing price session | edge | membership survives a missing session (20 of 30); the session is reported in `universe_rule.sessions_without_prices` |
| TC-LU-5 | DSL | market universe validation | unit | STOCK + LIQUID_EQ valid; MF rejected; unknown ref rejected |
| TC-LU-6 | DaaS provider | prepare / screen | unit (fake client) | per-session EOD reads incl. 29-session lookback; features fetched only for the union; screen limited to that date's members; basis point_in_time + rule |
| TC-LU-7 | SQL provider | prepare / screen | unit (fake pool) | same rule from SQL rows; compiled SQL binds `ANY($n)` per date |
| TC-LU-8 | DaaS failure | EOD read fails | failure | backtest raises (no silent empty universe) |
| TC-LU-9 | index universe | latest snapshot | unit | `universe_basis` latest_snapshot + `universe_warning` naming survivorship bias |
| TC-LU-10 | defaults | screen→strategy, catalog | unit | default universe market/LIQUID_EQ; catalog's first Broad Market card carries `universe` {market, LIQUID_EQ} |
| TC-LU-11 | universe data | staging, read-only | data | per-date member counts in band; the SQL equivalent on the warehouse and the Python rule on the same rows agree |
| TC-LU-12 | UI | warning + default | e2e (mocked API) | index-universe result shows `backtest-survivorship-warning`; liquid result shows `backtest-universe-pit`; liquid card first and selected by default |
| TC-RP-1 | repro | run provenance | unit | metrics.provenance has data watermark, code version, rule version (spec SHA-256 stable under key order), cost model, universe rule |
| TC-RP-2 | repro | persist_run | unit | `snapshot_as_of` written from the watermark; provenance inside metrics |
| TC-RP-3 | repro | old runs | unit | a run row without these fields → provenance with nulls and `not_recorded`, no error |
| TC-RP-4 | repro | staging stored runs | data, read-only | the stored rows' metrics read through the normaliser → `not_recorded` lists exactly what is missing |
| TC-DOC-1 | 4.4 | scope doc | review | four items, each with the code that enforces it today and exact preconditions to lift it |
| TC-DOC-2 | 4.2 | index history decision | review | source, effort, staging write and validation for importing NSE historical index files; not executed |
| TC-RS-1 | RS63 | readiness counter | unit | counts only dates > 2026-10-09 with a complete 10-session outcome; regime by Nifty 50 vs SMA200; READY at ≥ 60 and ≥ 20 per regime; deadline note after 2027-06-30 |
| TC-RS-2 | RS63 | staging now | data, read-only | reports NOT READY with the real counts |
| TC-SAFE-1 | safety | `tests/test_order_path_guard.py` | regression | passes |
| TC-REG-1 | regression | full backend suite, branch vs origin/dev | regression | "fails on branch, passes on dev" is empty |
