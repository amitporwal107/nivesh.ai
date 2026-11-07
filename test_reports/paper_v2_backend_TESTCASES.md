# Paper Trading v2 — backend gaps: test cases (UI_DESIGN_V2.md §3, §4, §7)

Written 5 Nov 2026 IST, BEFORE the implementation (CONTEXT.md §4a: test cases up front). Branch `feat/paper-trading-v2`.
Tests: `backend/tests/test_paper_v2_*.py`, in-memory fakes only. MOCK — not real data: every user, symbol, price,
position, chain and signal in a fixture is made up; no staging data is read or written by any test.

Scope (UI_DESIGN_V2 §4 items 1–6): `GET /api/v1/paper/overview`, `GET/PUT /api/v1/paper/accounts/{id}/policy` (+ admin
`GET/PUT /api/admin/spt/{user_id}/policy`), `GET /api/v1/risk/correlation/{id}`, the named stress scenarios on the existing
`GET /api/v1/risk/stress-test/{id}`, `GET /api/v1/analytics/account/{id}`, `GET /api/v1/paper/fno-structures`.

## Interpretations (read first; each is reported to the integrator)

| # | What | Why |
|---|---|---|
| PV2-I-1 | **Combined policy version = risk_profile `version` + SPT config `version`.** Nothing new is stored. | Both counters only ever increase by one per change, so their sum strictly increases with every change to either store and names one state in the history. `expected_version` is checked against the sum, and each store's own compare-and-set (profile: a new optional `expected_version` on `risk_profile.set_limits`; SPT: `policy.update(expected_version=…)`) is given the exact version read, so a change landing between the check and the write is refused (409). A mode change (PUT …/config) also moves the SPT counter, so it moves the policy version too. |
| PV2-I-2 | **Atomic write:** validate everything for both stores (ranges, buckets, ladder, halt > restricted, the profile's own cross-rules, permissions, version) → write the two stores one after the other → if the second fails, restore the first to what was read (compare-and-set on the version just written; "rollback" reason) and answer the second store's refusal (409 / 403 / 422) or 500 `policy_write_failed`, with `rolled_back: true`. A restore that cannot land → 500 `policy_rollback_failed` naming what is left. **Order:** the SPT config first when its new overrides are valid under the profile as it is now (then both stores judge "looser" against the same state the plan did); otherwise (a ladder valid only under the new halt) the profile first — in that order SPT judges its restricted level against the NEW halt's default, so a level above ⅔ of a lowered halt is an admin's change (PV2-B-10e). *(Revised during the build: a profile-first-only order made the SPT store call a holder's tightening "looser"; found in self-review.)* | Mongo on staging is a single node (DESIGN D7): no multi-document transaction. A compensating write is the only way to keep "nothing half written". |
| PV2-I-3 | **Reason.** The account holder's PUT may omit `reason`; the risk profile requires one for every change, so the stored reason is then "Paper Trading › policy panel (no reason entered)". A loosening (admin) needs a reason (422 `reason_required`), as both stores already rule. The admin route always needs one. | risk_profile.set_limits refuses an empty reason; the generated text says where the change came from and nothing more. |
| PV2-I-4 | **Defaults (`null`).** An SPT field set to `null` drops its override (back to the profile-derived default). A risk-profile field set to `null` goes back to the owner default profile's value (`owner-default-2026-10-27`). | The profile stores full limits, not overrides; the owner default is the system default. |
| PV2-I-5 | **Buckets.** The three buckets map to `allocation_buckets_pct.{equity_positional, equity_intraday, fno}`; the reserve leaf is written as 100 − their sum (dropped back to its default when it equals it). The reserve falling is LOOSER (SPT policy's existing rule), so raising a bucket without lowering another needs an admin; the 403 names the bucket key(s) that rose. | SPT's config requires the four to total 100; the design derives the reserve. |
| PV2-I-6 | **New SPT extras** `fno_max_loss_pct` = profile `per_trade_risk_pct` × 0.7 (0.35 % for the owner default; PRD §9.4 / §26 "F&O strategy risk 0.35 %"; owner rule 5 Nov: defaults come from the risk profile) and `margin_util_pct` 70 ("owner's Paper Trading v2 design (5 Nov); PRD has no figure; configurable"). Higher is looser for both. *(Corrected 5 Nov: the first build used 0.65, a design SAMPLE figure that must never ship.)* | The same derivation as `risk_pct.fno`; the source is named in `defaults_source`. |
| PV2-I-7 | **Correlation prices** = the validation's own source (`services/spt/opportunities/inputs` → `desk_trading.fetch_bars`, NSE bhavcopy, raw traded prices). A series whose window holds a one-day move of 18 % or more (or the exit-watch break rule 0.65 / 1.5) is treated as a possible unadjusted bonus / split / gap: its row and column are null with that reason. Fewer than max(20, ⌈⅔·days⌉) overlapping returns → null. | The source is NOT bonus/split adjusted (memory: HDFCAMC); a fake correlation is worse than none. A bonus smaller than 1:4 (< 18 % price change) is not detected — said in `notes`. |
| PV2-I-8 | **Analytics** read closed SPT positions only (`spt_positions` CLOSED with an outcome). Desk paper trades are not included: they have no setup type or regime at entry from the scanner pipeline. R = the position's own `outcome.r_multiple` (net P&L after all fill costs / initial price risk). Sharpe / Sortino are on a realised-only daily series (no daily marks of open SPT positions are stored). | Stated in `basis` and `notes`. |
| PV2-I-9 | **F&O structures** = the desk's open paper strategy trades (`desk_paper_trades` kind "strategy"), read without applying exits (`services/paper_pnl/book.read_book`). Leg LTP by the /api/desk/pnl rule (`paper_pnl.prices.resolve`: live → Kite close → EOD); payoff, breakevens, Greeks and scenarios by `services/positions` (`paper_groups` → `analytics`) on the F&O chain; margin by Zerodha's calculator (a calculation, nothing placed), null with a reason when the platform has no Kite session. Desk paper legs are all recorded at once, so `status: "partial"` appears only for a leg with no recorded entry (pending). | The design's "partially filled · unhedged" state has no source in desk paper trades today; the detection is built and tested on synthetic legs. |

## Test cases

| Id | Area | Case | Expected |
|---|---|---|---|
| PV2-B-01 | auth | Every new route without a session | 401 |
| PV2-B-02 | auth | `{id}` ≠ the caller on policy GET/PUT, correlation, analytics | 403 `not_your_account` |
| PV2-B-03 | auth | Admin policy routes as a non-admin | 403 (require_role("admin")) |
| PV2-B-04 | policy GET | A fresh account | 200; `fields` has exactly the 14 §7 keys, each with value, default, min, max, step, unit, store, overridden, loosen_needs_admin, label; owner defaults 0.5 / 3 / 2 / 4 / 6.67 / 10 / 10 / 25 / 70 / 0.35 / 45 / 25 / 20 / 10; `version` 0; `derived.reserve_pct` 10, `per_trade_risk_rs` 5,000 on ₹10L |
| PV2-B-05 | policy PUT | The holder tightens a profile field and an SPT field in one PUT | 200; profile limit and SPT override both changed; version = old + 2; one profile audit row and one SPT version row |
| PV2-B-06 | policy PUT | The holder loosens (risk per trade 0.5 → 1.0) | 403 `{code: admin_required, loosened: ["per_trade_risk_pct", "fno_max_loss_pct"]}` (the F&O limit is 0.7 × it, so it loosens too); no store written, no audit / version row |
| PV2-B-07 | policy PUT | Tighten one + loosen another in one PUT | 403 naming only the loosened key; the tightened one is NOT written either |
| PV2-B-08 | policy PUT | `expected_version` stale | 409 `{code: version_conflict}`; nothing written |
| PV2-B-09 | policy PUT | Bad input | 422 `{code, field, message}`: out of range (field named), unknown key, non-number, buckets over 100 (`reserve_negative`), halt ≤ restricted (`halt_not_above_restricted`), max open risk < per trade (profile rule), `no_change`; nothing written |
| PV2-B-10 | policy PUT | One store's write fails after the other's | SPT-first order, the profile write fails → the SPT write is undone (overrides back, a "rollback" version row); profile-first order, the SPT write fails → the profile is back to its limits (audit row "rollback…"); 500 `policy_write_failed`, `rolled_back: true` (10, 10b); a failed restore → 500 `policy_rollback_failed` naming what is left (10c); a profile race → 409 with the SPT part undone (10d); profile-first and the SPT store refuses a restricted level above the new halt's ⅔ → 403 with the profile put back (10e); both orders succeed end to end (10f) |
| PV2-B-11 | policy PUT | `null` values | SPT field → override removed (`overridden: false`); profile field → owner default |
| PV2-B-12 | admin | Admin loosens with a reason / without | 200 / 422 `reason_required` |
| PV2-B-13 | policy PUT | Raise a bucket, lower another by the same amount | 200 (neutral), reserve unchanged; raise one only → 403 naming that bucket; reserve < 5 is allowed for an admin and shows in `derived` |
| PV2-B-14 | SPT config | The new extras | `policy.read` carries `margin_util_pct` 70 / `fno_max_loss_pct` 0.35 (0.7 × the profile's 0.5) with their source; the existing PUT …/config can tighten them; loosening → 403; with no override the F&O limit follows a profile change (14b) |
| PV2-B-15 | overview | Shape and counts | status / kpis / pipeline (6 stages in the §7 order) / warnings / headline; counts from fixtures: signals of the IST day, opportunities, QUALIFIED, risk-approved proposals, filled entry orders, open positions |
| PV2-B-16 | overview | Warnings | a risk refusal today → danger `RISK_REJECTED` with symbol and time; open risk > 80 % of its limit → amber `NEAR_LIMIT_OPEN_RISK`; feed down in session → danger `FEED_DOWN`; nothing wrong → one mint `FEEDS_HEALTHY` |
| PV2-B-17 | overview | Feed mapping (pure) | live → live; delayed → stale; closed → closed; expired / not_connected / disabled → down |
| PV2-B-18 | correlation | Math (pure, hand-checked) | ρ of two constructed return series equals the hand value to 1e-6; diagonal 1; symmetric; `threshold` 0.7 |
| PV2-B-19 | correlation | Nulls | short series → null + reason; a −50 % one-day move (unadjusted bonus) → that symbol's row/column null + reason; unreadable bars → null + reason; `?with=` added; bad `with` → 422 |
| PV2-B-20 | stress | Named scenarios | index_down, sector_gap, correlated_stops, gap_beyond_stops, iv_up each with label, loss_rs and assumption; the three existing scenarios unchanged; hand-checked figures |
| PV2-B-21 | analytics | Math on a fixture | trades, wins, losses, win rate, avg win / loss R, expectancy R, profit factor, max drawdown equal the hand-worked values |
| PV2-B-22 | analytics | Ratios | < 20 daily points → sharpe / sortino null with `ratio_reason`; ≥ 20 → equal to the hand-worked values |
| PV2-B-23 | analytics | Groups and certification | by_setup and by_regime (bullish → uptrend, bearish → downtrend, sideways → sideways, high volatility / mixed by the Nifty trend, missing → unknown); certification: min 50 fail, expectancy / PF pass or warn (n < 30), out-of-sample `not_measured`, regimes ≥ 2 |
| PV2-B-24 | F&O | Shape and figures | one structure per open desk strategy: legs, net Greeks, max loss / profit, breakevens, scenarios (±1 / ±2 %, IV ±5, 1-day theta, expiry at the level), margin; totals; limits from the policy |
| PV2-B-25 | F&O | Fill state | a leg with no entry → `status: partial`, `pending: true`, `filled_qty` 0, leg P&L null; an uncovered short option → `hedged: false` |
| PV2-B-26 | F&O | Unpriced | a leg with no implied volatility → Greeks and the IV / theta scenarios null with a note, never 0; no Kite session → `margin_rs` null with `margin_reason` |
| PV2-B-27 | wording | Compliance | no "recommend", "pick" or "suggest" in any string of the new responses |
| PV2-B-28 | reads | GET routes write nothing | the policy, SPT config, proposal, order and position stores are unchanged after every GET |

### Added 5 Nov (second request): bucket risk and setup type

| Id | Area | Case | Expected |
|---|---|---|---|
| PV2-B-29 | bucket risk | The open-risk rows (pure) | every reservation and every unreserved position is one row with its bucket (SPT: its proposal's horizon / instrument; other reservations by kind, structure → fno; legacy strategy → fno; shares / journal → equity_positional) and sector; summed by bucket and by sector with one helper |
| PV2-B-30 | bucket risk | GET /api/v1/risk/account | `utilisation.buckets[k].risk_rs` per bucket; their sum equals `open_risk.rs`; `used_rs` unchanged (SPT reservations only, said in `bucket_risk_basis`); the overview's concentration reads the same rows; an unreadable book → every `risk_rs` null |
| PV2-B-31 | setup type | Each row kind | scanner → the opportunity's stored `category`; desk F&O → `family`; desk shares → `source.bucket`; nothing stored → null (a source `kind` is not a setup type); on open rows, closed rows and strategy entries, with `setup_type_source` |
| PV2-B-32 | setup type | Over /api/desk/pnl | ONE batched `spt_opportunities` read per book build; a missing opportunity → null; an unreadable store → null and the position still shown |
| PV2-B-33 | F&O id | fno-structures `id` vs /api/desk/pnl `strategy_id` | equal for the same structure (both the published trade's id) |

## Status (5 Nov 2026, 08:39 IST, after the fno_max_loss_pct default correction — output in `test_reports/paper_v2_backend_pytest.txt`)

- PV2-B-01 … PV2-B-28: covered by `backend/tests/test_paper_v2_{policy,overview,risk,analytics,fno,routes}.py` —
  **78 passed** (`tests/test_paper_v2_*.py`) in the backend image, MOCK fixtures only.
- Regression set (paper_pnl, spt_*, risk*, paper*, desk_trading*, scan_builder*, exit_rules*, exit_watch,
  order_path_guard): **1480 passed, 5 skipped, 0 failed**.
- 09:28 IST, after PV2-B-29..33 (bucket risk, setup type): `tests/test_paper_v2_*.py tests/test_paper_pnl*.py` **147 passed**;
  regression set **1488 passed, 5 skipped, 0 failed** (appended to the same output file).
- **UNVERIFIED on staging:** nothing here was deployed or called against the staging API or its data (the brief forbids
  writes to staging; the code is not in the running image). Every claim above is about the unit/route tests on fakes.
  Needed next (integrator): deploy the branch to staging and call the seven routes with a real session; check the
  overview counts against `spt_signal_events` / `spt_opportunities` of the day, the F&O structures against
  `/api/desk/pnl`, and a policy PUT round trip on a test account.
