# Smart Money Movement — live desk tab (06), functionality verification

**Date:** 2026-10-22 · **Branch:** `feat/provider-foundations` · **Author:** Claude (Opus 5)
**Scope of this verdict:** the code paths reachable without a DaaS process restart. The
staging-API leg is **carved out** into `test_reports/OVERRIDE_smart_money_staging_api.md`
because the container restart was denied by the permission classifier. This report's PASS
therefore means "built, typechecked, unit-verified, UI-verified, and SQL-verified against the
real warehouse" — it does **not** mean "live on staging". See §6.

---

## 1. What was built

| Layer | File | State |
|---|---|---|
| DaaS router | `backend/nidp/services/daas_api/routers/smart_money.py` | new, 5 routes |
| DaaS registration | `.../daas_api/app.py`, `.../routers/catalog.py` | import + `include_router` + 2 dataset entries |
| App proxy | `backend/routes/markets_smart_money.py` | new, 5 routes |
| App registration | `backend/server.py` | import + `include_router` |
| Frontend data | `frontend-v5/src/pages/CopilotApp/screens/tradingdesk/smart-money-data.ts` | new |
| Frontend tab | `.../tradingdesk/SmartMoneyTab.tsx` | new |
| Tab registration | `.../tradingdesk/context.tsx`, `.../TradingDesk.tsx`, `.../tradingdesk/BottomBar.tsx` | 5 points |
| Backend test | `backend/nidp/tests/services/test_daas_smart_money.py` | new, 13 cases |
| UI test | `frontend-v5/e2e/tests/copilot-app-desk-smart-money.spec.ts` | new, 13 cases |
| Regression | `frontend-v5/e2e/tests/copilot-app-desk.spec.ts` | tab arrays 6 -> 7 |

Endpoints: `/api/markets/smart-money/{feeds,flows,sectors,breadth,scanner}`
-> DaaS `/v1/desk/smart-money/*`.

## 2. The tab's place in the row

The chip number is the `NAV` index (`String(i+1).padStart(2,"0")`) while More's was a hardcoded
`"06"`, so a literal "07 Smart Money" and the position "peer of 03 Market Intelligence" could not
both hold. Decision: **Smart Money renders as `06`, More moves to `07`** — More is an overflow
chip and belongs last. More's number is now derived from `NAV.length + 1` rather than a literal,
so it cannot drift again.

Adding a member to `DESK_TABS` is not free: `moreOn = more || tab === "fno" || tab === "events"`
(`TradingDesk.tsx:344`) lets TypeScript narrow `tab` in
`const bottomKey: BottomKey = moreOn ? "more" : tab` (`:534`). Omitting the `BottomKey` member is
a compile error, and excluding it the fno/events way would hide the tab on phones. The phone bar
therefore gained an entry (`Flows`, aria `Smart Money Movement`).

## 3. Real warehouse verification (SQL, this session)

Queried via `~/.config/nivesh/nidp-psql.sh` against staging `nidp_staging`.

### 3.1 Feeds — the ingest date is not the data date
```
          label           | status | stale_d | ingested_for | data_as_of
--------------------------+--------+---------+--------------+------------
 AMFI scheme portfolios   | STALE  |       9 | 2026-09-01   | 2026-09-01
 Shareholding patterns    | OK     |       0 | 2026-10-22   | 2026-09-30
 FII/DII cash (Sensibull) | OK     |       0 | 2026-10-22   | 2026-10-21
 Deals (Trendlyne)        | OK     |       0 | 2026-10-22   | 2026-10-21
```
Shareholding is 22 days apart. A strip printing the view's date as "data as of" would mislead,
so both are served and the UI labels which is which.

### 3.2 Flows — one grain per window
```
    date    | fii_net | dii_net | fii_cum | dii_cum
------------+---------+---------+---------+---------
 2026-10-21 |    1022 |    1614 | -101382 |  201070

 rows_returned | first_month | last_month | fii_total | dii_total
---------------+-------------+------------+-----------+-----------
            12 | 2025-11-01  | 2026-10-01 |   -503813 |    849222
```
1Y returns exactly 12 monthly rows. The daily series begins 2026-04-01 (138 sessions), so a 1Y
window answered from daily rows truncates to ~6.7 months and looks plausible — hence the grain
switch, asserted in the backend test.

### 3.3 Sectors — pinned month pair
```
    cur     |    prv
------------+------------
 2026-09-01 | 2026-08-01

          industry          | stocks | priced | net_value_cr | schemes_up | schemes_dn
----------------------------+--------+--------+--------------+------------+------------
 Financial Services         |     98 |     98 |        45225 |       7000 |       5849
 Healthcare                 |     44 |     44 |        24993 |       2878 |       2346
 Consumer Services          |     23 |     23 |        12799 |       1457 |       1300
 Telecommunication          |     11 |     11 |        12595 |        662 |        486
 Oil Gas & Consumable Fuels |     19 |     19 |         8287 |       1350 |       1210
```

### 3.4 Breadth — the point-in-time filter halves the counts
```
 point_in_time | rows | rising | direct_and_proxy | direct_only | single_amc | disclosure_as_of
---------------+------+--------+------------------+-------------+------------+------------------
 f             |  984 |    449 |              416 |          33 |        372 | 2026-09-01
 t             |  976 |    449 |              417 |          32 |        379 | 2026-09-01

 validated_study
-----------------
 f
```
The table carries both series on the same date. An audit that omitted `point_in_time` reported
1,960 / 898 / 833 / 65 — the two series summed. The router filters to the `t` series; the `f`
series is the reporting-date (look-ahead) one the study excluded.
`validated_study = f` is read live from `smart_money_promotion_decisions` and is what drives the
"Evidence only · not scored" pill rather than a hardcoded string.

## 4. Backend test — real output
```
$ python -m pytest nidp/tests/services/test_daas_smart_money.py -q
.............                                                            [100%]
13 passed, 1 warning in 0.60s
```
Thirteen cases, of which these guard figures that would otherwise be wrong-but-plausible:
`point_in_time IS TRUE` present; `v_smart_money_shadow_rank` and `evidence_class` absent;
1Y binds `SENSIBULL_MONTHLY` and 1M/3M/6M bind `SENSIBULL`; sectors pin both months;
`series IN ('EQ','BE')` and `DUMMYHEG` exclusion present; shareholding deduped
`DISTINCT ON (symbol, period_end)` ordered by `(fii_pct IS NOT NULL) DESC`;
`v_trendlyne_deals_net` and `trendlyne_deal_fetch_log` used; no data is 200-with-empty, never 500.

## 5. UI test — real Playwright output
Production build, `vite preview` on :5174, `/api/*` answered by route mocks whose **figures are
the real staging numbers above**, so a shape drift fails an assertion instead of blanking a panel.
```
$ npx playwright test --config pw.copilot-app.config.ts e2e/tests/copilot-app-desk-smart-money.spec.ts
13 passed (9.4s)
```
TC-F1 06/07 numbering · TC-F2 "not scored" · TC-F3 disclosure date + 51d age (not the compute
date) · TC-F4 1Y switches to monthly · TC-F5 point-in-time tiles · TC-F6 the three deal states
read differently · TC-F7 evidence class derived per row · TC-F8 data date vs loader run ·
TC-F9 footer refuses a hit rate · TC-F10 partial failure keeps the screen · TC-F11 total failure
errors · TC-F12 phone bar · TC-F13 no score/rank/hit-rate string in the DOM.

Three initial failures were my assertions, not product defects: the app formats dates as
"1 Sept 2026" and numbers in the Indian grouping ("27,95,13,109"). Assertions were made
locale-tolerant; no product code changed.

### Regression
```
$ npx playwright test ... e2e/tests/copilot-app-desk.spec.ts           -> 19 passed (24.6s)
$ npx playwright test ... copilot-app-desk-market.spec.ts copilot-app-screens.spec.ts
                                                                       -> 55 passed (1.2m)
$ npx tsc --noEmit -p tsconfig.json                                    -> TSC_EXIT=0
```
The typecheck was clean before the change too, so the exit 0 is attributable.

## 6. What this screen deliberately refuses to say

The validation study (`NIDP-SM-VALIDATION-001/002`) returned **INCONCLUSIVE** at
`stage = exploratory`, and `smart_money_promotion_decisions` holds **0** rows. Two of its own four
frozen `full_promotion_requires` criteria are measured failures, not open questions: the CI lower
bound is `0.0000` (needs "above zero") and the point estimate is `+0.2189 pp` (needs `>= +1.0 pp`).
So the screen serves evidence and never a verdict:

- **No score, and no ranking by one.** The scanner orders by how many AMCs raised the holding — a
  count of disclosures.
- **No hit rate.** A database-wide column search for `hit_rate|win_rate|forward_return|reaction`
  finds nothing in the smart-money path. The screen ships
  "Historical market reaction: no validated study available". The computable 51.5% / 52.2%
  "naive pct positive" is a top-30 portfolio backtest over 9 dates (floor 12), 270 rows covering
  123 distinct symbols, price-return against a price-index proxy — it must never reach a screen.
- **`v_smart_money_shadow_rank` is not read.** No `point_in_time` predicate in its join, so 936 of
  2,479 symbols duplicate on 2026-10-21 with two different scores and the `rank()` window runs over
  a duplicated population; and its `shadow_score` falls back to `live_score` when the join misses
  (on 2026-10-19 all 2,480 rows carried a score with zero smart-money input).
- **`evidence_class` is not read.** It is a hardcoded literal `'A'` at
  `smart_money_scores/service.py:229` — 100% of 25,313 rows on all 16 dates. The A/B/C/D classes
  are derived in `evidenceOf()` from which sources actually answered.
- **"Not checked" ≠ "no deals".** 402 of 976 scored symbols (41.2%) were never queried;
  `trendlyne_deal_fetch_log` makes the distinction representable and the UI renders three distinct
  states (`Not checked`, `No deals`, `Net 0 · transfer`).
- **A proxy is never called accumulation.** Delivery and volume do not disclose a buyer.
- **No sector- or benchmark-relative claim.** `sector_return_pct` is NULL in 540/540 rows
  (`UNAVAILABLE`); the benchmark is a price index, not the contracted Nifty 500 TRI.
- **No confidence sparkline.** `data_confidence` is a pure function of history depth
  (`lookback_months = 3` for all rows), so a historical trend would be a warehouse artefact.
- **The shareholding leg of the sector panel is absent**, stated on screen: `total_shares` is NULL
  in every prior-quarter row, so a two-quarter value-weighted delta cannot be computed.

## 7. Not verified

- **Staging API.** The routes are **not live**: confirmed `HTTP 404` at
  `https://staging-data.niveshcopilot.com/daas/v1/desk/smart-money/breadth` with DaaS health 200
  and 170 OpenAPI paths carrying zero smart-money entries. The router file is staged on the NIDP
  VM (sha256 verified identical) and compiles there, but the process restart that would load it was
  denied. See `test_reports/OVERRIDE_smart_money_staging_api.md`.
- **The app backend and frontend are also undeployed**: the app-backend bind-mounts
  `/opt/nivesh-staging/repo/backend` (not this checkout) and the v5 frontend is served from a built
  image. Deploying either alone would put a visible tab on staging that 502s, so none was deployed.
- **No browser screenshot of the tab against real data**, for the same reason; the Playwright
  evidence is against contract-shaped mocks carrying the real figures.
- `deal_gross_inr`, `dealDays`, `deliv10d/60d` and `diiDeltaPp` are parsed and served but not yet
  surfaced in any column.

## Verdict: PASS
