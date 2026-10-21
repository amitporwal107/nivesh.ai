# Smart Money Movement — screen design (BASELINE)

Supersedes the earlier dashboard screenshot. Source: `Smart Money Movement.html`
(design-component bundle, received 2026-10-22). Screen id in the design: **07 · Smart Money
Movement**; subtitle `NSE · BSE · AMFI · Shareholding disclosures`.

Design system: `frontend-v5/design/nivesh-tokens.css` (dark-first, mint primary, Instrument
Serif display / Inter Tight sans / JetBrains Mono labels). The bundle carries the V5 token
file verbatim — no new tokens are introduced.

---

## 1. Layout

```
┌ header (sticky, 60px) ─ brand · nav · search · bell · settings · avatar ─────────┐
├ main (flex 10, min 860px) ──────────────────┬ rail (flex 1, min 380px) ─────────┤
│ title row: 07 · Smart Money Movement        │ Nivesh Copilot                    │
│   period toggle [1M|3M|6M|1Y] · as-of date  │   ask box + suggested questions   │
│ KPI row (4 cards, auto-fit minmax(200px))   │   → answer w/ source pills        │
│ ┌ sector rotation (flex 2) ─┬ flow regime ─┐│ Stock detail                      │
│ │ ranked bars / diverging   │ cumulative   ││   price · follow · 5 tabs         │
│ │ view: ₹Cr / % / #stocks   │ FII+DII lines││   Overview·SmartMoney·Fin·Tech·News│
│ └───────────────────────────┴──────────────┘│                                   │
│ stock-level smart money scanner (table)     │                                   │
├ footer ─ "Smart money is evidence, not a buy signal." + caveats ────────────────┘
```

Props on the design component: `theme` (dark|light), `sectorChart` (bars|diverging),
`showCopilot` (bool).

## 2. Components and every field they need

### 2.1 Period toggle
`1M | 3M | 6M | 1Y` → trading-day windows 22 / 63 / 126 / 248. Every panel below is
recomputed for the selected window, and each KPI shows a delta "vs previous <window>".

### 2.2 KPI row (4 cards)
| Card | Fields |
|---|---|
| FII Net Flow (Cash) | `₹<n> Cr`, `↑/↓ <pct>%` vs prev window, 12-bucket signed sparkline |
| DII Net Flow (Cash) | same shape |
| Mutual Fund Accumulation | `<pct>% Rising`, caption "of tracked stocks … (<window>)", area sparkline |
| Stocks with rising institutional ownership | `<n>` of 500, `↑/↓ <pct>%` vs prev, 12-bucket sparkline |

### 2.3 Sector rotation
Ten sectors, split into net-buying (mint) and net-selling (danger) groups, ranked by
magnitude. Two layouts (`sectorChart` prop): ranked bars, or diverging bars around a zero
axis. Three measures (`View by`): **Net Flow (₹ Cr)** · **% of Total** (share of gross
institutional flow) · **No. of Stocks**. Clicking a sector filters the scanner; the panel
footer shows the active filter with a Clear action.

### 2.4 Flow regime
Regime label (e.g. "Selective **accumulation**"), one-line sub, confidence pill
(Low / Moderate / High), two cumulative lines (FII mint, DII indigo) over the window with a
crosshair tooltip (date · FII · DII, cumulative ₹Cr), y-axis ticks with a dashed zero line,
6 x-ticks, and a prose summary.

### 2.5 Stock-level smart money scanner
Columns: `#` · Stock (name + NSE symbol) · Sector · **MF holdings Δ (3M)** + `(n schemes)` ·
**FII / DII ownership Δ (QoQ)** · **Bulk / block activity (3M)** + share count ·
**Delivery vs avg (3M)** `<pct>% (vs <pct>%)` · **Accumulation score** 0–100 with bar ·
**Evidence** pill.

Controls: universe select (Nifty 500 / 200 / Midcap 150 / Smallcap 250), sector select,
Filters popover (Evidence: All | Direct only; Min. accumulation score: Any | 60+ | 70+),
match count, empty state with Clear filters.

Evidence vocabulary — **Direct evidence** / **Direct + proxy** / **Proxy only** (mint for the
first two, amber for proxy-only). Score colour: ≥70 mint, ≥50 amber, else danger.

### 2.6 Stock detail (rail)
Header: full name, `NSE: <sym> | BSE: <code>`, last price + change (abs and %), Follow
toggle, NSE deep link. Five tabs:
- **Overview** — "Why it surfaced" (3 numbered reasons), Accumulation score `/100`,
  Evidence pill, "Data freshness: MF: <month> · FII/DII: <quarter>".
- **Smart Money** — FII ownership `a% → b%` (+Δ PP · QOQ), DII ownership, MF holdings Δ
  (n schemes · 3M), Bulk/block deals (shares · 3M), Delivery vs avg (Δ pts · 3M).
- **Financials** — Revenue TTM, Revenue growth YoY, ROE, P/E.
- **Technicals** — RSI 14D (+ overbought/oversold/neutral), vs 50-DMA, vs 200-DMA,
  52-week range position.
- **News** — dated exchange/AMFI disclosures with source line.

### 2.7 Copilot rail
Ask box; five suggested questions (sector buying, rising MF holdings, why IT is being sold,
FII vs DII comparison, what explains the flow reversal); routed answer with a serif headline,
prose, and source pills. The header search box also routes into the Copilot on Enter.

### 2.8 Footer disclaimer (ship verbatim)
> Smart money is evidence, not a buy signal. Ownership disclosures are periodic; deal
> disclosures may not identify beneficial intent; market proxies are indirect. Always
> validate with fundamentals, technicals and risk management.

---

## 3. Data contract vs. real staging coverage

Measured on staging NIDP 2026-10-22 (counts and ranges are live `count(*)`/`min`/`max`).

| Screen field | Source | Coverage on staging | Verdict |
|---|---|---|---|
| FII/DII net flow (cash), 1M–1Y + sparkline + cumulative chart | `nidp.fii_dii_flows` (segment=cash) | **16 rows, 2026-10-09 → 2026-10-21** (~8 sessions) | 🔴 **BLOCKED** — cannot serve 1M (22d) let alone 1Y (248d) |
| MF accumulation % rising | `v_mf_accumulation_breadth` over `mf_holdings_deltas` | 1,780,881 rows, 2025-09 → 2026-09 (13 monthly deltas) | 🟢 servable for all four windows |
| Stocks with rising institutional ownership (of 500) | `trendlyne_ownership.insti_chg_qoq_pct` | 2,479 symbols but only **3 snapshot dates** (2026-10-16 → 21) | 🟡 current value yes; **no "vs previous window" delta** |
| | `shareholding_pattern` | 978 symbols have both 2026-06-30 and 2026-09-30 → QoQ computable | 🟡 quarterly only |
| Sector rotation, net institutional flow by sector | `fpi_sector_auc.net_inv_inr_cr` | 2,592 rows, 23 sectors, 9 fortnightly reports 2026-05-31 → 2026-09-30 | 🟡 **foreign (FPI) only, fortnightly, 5 months** — no DII sector split exists |
| Scanner: MF holdings Δ 3M + scheme count | `smart_money_scores_daily` (`net_shares_pct`, `schemes_increasing`, `amcs_increasing`) | 25,313 rows, 2025-11-12 → 2026-10-21 | 🟢 |
| Scanner: FII / DII ownership Δ QoQ | `trendlyne_ownership` (`fii_chg_qoq_pct`, `insti_chg_qoq_pct`) | 2,479 symbols, one snapshot | 🟢 for the current value |
| Scanner: bulk / block activity 3M + shares | `trendlyne_deals` + `v_trendlyne_deals_net` | 19,787 rows back to 2006; **866 rows / 95 symbols in the last 90d** | 🟢 (NSE `bulk_deals` has only 13 days, `block_deals` 12 rows — use Trendlyne) |
| Scanner: delivery % vs 3M avg | `delivery_data.deliverable_pct` | 829,714 rows, 2025-10-01 → 2026-10-19 | 🟢 |
| Scanner: accumulation score + evidence class | `smart_money_scores_daily` (`accumulation_score`, `evidence_class`, `data_confidence`) | as above | 🟢 |
| Scanner: sector label | `sector_master.sector` | only **550 symbols** have a non-null sector | 🟡 fall back to `index_constituents.industry` |
| Detail: price + change | `prices_eod` | full | 🟢 |
| Detail: Financials tiles | `nse_financials_quarterly`, `stock_fundamental_values`, `v_stock_fundamentals_latest` | present; `roce_pct` missing for ~14% of stocks, `profit_margin_trend_pct` ~15% | 🟡 ship with a coverage caveat |
| Detail: Technicals tiles | `stock_features_daily` (`rsi14`, `sma50`, `sma200`) | present; `sma200` missing ~20% | 🟡 |
| Detail: News / disclosures | `corporate_announcements`, `mf_scheme_disclosure_snapshot` | present | 🟢 |
| Universe selects (Nifty 500/200/Midcap/Smallcap) | `index_constituents` | 7,988 rows, 2026-10-12 → 2026-10-22 | 🟢 current; no history |

### 3.1 The one real blocker
The **FII/DII cash-flow history** is the only thing on this screen that cannot be rendered at
all for the designed windows. Two KPI cards, the whole cumulative flow-regime chart, and the
period toggle's meaning for those panels all depend on it, and staging holds ~8 sessions.

Options, in order of preference:
1. **NSE daily FII/DII archive backfill** — the dated-archive URL
   (`fii_stats_{YYYYMMDD}.xls`) 404s, so this needs the current combined-report endpoint
   scraped forward daily from here (gives 1M in ~3 weeks, 1Y in a year) — plus a one-off
   historical source.
2. **ScanX `insight/fii-dii-data`** — server-rendered `ng-state` blob, 20 days of cash
   buy/sell/net. Covers 1M once we have 2 more days; still not 3M/6M/1Y.
3. **Trendlyne** — confirmed to carry **no** market-wide FII/DII cash flow. Not an option.

Until one of those lands, those three panels must render an explicit
"Insufficient history — N sessions available" state rather than a number. The design has no
such state; it needs one adding.

### 3.2 Second gap worth naming
Sector rotation is specified as **combined FII + DII** flow per sector. No DII sector split
exists in any feed we have. Either relabel the panel "FPI sector flows" (honest, servable
from `fpi_sector_auc`) or source a DII sector breakdown.

---

## 4. Wiring rules that apply (standing)

- Reuse the existing v5 Copilot tools rather than new endpoints; one data source per tool.
- Brokers are read-only on this screen.
- Icons sit beside names, never replacing them.
- Report gaps on the screen (don't silently show zeroes or illustrative numbers).
- The bundle's numbers are **illustrative** — the footer says so, and that label must not
  survive into the wired build.
