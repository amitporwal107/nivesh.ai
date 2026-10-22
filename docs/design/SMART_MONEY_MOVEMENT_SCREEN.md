# Smart Money Movement — screen design (BASELINE, v2)

**Source:** `Smart Money Movement v2.html` (design-component bundle, received 2026-10-22).
**Supersedes** `Smart Money Movement.html` (v1, same day) and, before it, the dashboard
screenshot. v1 is dead — do not wire anything from it.

Screen id: **07 · Smart Money Movement**. Design system is unchanged:
`frontend-v5/design/nivesh-tokens.css` carried verbatim in the bundle (dark-first, mint primary,
Instrument Serif display / Inter Tight sans / JetBrains Mono labels). No new tokens.

Component props: `theme` (dark|light), `showShadowScore` (bool, default **false**),
`showCopilot` (bool, default true).

---

## 0. What changed from v1, and why it matters for wiring

v2 is not a restyle. It replaces a *score* screen with an *evidence* screen.

| v1 | v2 |
|---|---|
| 4 KPI cards (score-led) | 5 **feed-status strips** with freshness dots, incl. one that says a feed is down |
| "Combined FII+DII" sector rotation | "Sector rotation — **disclosed buying**", from MF + shareholding deltas × VWAP |
| Flow-regime panel | **Evidence-breadth** panel (direct+proxy / direct only / proxy only) |
| Scanner ranked by score | Scanner ranked by **evidence classes**, then scheme breadth |
| Evidence vocabulary in prose | **A / B / C / D class chips** per row, with a legend |
| — | **Evidence lanes** as tabs: Disclosed (A/B) · Proxy only (C) · All |
| — | "Evidence against & limitations" and "What would weaken this reading" per stock |
| Score shown | Score demoted behind `showShadowScore`, labelled *not validated, not used for ranking* |

Two consequences:

1. **v1's biggest blocker partly dissolves.** v1 asked for a combined FII+DII *sector* split,
   which does not exist anywhere (`fpi_sector_auc` is FPI-only). v2 instead derives sector
   rotation from disclosed MF + shareholding deltas valued at VWAP — all of which we have. That
   panel is now servable.
2. **v2 asks for things v1 did not**, chiefly delivery-vs-baseline, transfer-netted deals,
   scheme/AMC breadth and filing-freshness. Measured below: mostly available, three gaps.

## 1. Layout

```
┌ header (sticky, 60px) ─ brand · nav · search · avatar ───────────────────────────┐
├ main (flex 10, min 860px) ──────────────────┬ rail (flex 1, min 380px) ─────────┤
│ title: 07 · Smart Money Movement            │ Stock evidence panel              │
│   period [1M|3M|6M|1Y] · as-of · "not live" │   price · Follow · 5 tabs         │
│ feed-status strip row (5 cards)             │   Overview: why it surfaced ·     │
│ ┌ market-wide flows ─────────────────────┐  │     evidence chain (A/B/C/D) ·    │
│ │ regime headline · FII/DII net + 5/20/60D│ │     against · what would weaken   │
│ │ cumulative FII & DII chart (hover)     │  │   SmartMoney · Fin · Tech · News  │
│ └────────────────────────────────────────┘  │ Nivesh Copilot                    │
│ ┌ sector rotation (flex 1.6) ─┬ evidence ─┐ │   ask box + 6 suggested questions │
│ │ diverging bars · ₹Cr/%/#    │ breadth   │ │   → answer w/ source pills        │
│ └─────────────────────────────┴───────────┘ │                                   │
│ scanner: lanes · filters · A/B/C/D · legend │                                   │
├ footer ─ "Smart money is evidence, not a buy signal." + caveats ────────────────┘
```

## 2. Components and every field they need

### 2.1 Period toggle
`1M | 3M | 6M | 1Y` → trading-day windows **22 / 63 / 126 / 248**. Every panel recomputes.
Each window also implies a *disclosure* window, which is what the evidence columns actually use:

| Period | MF window (monthly) | Shareholding window (quarterly) | Deal window |
|---|---|---|---|
| 1M | Aug → Sep 26 | 1 quarter back | from 2026-09-21 |
| 3M | Jun → Sep 26 | 1 quarter back | from 2026-07-21 |
| 6M | Mar → Sep 26 | 2 quarters back | from 2026-04-21 |
| 1Y | Sep 25 → Sep 26 | 4 quarters back | from 2025-10-21 |

### 2.2 Feed-status strips (5)
Name · freshness dot (mint/amber/danger) · cadence line. Verbatim intent from the design:
NSE FII/DII cash (daily, provisional) · AMFI scheme portfolios (monthly) · Shareholding patterns
(quarterly, with **% of filings in**) · Bulk/block deals (daily, transfer-netted) · Financials
feed (**unavailable — gates unevaluable**). The screen is designed to say a feed is down. Keep
that; do not hide it.

### 2.3 Market-wide flows
Regime headline + prose · FII net cash and DII net cash (₹ Cr, delta vs previous period, and
**5D / 20D / 60D rolling sums**) · cumulative FII and DII line chart with hover tooltip (date,
FII, DII) · pill "Market-wide · not stock-specific" · footer "Historical market reaction: no
validated study available".

That last line ships verbatim. It is true (see `docs/prd/SMART_MONEY_GATE_DECISION_20261022.md`)
and it is the honest alternative to inventing a hit rate.

### 2.4 Sector rotation — disclosed buying
10 sectors, diverging bars around zero, three measures: **₹ Cr / % of total / # stocks**.
Footnote: "MF + shareholding deltas × period VWAP · estimated · 487/500 covered". Clicking a
sector filters the scanner.

### 2.5 Evidence breadth
Count of stocks with rising disclosed ownership, of N evaluated. Three tiers with bars —
**Direct + proxy agree · Direct evidence only · Proxy only, not confirmed** — plus freshness
counts **Fresh / Ageing / Stale**, and an MF coverage sentence.

### 2.6 Scanner
Filters: universe · sector · direction (All/Accumulation/Distribution) · freshness (Any/Fresh/
Ageing/Stale). Lanes as tabs: **Disclosed evidence (A/B)** · **Proxy only (C)** · **All**.
Coverage line under the tabs.

Columns: # · Stock·sector · **MF holdings Δ** (% + `n↑ m↓ · k AMCs`) · **FII/DII Δ latest filing**
(pp each + quarter pair, or a break/stale note) · **Bulk/block netted** (net shares + `legs ·
matched`) · **Delivery vs base** (% vs 60-session baseline) · **Evidence** (A/B/C/D chips +
coverage %) · **Freshness** · chevron.

Class legend, shipped verbatim:
- **A** disclosed holdings change
- **B** disclosed deal, net of transfers
- **C** market proxy, buyer unknown
- **D** direct and proxy align

Ranking: evidence classes first, then scheme breadth. **Not** by score.

### 2.7 Stock evidence panel (rail)
Name · NSE/BSE ids · Follow toggle · price + change · direction pill (Accumulation / Distribution
/ **Proxy signal**). Tabs: Overview · Smart Money · Financials · Technicals · News.

Overview carries the three sections that make this screen defensible:
- **Why it surfaced · evidence chain** — one row per class chip, each with its own source line.
- **Evidence against & limitations**
- **What would weaken this reading**

Proxy-only stocks get an explicit amber banner: "Market-proxy evidence only. This is not labelled
institutional accumulation."

### 2.8 Shadow score
Behind `showShadowScore`, dashed indigo container, labelled "Experimental score · shadow mode …
Not validated. Shown for research only; not used for ranking." This matches the gate decision:
study C is INCONCLUSIVE and stays in shadow. **Default must remain `false` in production.**

### 2.9 Footer (ship verbatim)
> Smart money is evidence, not a buy signal.
> Ownership disclosures are periodic; deal disclosures may not identify beneficial intent; market
> proxies are indirect. Always validate with fundamentals, technicals and risk management.
> Educational market intelligence, not investment advice.

---

## 3. Data contract vs. real staging coverage

Measured on staging (NIDP VM 45.64.105.224) 2026-10-22. Every row below is a query result, not
an assumption.

| v2 element | Source | Status |
|---|---|---|
| Sector rotation (MF + SHP deltas × VWAP) | `scanx_mf_holdings` + `shareholding_pattern` + `prices_eod` | ✅ **servable** — but VWAP must be derived (§3.2) |
| MF holdings Δ, schemes ↑/↓, AMC breadth, top-AMC % | `scanx_mf_holdings` (`amc`, `scheme_name`, `shares`) | ✅ 12 months Oct 25 → Sep 26; Nifty 500 coverage **500/501** |
| Bulk/block, transfer-netted | `v_trendlyne_deals_net` | ✅ 6,109 rows → 2026-10-21; 2,318 pure-transfer rows; 42 Nifty-500 names with a deal in 3M |
| Relative volume (20-session) | `prices_eod.volume` | ✅ 100% populated |
| Universe selector "Nifty 500" | `index_constituents` | ✅ 501 members, as of 2026-10-22 |
| Delivery vs 60-session baseline | `prices_eod.deliv_pct` | ⚠️ **lags one session** (§3.3) |
| FII/DII Δ latest filing | `shareholding_pattern.fii_pct/dii_pct` | ⚠️ **1M/3M only** (§3.4) |
| Classification-break detection | `shareholding_pattern` | ⚠️ **no `others` column** (§3.5) |
| 1Y MF window "Sep 25 → Sep 26" | `scanx_mf_holdings` | ⚠️ **label wrong** (§3.6) |
| Universe selector "Nifty 1000" | `index_constituents` | ⚠️ **no such index** (§3.7) |
| FII/DII net cash, rolling sums, cumulative chart | Sensibull `oxide` endpoints → `fii_dii_flows` | ✅ **resolved** — 1M/3M/6M daily, 1Y monthly (§3.1) |
| Financials tiles (P/E, P/B, interest cover, CFO/PAT) | — | 🔴 not ingested — v2 already says so on screen |

### 3.1 ✅ RESOLVED — Sensibull is the backfill (was the one blocker)

`nidp.fii_dii_flows` holds **16 NSE-sourced rows** (2026-10-09 → 10-21). NSE's
`/api/fiidiiTradeReact` is rolling and its dated archive (`fii_stats_*.xls`) 404s, so the
warehouse cannot be backfilled from NSE. That was the blocker. It is now closed.

**Sensibull (`web.sensibull.com/fii-dii-data/history`) serves the whole history**, verified live
2026-10-22. Two endpoints on `oxide.sensibull.com`, reachable with an **anonymous** token — no
login, no paid plan:

```
# 1. mint an anonymous platform token (GET; sets access_token=pa:<JWT>, aud uauth/platform_anon)
GET https://oxide.sensibull.com/v1/pluto/auth/web/session/a/platform/identify

# 2. DAILY cash + F&O OI, one month per call. NOTE the month-name format.
GET https://oxide.sensibull.com/v1/compute/cache/fii_dii_daily?year_month=2026-September

# 3. MONTHLY cash, entire history in ONE call, no params
GET https://oxide.sensibull.com/v1/compute/cache/fii_dii_cash
```
Both data calls need `Cookie: access_token=…` **and** `Origin: https://web.sensibull.com`
(omitting Origin returns `access denied`). `year_month` takes `2026-September`, not `2026-09` —
the numeric form returns `Internal Calculation Error`.

| Endpoint | Depth measured | Granularity | Fields |
|---|---|---|---|
| `fii_dii_daily` | **7 months**, `key_list` = 2026-April … 2026-October (~145 sessions) | daily | cash FII/DII buy, sell, net + **futures/options OI per index** (nifty, banknifty, finnifty, midcpnifty, niftynxt50), quantity- and amount-wise |
| `fii_dii_cash` | **98 months**, 2018-09-01 → 2026-10-01 | monthly | FII/DII buy, sell, net + nifty close and % change |

Months outside `key_list` return `Internal Calculation Error`, so daily depth is a ~7-month
rolling window, not open-ended.

**What this unblocks:**

| Period | Sessions needed | Status |
|---|---|---|
| 1M | 22 | ✅ daily, available now |
| 3M | 63 | ✅ daily, available now |
| 6M | 126 | ✅ daily, available now (~145 reachable) |
| 1Y | 248 | ⚠️ daily is ~103 sessions short — use the **monthly** series (12 points) for the 1Y cumulative chart, or accumulate ~5 more months for true daily |

5D / 20D / 60D rolling sums all fall inside the daily window. ✅

**Provenance cross-check.** Sensibull's 2026-10 monthly aggregate and ScanX/Dhan's independently
retrieved `LATEST.MONTHLY` agree to within **₹0.0002 Cr on a ₹48,895 Cr figure** (FII net
−48,895.330078 vs −48,895.330017; DII net +52,983.639648 vs +52,983.639526) — the gap is float32
vs float64, not a data difference. Two unrelated aggregators carrying identical values is good
evidence both are passing through NSE's published numbers unmodified.

**Ingest shape.** One call gets all 98 monthly points; six more get Apr–Oct 2026 daily. So the
entire backfill is **~8 HTTP requests**, not months of accumulation. Record `source`,
`as_of_date`, retrieval time and provenance per row, and make the job idempotent so repeat runs
do not duplicate observations. Keep the existing NSE rows distinguishable by `source` rather than
overwriting them — the overlap is a free daily reconciliation check.

**Caveat, same as ScanX.** This is a third-party aggregator's internal app state, not a
documented API; it can change shape without notice, and the anonymous token is an undocumented
affordance. Check terms of use before relying on it commercially, and keep provenance recorded.

### 3.2 VWAP must be derived — `avg_price` is empty
`prices_eod.avg_price` is populated on **0 of 220,507** rows in the last 90 days.
`turnover` is populated on **220,507 of 220,507**, and `turnover > 0 AND volume > 0` on
**100.0%** of them. So period VWAP = `sum(turnover) / sum(volume)` over the window. Servable —
but anything reading `avg_price` will silently produce nulls.

### 3.3 Delivery % lags one session
| Session | Rows | `deliv_pct` populated |
|---|---|---|
| 2026-10-21 | 3,708 | **0** |
| 2026-10-19 | 3,668 | 3,254 |
| 2026-10-16 | 3,675 | 3,253 |

Delivery arrives a session late and covers ~88.6% of symbols when it does. The scanner's
"Delivery vs base" column must read **the latest session that has delivery data**, and the panel's
as-of date for that column differs from the price as-of date. Do not join on the latest price
session — it yields an empty column.

### 3.4 Ownership deltas work for 1M/3M only
Filings per period, and Nifty-500 coverage:

| Period end | Symbols filed (all) | Of Nifty 500 |
|---|---|---|
| 2026-09-30 | 1,991 | 420 / 501 (**83.8%**) |
| 2026-06-30 | 1,207 | 336 / 501 (67.1%) |
| 2026-03-31 | 193 | — |
| 2025-12-31 | 169 | — |
| 2025-09-30 | 165 | — |

A delta needs two consecutive filings. Jun → Sep 2026 gives ~336 Nifty-500 names, which serves
**1M and 3M**. The 6M window needs Mar 2026 and the 1Y window needs Sep 2025 — both have ~165–193
symbols *in total*, so the column is effectively empty there. **For 6M/1Y, show the column as
unavailable rather than computing a delta against a near-empty quarter.**

The feed strip's "Sep 26 filings 62% in" is computable — currently **83.8%** of Nifty 500.

### 3.5 Classification-break detection needs a definition
v2 withholds an FII change when a filing spans a reclassification (the Tega case: FII falls >10 pp
while "Others" rises by about as much). `shareholding_pattern` carries `fii_pct, dii_pct, mf_pct,
insurance_pct, bank_fi_pct, govt_holding_pct, public_pct, individual_pct, nri_pct,
bodies_corporate_pct` — but **no explicit `others_pct`**. The rule must be written against
`public_pct` / `bodies_corporate_pct`, or a residual computed as `100 − sum(known buckets)`.
This is a definition to agree, not a data gap. Until agreed, do not ship the break badge.

### 3.6 The 1Y MF window label is wrong by one month
`scanx_mf_holdings` spans **2025-10-01 → 2026-09-01** (12 months, 11 month-steps). v2 labels the
1Y MF window "Sep 25 → Sep 26", which would need Sep 2025. Relabel **"Oct 25 → Sep 26"**.

### 3.7 "Nifty 1000" does not exist
The universe selector offers Nifty 500 / Nifty 1000 / All liquid NSE / My watchlist.
`index_constituents` has: Nifty Total Market **756**, Nifty 500 **501**, Nifty Smallcap 250,
Nifty 200, Nifty Midcap 150, Nifty 100, Nifty 50. There is no 1,000-name index. Either relabel
the option **"Nifty Total Market (756)"** or drop it.

### 3.8 Global MF→price mapping is loose, but not for Nifty 500
Of 3,950 symbols in the Sep-2026 MF data, **2,457 have no price row** on 2026-10-21 (unlisted,
debt, delisted, non-equity holdings). Within Nifty 500 the picture is clean (500/501 have MF
data). So the scanner's "unmapped ISIN" count must be computed **inside the selected universe** —
a global count would read ~2,457 and be meaningless.

---

## 4. Wiring rules that apply (standing)

Carried forward from the one-screen copilot design decisions; unchanged by v2:

1. **Reuse the v5 tools** — do not add a parallel data path for this screen.
2. **One data source per tool**, named on screen. Every v2 panel already has a source line; keep
   them bound to the actual table, not to a provider's marketing name.
3. **Brokers are read-only** here. This screen never places an order.
4. **Icons sit beside names**, not replacing them.
5. **Report gaps on screen.** v2 is built for this — the fifth feed strip exists to say a feed is
   down, proxy-only names get an amber banner, and unavailable tiles say "Feed not ingested".
   Honour it: no silent zeros, no interpolation, no "—" standing in for an untested claim.
6. **`showShadowScore` stays `false`** until a study passes its gate. Today the paired B-vs-C
   evaluation is INCONCLUSIVE.

## 5. Build order implied by the above

1. Sector rotation, MF holdings Δ, deal netting, relative volume, evidence classes/lanes,
   stock evidence panel — all servable now.
2. Delivery column with the one-session lag rule (§3.3).
3. Ownership-delta column, 1M/3M only, with 6M/1Y showing unavailable (§3.4).
4. Agree the classification-break rule (§3.5), then ship the badge.
5. Fix the three labels (§3.6, §3.7) — trivial, but they are factual claims on screen.
6. **Backfill `fii_dii_flows` from Sensibull** (§3.1) — ~8 requests gets 98 monthly points
   (2018-09 →) and 7 months of daily. Build it as an idempotent service that keeps `source`
   distinct from the existing NSE rows, so the overlap stays a daily reconciliation check. The
   flows panel then ships with 1M/3M/6M on daily data and 1Y on monthly; only a true 248-session
   daily 1Y still needs ~5 months of accumulation.
