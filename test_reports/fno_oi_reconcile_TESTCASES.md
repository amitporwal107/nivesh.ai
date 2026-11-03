# F&O OI reconciliation — test cases (authored before implementation)

- **Branch:** feat/fno-oi-reconcile (from origin/dev 5152e19d)
- **Date:** 2026-11-03
- **Ask:** the owner's validation framework (pasted 3 Nov, after "For HDFCAMC the OI delta looks to be unreal"): a
  reconciliation test between three data sources — the previous session's NSE F&O bhavcopy, the current session's
  bhavcopy, and the intraday (Kite) snapshots — and what the app shows (option chain table, chart).
- **Design:** `backend/services/fno_oi_reconcile.py` (pure checks, no I/O) + `backend/scripts/reconcile_fno_oi.py`
  (reads the app's own F&O routes in-process as a system caller, the same code the screen calls, and the bhavcopy
  through the data platform; prints a report; writes nothing). Read only. Not scheduled (a schedule is a separate,
  approved step).

## The seven checks (the owner's table → what is compared)

| ID | Owner's line | Compared | Source of truth |
|----|--------------|----------|-----------------|
| C1 | Previous-day closing OI matches previous session bhavcopy | app chain/futures `oi − change_in_oi` per contract vs bhavcopy OI on the previous session | bhavcopy D−1 |
| C2 | Current closing OI matches current session bhavcopy | app chain/futures `oi`; chart futures pane last daily bar; Kite's last intraday candle ON day D (futures + options) | bhavcopy D |
| C3 | OI change = current OI − previous OI | app `change_in_oi` (chain, futures, chart daily bar) vs bhavcopy D − bhavcopy D−1 | bhavcopy D, D−1 |
| C4 | OI change % = change / previous OI × 100 | the screen's formula (`oiChangePct`, `pctOf`: change ÷ (oi − change)) on the app's figures vs (D − D−1) ÷ D−1 from the bhavcopy; WARN when the base is under 10 lots and the % is ±100 or more | bhavcopy D, D−1 |
| C5 | Intraday OI change matches intraday snapshot differences | futures windows: `oi_change` = this window's OI − the previous window's; options pane: summed CE/PE OI = Σ contract candles, `ce/pe_oi_change` = row − previous row; WARN when the pane has no sums at all | Kite candles |
| C6 | Chart total OI matches option-chain table OI | chain summary totals (PCR, walls) vs Σ bhavcopy for the expiry; consolidated strike = Σ per-expiry chain rows; chart futures pane last OI = futures route OI (and Σ for consolidated) | bhavcopy D, chain route |
| C7 | Increase/decrease segments sum to net OI movement | per series: Σ increases + Σ decreases vs last OI − first OI; a gap is attributed to contract rolls when the series changes contract | the series itself |

Statuses: PASS (matched), FAIL (did not match: figure wrong or misleading by construction), WARN (figures match but the
display misleads or is empty), SKIP (a source could not answer: the reason is printed; never counted as a pass).

## Test cases

| ID | Area | Scenario | Type | Expected |
|----|------|----------|------|----------|
| TC-1 | C1 | chain put OI 17,100, change +16,200; bhavcopy D−1 900 | unit | PASS |
| TC-2 | C1 | same, bhavcopy D−1 1,200 | unit | FAIL, diff 300 |
| TC-3 | C1/C3 | contract absent on D−1 (newly listed), change = OI | unit | PASS (previous = 0) |
| TC-4 | C2 | app OI ≠ bhavcopy D OI | unit | FAIL with both figures |
| TC-5 | C2 | Kite last candle on D 31,800 vs bhavcopy 32,100 | unit | FAIL, diff −300, labelled Kite vs bhavcopy |
| TC-6 | C2 | Kite has no candle for the contract on D | unit | counted as not comparable (SKIP line), not PASS |
| TC-7 | C3 | app change_in_oi = D − D−1 | unit | PASS; off by one lot → FAIL |
| TC-8 | C4 | 900 → 17,100, lot 300 | unit | % = +1800.0 both ways → PASS + WARN small base (3 lots → 57 lots) |
| TC-9 | C4 | D−1 = 0, D = 300 | unit | no % on screen and none expected → PASS (shown as new) |
| TC-10 | C4 | 128,400 → 101,100 | unit | −21.3 % both ways, base 428 lots → PASS, no WARN |
| TC-11 | C5 | windows oi 100, 90 (change −10), 95 (change +5) | unit | PASS; a window with change −9 → FAIL |
| TC-12 | C5 | options series sums = Σ contract candles, changes = row diffs | unit | PASS; a wrong sum → FAIL |
| TC-13 | C5 | options series all null (a contract with no candle) | unit | WARN "the pane has no sums", with the missing contracts |
| TC-14 | C6 | chain summary total_call_oi = Σ bhavcopy CE OI for the expiry | unit | PASS; off → FAIL |
| TC-15 | C6 | consolidated strike = Σ per-expiry chain rows | unit | PASS; off → FAIL |
| TC-16 | C6 | chart daily last OI per slot = futures route OI for the slot's expiry; consolidated = Σ | unit | PASS |
| TC-17 | C7 | daily series with one roll: 650,100 → 7,226,700 (new contract change +21,300) | unit | FAIL, gap = roll jump 6,555,300, 1 roll named |
| TC-18 | C7 | consolidated daily series | unit | PASS (Σ changes = net) |
| TC-19 | report | statuses roll up per check (FAIL > WARN > PASS > SKIP), exit code 3 on any FAIL, 0 otherwise | unit | as stated |
| TC-20 | staging | HDFCAMC on staging, 3 Nov 2026 vs 2 Nov | api (in-process routes, real data) | C1, C3 PASS for every chain contract; C4 PASS + WARN on 2,380 / 2,420 / 2,440 PE; C7 FAIL for current / next / far daily, PASS consolidated; C2 Kite vs bhavcopy differences reported as found |
| TC-21 | staging | 3 more F&O stocks (RELIANCE, TVSMOTOR, SONACOMS) | api | runs end to end; every check has a status; no crash |
| TC-22 | data | independent SQL on nidp.fno_bhavcopy for sampled contracts | data | the reconciler's expected figures equal the SQL figures |
| TC-23 | safety | the run writes nothing (no DB write, no Kite order call) | review | ReadOnlyKite + GET-only routes; no insert/update in the code |
