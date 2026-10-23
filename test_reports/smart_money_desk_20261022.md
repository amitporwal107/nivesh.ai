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
...................                                                      [100%]
19 passed, 1 warning in 0.96s
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
$ npx tsc --noEmit -p tsconfig.json                        -> TSC_EXIT=0
$ npx playwright test --config pw.copilot-app.config.ts e2e/tests/copilot-app-desk-smart-money.spec.ts
21 passed (16.2s)
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
$ npx playwright test ... copilot-app-desk.spec.ts copilot-app-desk-market.spec.ts copilot-app-screens.spec.ts
74 passed (1.6m)
```
The typecheck was clean before the change too, so the exit 0 is attributable.

## 5b. Built to the v2 design, and where it could not be

The first cut of this tab was built from the spec's §3 data tables and the desk's existing component
vocabulary; it did not implement §1's layout. That was a real miss and the screen was rebuilt against
the design. It now carries the period toggle, the five feed-status strips, the regime line, the
cumulative FII/DII chart, diverging sector bars with three measures, the three breadth tiers, the
scanner's lanes/filters/legend, and the stock-evidence panel with its evidence chain and
falsification list.

Three controls could not be built as drawn, each because the warehouse cannot back them. In every
case the screen states the limit rather than serving a plausible wrong answer:

| Design asks for | Measured reality | What ships |
|---|---|---|
| Period toggle recomputes every panel | `mf_holdings_deltas` has only a **1-month** pair (200,160 rows / 4,189 ISINs). The 4- and 5-month pairs cover 103 and 93 ISINs. There is no 3-, 6- or 12-month pair. | All four chips work. Flows, deals, delivery and shareholding do recompute. The MF leg uses the widest-coverage pair and the API returns `mf_window {requested, actual, exact}`; the UI prints "Holdings change is over 1 month — a 3-month disclosure pair is not published." Honouring 6M with the 5-month pair would have collapsed the scanner from 4,189 names to 93. |
| Universe "Nifty 1000" | No such NSE index and no such list in `index_constituents`. Real lists: Total Market 755, Nifty 500 501, Smallcap 250, Nifty 200, Midcap 150, Nifty 100, Nifty 50. | Offered under real names; **Nifty Total Market** replaces "Nifty 1000". A request for `nifty1000` is a 400. |
| Evidence column = "A/B/C/D chips + coverage %" | `coverage_pct` is **100.00 on every one of the 976 rows** (min = max) — a second constant-as-measurement, alongside `evidence_class`. | Chips only; the coverage % is dropped and `freshness`, which has real variance (963 fresh / 8 ageing / 5 stale), takes the column. |

The A/B/C/D lanes are real but universe-dependent, which the lane counts now make visible:

```
 universe             |  A  | B |  C  | D
----------------------+-----+---+-----+----
 Nifty 500            | 458 | 0 |   0 | 42
 Nifty Total Market   | 569 | 7 | 114 | 60
```
In Nifty 500 the proxy lane is legitimately empty — every name there has a disclosed MF delta — so
the tab prints "no name in this universe rests on a proxy alone" rather than an unexplained blank.

### The chart's palette was validated, not chosen by eye
Two series, one axis (both are ₹ crore; a second scale would be a lie). Colours are new
`--sm-fii` / `--sm-dii` tokens, run through the palette validator against the real `.cp-card`
surface in each theme. Dark is re-stepped rather than flipped, because the light pair sits above the
dark lightness band:

| Mode | FII | DII | Surface | Result |
|---|---|---|---|---|
| light | `#4F58D6` | `#B86A12` | `#FFFFFF` | PASS — CVD ΔE 29.5 protan / 25.0 tritan, normal-vision 31.9, contrast ≥3:1 |
| dark | `#7C86F0` | `#CE7F12` | `#0A0E1A` | PASS — CVD ΔE 28.4 protan / 22.7 tritan, normal-vision 28.9, contrast ≥3:1 |

A legend is always present, both series carry direct end-labels, the hover readout is `aria-live`,
and a "Show as a table" disclosure gives the same numbers without the plot.

### The rail could not sit beside the main column, and says so
The design's §1 wants 860px main + 380px rail = 1240px. This tab's column, measured in the browser
with the desk's Copilot docked, is **888px at a 1600px viewport and 1076px at 2200px** — the desk
shell caps it. So the stock-evidence panel stacks under the scanner instead of splitting the column.
Forcing the split would leave the scanner (seven columns) scrolling sideways in ~670px, and the
scanner is the part of this screen that most needs the width. `useRoomFor(1240)` measures the real
container, so the split engages by itself if the desk ever grants the room. The design's duplicate
Copilot was dropped: the desk already docks one, and the panel's "Ask the Copilot" button calls the
desk's own `askDesk`.

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
- **The router staged on the NIDP VM has been refreshed** and now matches the committed file
  (sha256 `6513d8c8d97930087f5260c30c944e8b` on both sides, `REMOTE_PY_COMPILE_OK`, 5 routes,
  registrations intact). It was briefly stale while SSH to the host was refused
  (`kex_exchange_identification: Connection reset by peer`, most likely fail2ban after earlier
  failed key-auth probes); the ban expired. A restart now loads the correct router, though
  deploying from the branch is still preferable — see the override.
- **Migration 181 is now committed.** `nidp.trendlyne_deal_fetch_log` is read by four files already
  merged into dev (the deal ingest from `5f7e83c4`, this scanner, and two tests) while the migration
  creating it was untracked, so dev could not be built from scratch. Verified against staging where
  it is already applied: seven columns matching the DDL by name, type and nullability, both indexes,
  578 rows (561 `OK`, 17 `EMPTY`). Those 17 are what the scanner's "Not checked" state depends on.
- Screenshots were read at 1600px, 2200px and 390px to check layout, and three defects found that
  way were fixed (a crushed main column, a clipped Evidence column, a clipped Freshness column). The
  captures were scratch and are not committed.
- `deal_gross_inr`, `dealDays` and `deliv10d/60d` are parsed and served; the first is not yet
  surfaced in any column.
- The design's §2.7 rail tabs (Smart Money · Financials · Technicals · News) are not built: only the
  Overview tab's three sections are, which are the ones the disclosed data supports.
- §2.8's shadow-score container is deliberately not built. `showShadowScore` would have to default
  false and the gate has not passed, so the component would be dead code that invites being turned
  on.

## Verdict: PASS
