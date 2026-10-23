# Smart Money Movement — screen design (BASELINE, v2)

**Source:** `Smart Money Movement v2.html` (design-component bundle, received 2026-10-22).
**Supersedes** `Smart Money Movement.html` (v1, same day) and, before it, the dashboard
screenshot. v1 is dead — do not wire anything from it.

**Where the screen itself now lives** (committed 2026-10-22 from the design-project export
`Smart Money Movement Dashboard.zip`; the zip is gitignored by `**/*.zip`, so its contents were
extracted into the repo):

| Path | What |
|---|---|
| `frontend-v5/design/smart-money/Smart Money Movement v2.dc.html` | **the v2 screen** — template + logic, as exported |
| `frontend-v5/design/Smart Money Movement v2 · offline.html` | the one-file review copy (open it directly) |
| `frontend-v5/design/smart-money/screenshots/smart-money-movement-v2.png` | v2 rendered |
| `frontend-v5/design/smart-money/screenshots/smart-money-movement-v1.png` | v1 rendered, for the §0 comparison |
| `frontend-v5/design/smart-money/Smart Money Movement v1 · offline.html` | v1, openable — **dead**, for the §0 comparison only |
| `frontend-v5/design/smart-money/Smart Money Movement.dc.html` | v1 source — **dead**, kept only as provenance |
| `frontend-v5/design/smart-money/support.js` | the runtime the `.dc.html` head loads |
| `frontend-v5/design/_ds/nivesh-copilot-design-system-21f53176-…/` | the design system the helmet links |

Until this landed, §0–§2 below specified a file that was in no branch and on no disk — the same
failure the charting screen hit (`frontend-v5/design/README.md` → "a screen built from §38 alone
will drift on composition"). §0–§2 own *behaviour and fields*; the `.dc.html` owns *composition* —
bar heights, what is a headline, what is a pill, how dense each panel is. Build from both.

Two things the export settled, worth recording because they were previously assumptions:
`_ds/…/colors_and_type.css` is **byte-identical** to the committed
`frontend-v5/design/nivesh-copilot/colors_and_type.css` (sha256 `6210c9ed…`), so v2 introduces no
new tokens; and its `_ds` id is the **same** one the existing `nivesh-copilot/*.dc.html` files
already reference, so committing that tree makes those files resolve their stylesheet and bundle
for the first time too.

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
| Delivery vs 60-session baseline | `prices_eod.deliv_pct` | ✅ servable — **resolve the as-of date**, the lag is transient (§3.3) |
| FII/DII Δ latest filing | `shareholding_pattern.fii_pct/dii_pct` | 🔴 **49 of 501 names, at every window** (§3.4) |
| Classification-break detection | `shareholding_pattern` | 🔴 **not earnable from this table** (§3.5) |
| 1Y MF window "Sep 25 → Sep 26" | `scanx_mf_holdings` | ⚠️ **label wrong** (§3.6) |
| Universe selector "Nifty 1000" | `index_constituents` | ⚠️ **no such index**; Total Market is **755** (§3.7) |
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

### 3.1b Four rules the flows panel must obey (measured post-ingest)

The backfill landed (`SENSIBULL` 2,070 rows / 138 sessions, `SENSIBULL_MONTHLY` 196 / 98 months,
`NSE_FII_DII` 16 preserved). Reconciliation against the real rows produced four hard rules.

**1. Never aggregate across grains — it double-counts by exactly 2×.** The monthly series is the
*exact* aggregate of the same daily universe. Across all 7 overlap months, `sum(daily)` minus
`monthly` is **0.00 to the paisa** for both FII and DII. Excellent internal validation of the
source; also means any `sum()` spanning `SENSIBULL` and `SENSIBULL_MONTHLY` returns a
plausible-looking number that is twice the truth.

**2. Grain must come from `source`, never from `as_of_date` being the 1st.** Within the daily
window **5 real trading sessions fall on a month-start** — 2026-04-01, 06-01, 07-01, 09-01,
10-01. A day-1 heuristic misclassifies 10 legitimate daily rows. This is also why monthly needed
its own `source` value: sharing `source='SENSIBULL'` would have made those 10 rows **collide on
the primary key and silently overwrite each other**. Convention: a `%_MONTHLY` suffix, matched
with a literal `LIKE '%\_MONTHLY'` so a source named `XMONTHLY` is not caught.

**3. Any cross-source comparison needs a grain guard.** A plain self-join on
`(as_of_date, category, segment)` pairs a daily row against a monthly one and reports **10 false
disagreements** — e.g. 2026-04-01 DII daily 7,171.80 vs monthly 51,063.87. Add
`AND b.grain = a.grain`.

**4. The newest monthly point is an incomplete month-to-date.** 2026-10-01 holds only **13
elapsed sessions** and keeps growing, but sits in the series looking like a closed month. The 1Y
chart must flag or exclude it, never render it as a finished bar.

Agreement, for the record: NSE vs Sensibull on all 16 overlapping observations **AGREE**, worst
absolute difference **0.0011 Cr**, worst relative **5.2e-7 %**. Judge agreement with a tolerance
(an absolute floor is mandatory because net flows cross zero, where a purely relative test is
meaningless), not exact equality.

Two things stay unreconciled and should be labelled provisional on screen: the **F&O segments**
(index futures/options, per-index, and the `PRO`/`CLIENT` categories) are single-sourced from
Sensibull, and **monthly history before 2025-10-01 cannot be session-gap-checked** because the
`prices_eod` calendar does not reach back that far.

### 3.2 VWAP must be derived — `avg_price` is empty
`prices_eod.avg_price` is populated on **0 of 220,507** rows in the last 90 days.
`turnover` is populated on **220,507 of 220,507**, and `turnover > 0 AND volume > 0` on
**100.0%** of them. So period VWAP = `sum(turnover) / sum(volume)` over the window. Servable —
but anything reading `avg_price` will silently produce nulls. `turnover` is in **rupees**, not
lakhs (360ONE VWAP ₹1,117.70 against a ₹1,210 last close), so no unit scaling.

Two conditions on that aggregate, both measured:

- **`WHERE series IN ('EQ','BE')` is mandatory** — see §3.9. Without it four Nifty-500 members
  double-count.
- **Return `sessions_used` alongside the VWAP.** A 63-session query returns as few as **20**
  sessions for a recent listing (`HEGAM`), and a VWAP-weighted sector rotation that treats a
  20-session average as a 63-session one mis-weights new IPOs. Let the UI mark short windows.

### 3.3 Delivery % is complete — but its as-of date must be resolved, not assumed
v1 of this section said delivery "lags one session" and covers ~88.6% of symbols. **Both were
wrong**, and re-measuring today says so:

```
 sessions_total | sessions_delivery_missing
----------------+---------------------------
            259 |                         0
```

**Not one session in 259** (2025-10-01 → 2026-10-21) lacks delivery data. The session that read
zero was caught mid-ingest: the day's price rows land before its delivery file, and it backfills
within the day. That is an **intraday ordering artifact, not a standing offset**. The 88.6% figure
was an artifact of counting all 55 `series` values; within `EQ`+`BE` the real fill is **92.0–92.4%**,
stable across recent sessions.

The guard v1 proposed is still right, for a different reason. The column must **resolve** its
as-of date — the latest session whose delivery fill is ≥50% of its rows — rather than assume
either the latest price session or a fixed one-session offset. On most renders that resolves to
the *same* date as the price as-of date, so **the UI must print the resolved date and must not
hardcode "delivery is one day behind."**

Baseline convention, to be stated on screen: the 60 sessions **strictly before** the resolved
delivery session, requiring ≥20 observations (which suppresses new listings whose baseline is too
thin to mean anything). 493 of 501 Nifty-500 names clear that bar. A mean baseline is sensitive to
spikes — the top hit, SIGNATURE at 68.22% against an 11.72% baseline, is real (413,403 of 606,014
shares) but would be muted by a median. Either is defensible; pick one and label it.

### 3.4 🔴 Ownership deltas are limited by breadth, not by window — 49 of 501
v1 of this section said Jun → Sep 2026 gives "~336 Nifty-500 names, which serves 1M and 3M" and
that 6M/1Y should show the column as unavailable. **That is wrong by roughly 7×, and inverted.**
The filing counts were right; reading them as deltas was not.

```
 period_end |   source    | rows | fii_pop
------------+-------------+------+---------
 2026-09-30 | NSE_SHP     | 1972 |    1722
 2026-09-30 | screener_in |  122 |     118
 2026-06-30 | NSE_SHP     | 1117 |       0     <-- rows, but no institutions
 2026-06-30 | screener_in |  173 |     167
 2026-03-31 | NSE_SHP     |   22 |       0     <-- same
 2026-03-31 | screener_in |  172 |     167
 2025-12-31 | screener_in |  169 |     164
 2025-09-30 | screener_in |  165 |     160
```

**`NSE_SHP` carries `fii_pct`/`dii_pct` for the 2026-09-30 quarter only.** Every earlier NSE_SHP
quarter has filings but NULL institutional columns. So 259 of the 336 Jun-2026 filings cannot
produce a delta at all, and the only source with an institutional *history* is `screener_in`,
whose panel is 194 symbols in total.

Same-source Nifty-500 FII deltas, by window:

| Window | Prior → anchor | Deltas available |
|---|---|---|
| 1M / 3M | 2026-06-30 → 2026-09-30 | **49** / 501 (9.8%) |
| 6M | 2026-03-31 → 2026-09-30 | **49** |
| 1Y | 2025-09-30 → 2026-09-30 | **48** |

Verified directly: the Jun→Sep same-source count is `49`. The number is **flat across every
window** because the one source with history is deep, so the spec had it exactly backwards —
it kept the column where it is thinnest and dropped it where it is just as good.

**`PARTITION BY symbol, source` is not optional.** The two sources disagree on the same quarter —
the first cross-source query I ran fabricated the largest move in the table:

```
  symbol   | from_period | to_period  | prev_fii | fii   | delta_pp | source_changed
-----------+-------------+------------+----------+-------+----------+----------------
 ICICIBANK | 2026-06-30  | 2026-09-30 |  33.79   | 50.44 |  +16.65  | t
```

ICICIBANK's Sep-2026 `fii_pct` is 50.44 in NSE_SHP and 34.68 in screener_in — **15.76 pp apart**.
A dedup that picks NSE_SHP for Sep and screener_in for Jun invents 16.65 pp of FII buying in
India's second-largest bank. Across the 98 overlapping rows the mean absolute difference is
0.27 pp but the max is 15.76 pp: **good enough to display a level, never good enough to difference
across sources.**

**What the screen should do:** show the FII/DII **level + filing date for the 420 Nifty-500 names
that filed for Sep-26** (83.8%, confirmed), and the **Δ only for the 49**, with an explicit
"Δ unavailable — no comparable prior filing" state for the other 371. Do not drop the Δ at 6M/1Y.
Until NSE_SHP backfills institutional columns for 2026-06-30 and earlier, the Δ column cannot
exceed ~49 Nifty-500 names at any window. That is the real gap, and it is larger than v1 thought.

### 3.5 🔴 The classification-break badge cannot be earned from this table — ship a withhold state
v1 proposed writing the rule against `public_pct` / `bodies_corporate_pct`, or a residual of
`100 − sum(known buckets)`, citing Tega (FII falls >10 pp while "Others" rises by about as much).
Three measurements dismantle that plan.

**1. Two of the named columns are not data.** `bodies_corporate_pct`, `insurance_pct` and
`govt_holding_pct` are populated on **0 of 5,124 rows**, in both sources. A rule written against
`bodies_corporate_pct` would never fire.

**2. The cited example is not in the warehouse.** `TEGA` has **exactly one filing** (2026-09-30,
NSE_SHP). There is no Mar-2026 or Jun-2026 row, so the canonical case cannot be reproduced here —
it was presumably seen in a provider UI. The rule was designed against an example this table
cannot show, which is why it came out unsound.

**3. The residual rule is algebraically circular.** A source-agnostic residual does work as a
*level*: `others_pct = 100 − promoter_pct − fii_pct − dii_pct` reproduces screener_in's own
`public_pct` to 0.317 pp mean absolute error and NSE_SHP's `public_pct − fii_pct − dii_pct` to
0.084 pp — one formula, both sources, despite their incompatible `public_pct` definitions (§3.9).
But as a *delta* it carries no information. Across all 1,501 same-source transitions,
`Δpromoter + Δfii + Δdii + Δothers = 0` with max absolute error **0.0000**. That is forced by the
definition, not an empirical finding. So "FII fell while another bucket rose by about as much" is
a restatement of "promoter and DII did not absorb the FII move" — it would fire on every genuine
FII sale to retail.

**Classify comparability, not reclassification.** When FII moves, the question is where it went.
Absorbed by DII is institutional rotation; absorbed by promoter is a separately discloseable
promoter action; absorbed by the residual is **either a real retail/HNI sale or a reclassification,
and this table cannot tell them apart.** So emit a verdict on whether the Δ is quotable:

- `COMPARABLE` → show the Δ.
- `STRUCTURAL_PROMOTER_CHANGE` (|Δpromoter| ≥ 10 pp) → withhold; say "promoter holding changed by
  N pp this quarter; institutional Δ not comparable."
- `AMBIGUOUS_UNATTRIBUTED` → withhold; say "FII change not attributable to a named counterparty in
  this filing." **Never the word "reclassification"** — we have evidence of ambiguity, not of one.

On 232 evaluable transitions this flags **2 (0.9%)**: RBLBANK → `STRUCTURAL` (Δpromoter +60.00 pp,
a real control event) and HFCL → `AMBIGUOUS`. It correctly leaves FEDFINA `COMPARABLE` (+8.64 FII
absorbed −7.93 by DII — an attributable rotation).

**False-positive risk is high and currently unresolvable.** The thresholds are judgement calls with
no labelled set to fit against; the one flag is unverifiable (HFCL's FII went 7.08 → 15.74 → 17.24
with promoter pinned — a large FPI allotment and a reclassification look identical here); and the
corroborating check is **not computable where the rule runs**, because `total_shares` is populated
on 0 of 1,987 `screener_in` rows and screener_in is the only source with prior-quarter
institutions. Note also that screener_in has its own taxonomy break — ICICIBANK's `public_pct`
jumps 9.13 → 25.36 between Dec-25 and Mar-26 — so any window reaching past 2026-03-31 needs its
own guard.

**Sharper than v1's "until agreed, do not ship the break badge": the badge can never be earned
from `shareholding_pattern` alone, whatever rule is agreed.** It needs an out-of-band corroborator
(`total_shares` backfilled into screener_in, or a deal cross-check against `v_trendlyne_deals_net`).
The withhold state is shippable today.

### 3.6 The 1Y MF window label is wrong by one month
`scanx_mf_holdings` spans **2025-10-01 → 2026-09-01** (12 months, 11 month-steps). v2 labels the
1Y MF window "Sep 25 → Sep 26", which would need Sep 2025. Relabel **"Oct 25 → Sep 26"**.

### 3.7 "Nifty 1000" does not exist
The universe selector offers Nifty 500 / Nifty 1000 / All liquid NSE / My watchlist.
`index_constituents` carries **27** indices at the 2026-10-22 snapshot, the largest being Nifty
Total Market **755**, then Nifty 500 **501**, Nifty Smallcap 250, Nifty 200, Nifty Midcap 150,
Nifty 100, Nifty 50. There is no 1,000-name index. Either relabel the option
**"Nifty Total Market (755)"** or drop it.

**755, not 756** — v1 said 756. Verified not a dedup artifact: 755 raw rows, 755 distinct symbols,
0 duplicates, and 755 on each of the last four snapshots. Shipping "756" on screen would be a
false factual claim, which is the one thing this section exists to prevent.

Bonus for §2.4's sector rotation: **21 sector indices** already sit in `index_constituents` at the
same snapshot date, so the sector grouping does not need `sector_master`, which is sparse.

### 3.8 Global MF→price mapping is loose, but not for Nifty 500
Of 3,950 symbols in the Sep-2026 MF data, **2,457 have no price row** on 2026-10-21 (unlisted,
debt, delisted, non-equity holdings). Within Nifty 500 the picture is clean (500/501 have MF
data). So the scanner's "unmapped ISIN" count must be computed **inside the selected universe** —
a global count would read ~2,457 and be meaningless.

### 3.9 Two cross-cutting traps that corrupt the aggregates silently
Neither was in v1; both break more than one panel.

**`prices_eod` has duplicate `symbol` + `as_of_date` rows across `series`.** The latest session
carries **55 distinct series** (EQ 2,694, SM 393, BE 222, ST 83, plus GS/GB/TB/N\*/Y\*). Four
Nifty-500 members — ABCAPITAL, ADANIENSOL, CRAFTSMAN, SHRIPISTON — have both a `BL` and an `EQ`
row on 2026-10-21, so any VWAP, delivery or volume aggregate double-counts them. **Filter
`series IN ('EQ','BE')`**, which leaves 0 duplicate symbol-date pairs. Consequences to accept:
BAGMANE, BIRET and EMBASSY trade only in series `RR` (REIT/InvIT) and drop out — add `'RR'` if
REITs belong in the universe, still 0 duplicates — and `DUMMYHEG` has **0 price rows anywhere**,
a corporate-action placeholder, which is also why Nifty 500 reports 501 members.

**`shareholding_pattern`'s two sources define `public_pct` incompatibly.**

```
   source    |  n   | promoter+public ≈ 100 | promoter+fii+dii+public ≈ 100
-------------+------+-----------------------+-------------------------------
 NSE_SHP     | 1561 |                  1524 |                           290
 screener_in | 1667 |                   270 |                          1627
```

NSE_SHP's `public_pct` is **total** public, institutions included; screener_in's **excludes** them.
The definitions differ by ~17 pp on average, so `public_pct` must never be compared or differenced
across sources. Also: **187 symbol+period pairs carry one row per source**, so dedup is mandatory
(`row_number() OVER (PARTITION BY symbol, period_end, source ORDER BY ingested_at DESC)`); and
`individual_pct = promoter_pct` on **381 of 1,595** NSE_SHP rows (24%), a parsing artifact — do
not use `individual_pct`.

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
