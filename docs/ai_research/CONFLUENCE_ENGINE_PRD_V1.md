# Nivesh Pattern × Market × Corporate Event Confluence Engine — PRD v1

**Status:** DRAFT for owner review. Nothing built against it yet.
**Owners:** chart/market — app-af · event — app-28 · arbiter — Amit
**Date:** 2026-09-25

---

## 0. What changed, and why this document exists

The research unit stops being `Pattern → prediction` and becomes:

> Pattern + Technical State + Market Regime + Sector Regime + Corporate Event + Event Timing
> → Historical Outcome

The key word is **confluence**, not "more indicators". A bigger indicator score is not the goal; the
goal is to find out whether the *combination* behaves differently from its parts.

Two owner decisions constrain everything below:

1. **Signals stay independent.** No single fused model. Chart/market publishes its signal, events
   publish theirs, correlations between them are computed and *shown as options*. The user picks.
2. **Direction is not assumed.** See §4.

---

## 1. The hierarchy

```
                    MARKET  ── regime
                      ▼
                    SECTOR  ── regime
                      ▼
                    STOCK
       ┌──────────────┼──────────────┐
    CHART           EVENT        FUNDAMENTAL
    STATE           STATE           STATE        (context/controls only in v1)
       └──────────────┼──────────────┘
                 CONFLUENCE
                      ▼
              HISTORICAL TEST
            +5%  ·  +10%  ·  downside
```

Fundamental state is **controls only** in v1. Promoting it is a v2 decision; adding it now explodes
dimensionality against cells that are already thin.

---

## 2. THE THREE CASES MUST BE SEPARATED

This is the core of the design and the easiest thing to get wrong.

| case | shape | what it tests | predictive? |
|---|---|---|---|
| **A — pattern before event** | 20D consolidation → flag → volume contraction → **event** → breakout | did the event act as a *catalyst* releasing a built setup? | yes |
| **B — event created the pattern** | acquisition → +8% gap → continuation → flag → breakout | does the *post-event* pattern predict continuation? | yes, but only of continuation |
| **C — independent agreement** | breakout setup **+** positive event **+** strong RS **+** high RVOL | does the combination beat either alone? | yes — the scientific question |

**Case B may never be presented as evidence that the pattern predicted the original move.** The
pattern is downstream of the event. This is enforced structurally, not by convention: a B-row's
`pattern_start` is after `event_timestamp`, and the schema in §7 makes that checkable.

**The actual scientific question is C:**

```
P(outcome | pattern ∧ event)   >   P(outcome | pattern)
                               and >   P(outcome | event)
```

Both inequalities, not either.

---

## 3. Pattern × Event matrix — an experimental design, NOT a recommendation table

| Pattern | Positive event | Negative event | Neutral event |
|---|---|---|---|
| Breakout · Bull flag · Ascending triangle · Rectangle · Cup & handle · Double bottom · H&S · Descending triangle · Falling wedge · Rising wedge · Channel breakout · Range expansion | Test | Test | Test |

**This is 36 cells = 36 looks.** Under the independent-signals design, every cell we *display* is a
look whether or not we write it up. See §10.

**Reality check before anyone plans around this matrix:**

- The NI-3 registry currently has **3 of 16 pattern families enabled**. Most rows of this matrix
  cannot be populated today.
- Event labels exist for **~9 months**, not two years (0% classified 2024-Q2..2025-Q4).
- So v1 populates the subset that exists, and renders the rest as `NOT_MEASURABLE`, never blank.

---

## 4. Event direction — MIXED until proven, and the evidence says be pessimistic

The taxonomy gains `event_direction ∈ {POSITIVE, NEGATIVE, MIXED, UNKNOWN}`, assigned **by historical
test, never by intuition**. Defaults are MIXED:

- **QIP** = positive funding signal + negative dilution signal → MIXED.
- **Acquisition** = different sign for acquirer vs target → the *same event* carries different
  expected information per security. Direction is a property of (event, security), not of the event.

**A prior result must not be re-imported here.** `event_category` direction (regulatory +13pp,
orders −24pp) is **RETRACTED**. It died under controls: choosing a size-decile *median* vs *mean*
benchmark flipped the sign of all 11 categories with t > 6 each, and a placebo on **random dates**
reached t = 10.8. ~410 tests, 92,644 events, **zero tradeable direction survivors**. Cleaning the
labels made direction *worse*.

What survived is the owner's own point, sharpened by evidence: **direction is materiality and
exposure, not label.** The same IRDAI paper sent PB Fintech −36% and ICICI Lombard +5.1%.

**Therefore v1 does not consume a `direction_prior`.** Event category enters as a raw categorical.
Direction may only be claimed per (event-family, role, materiality-bucket) with real-minus-placebo
attached.

---

## 5. Market and sector regime — the missing middle layer

Two observations that must never be equivalent training examples:

| | CONFLUENCE state | CONFLICT state |
|---|---|---|
| pattern | bullish breakout | bullish breakout |
| event | ₹500 Cr order | ₹500 Cr order |
| NIFTY | above 20/50 DMA | falling sharply |
| sector | above 20 DMA | weak |
| stock RS | > NIFTY | negative |
| RVOL | 3.2 | normal |

### 5a. Verified capability, 2026-09-25

| input | status | where | coverage |
|---|---|---|---|
| NIFTY trend | **EXISTS** | `regime.py:675` → `market_trend_class_class` | OK on 96.1% of 1,402 dates |
| Breadth | **EXISTS** | `index_history/breadth.py` → `regime.py:788` | uneven per field (A/D ~73%) |
| Market regime | **PARTIAL** | `regime.py:562` | OK on only **68.8%**; 219 of 532 post-sealed sessions UNAVAILABLE |
| Volatility | **PARTIAL** | `regime.py:760` VIX, `nifty_atr_14` | 99.9% covered but **raw levels only — no percentile, z-score or HIGH/LOW class** |
| **Sector trend** | **MISSING from the model path** | data + code already exist: 14 unused sector CSVs, `context.py:377 build_sector_index()`, `:464 sector_value_at()`, `:319 load_sector_map()` | 1,403 rows each, 2019-07..2026-09 |
| Risk-on / risk-off | **MISSING** | nothing in `research/`; app-side `macro_engine.py` is on an unreachable DB | — |

**Cheapest win in the whole PRD: sector trend.** The data and the functions exist; nothing wires
them to the stock-at-time-t path. Do this first.

### 5b. THE SEALED-WINDOW HOLE IS BIGGER THAN IT LOOKS

**All 18 index CSVs have exactly zero rows in 2023-01-01..2024-07-31** — every file jumps
2022-12-30 → 2024-08-01. INDIA_VIX and BREADTH_UNIVERSE included.

The non-obvious consequence: **warm-up after the gap.** `market_regime()` is dark for the first
**219 post-sealed sessions** because its lookbacks span the hole. So the post-sealed segment does not
begin with usable market state — it begins blind and recovers. Any study conditioning on market
regime must exclude that warm-up or report it as UNAVAILABLE, not treat it as SIDEWAYS.

---

## 6. Time alignment — the anti-look-ahead spine

```
09:30  pattern exists          → pattern_timestamp
10:15  breakout                → pattern_confirmation_timestamp
11:32  event becomes public    → event_timestamp
11:32+ event-confirmed response
```

An 11:32 event **cannot** confirm a 10:15 breakout. Every observation therefore carries five
timestamps: `pattern_timestamp`, `pattern_confirmation_timestamp`, `event_timestamp`,
`market_regime_timestamp`, `signal_timestamp`.

### 6a. Event timing types — different experimental structures, not one field

| type | shape | data we have |
|---|---|---|
| 1 — before market | event → next session → reaction | daily bars ✅ |
| 2 — during market | pre-event chart → event → intraday reaction | **5-min bars, 785 symbols, from 2024-08-01 only** |
| 3 — after market | close → event → next open | daily ✅; **64.7%** of NSE filings land here |
| 4 — weekend | Fri close → event → Mon open | ⚠️ production never sweeps weekends; those filings are **absent** |
| 5 — multi-week | rumour → board → CCI → NCLT → completion | `corporate_transactions`: BUYBACK 74 ready, QIP_PREF 301 not ready |

Type 2 is only testable from 2024-08-01 and only for 785 symbols. Type 4 is currently **not
testable at all** — the data is not collected.

**The as-of rule is consumed, never re-applied.** Read `nidp.v_event_asof` (app-28, in progress); it
bakes in the session rule, NSE/BSE dedup and true dissemination time. Applying it twice is the
failure mode the single view exists to prevent.

---

## 7. The state vector

```
PATTERN    pattern_family, pattern, pattern_age, breakout_strength (ATR),
           volume_confirmation, trend_confirmation
EVENT      event_type, event_direction, event_materiality, event_timestamp,
           event_source_confidence, role (target/acquirer/peer/channel)
MARKET     nifty_trend, sector_trend, market_volatility, sector_relative_strength
TECHNICAL  RSI14, ADX14, RVOL20, ATR_EXPANSION, RS20
PROVENANCE pattern_id, pattern_start, pattern_confirmation, pattern_breakout,
           pattern_failure, pattern_invalidation, detector_version, detector_parameters,
           event_id, event_version, event_status
```

Provenance is not bookkeeping. It is what lets us reproduce *why* the system said "bull flag +
positive order event" — and it is what makes case B detectable rather than assumed.

---

## 8. The four-group experiment

| group | definition |
|---|---|
| **A** | pattern, no material event |
| **B** | event, no qualifying pattern |
| **C** | pattern + event |
| **D** | neither |

Measured on each: +5% hit rate, +10% hit rate, mean and median return, MFE, MAE, CAR,
cost-adjusted return.

**Key comparisons: C vs A, C vs B, C vs D.**

Labels are already computed — `outcomes.py:135-136` gives `mfe` and `mae` per horizon, so
`up_5 = mfe ≥ 0.05`, `up_10 = mfe ≥ 0.10`, `down_5 = mae ≤ −0.05`. No new outcome code.

### 8a. THE BASELINE IS VOLATILITY, NOT 0.5

A volatile stock has high odds of a 5% move with no pattern and no event. ATR alone already gives
AUC 0.724 for movement, and a prior move-odds effort here found odds tracking volatility with **no
edge**. Group D is not a sufficient control: **every comparison must also beat an ATR-only model.**
Otherwise we ship a volatility proxy in a confluence costume.

---

## 9. Interaction is the real term

```
Return = Pattern + Event + Market + Sector + (Pattern × Event) + Controls
```

The **Pattern × Event** interaction is the deliverable. A significant main effect for either alone
is already known-ish; the interaction is what would justify the word "confluence".

### 9a. The worked example, and why it does not stop there

Breakout alone 1,000 obs → 14% · Order event alone 800 obs → 18% · **Both 220 obs → 27%**.

Interesting, and insufficient. Before believing it: was the market bullish? the sector? was the event
anticipated? was the breakout *caused* by the event (case B)? after close? results released
simultaneously? another event in-window? was the stock already up 15% in 10 sessions?

That last one has a measured precedent: a run-up followed by positive news gave **−1.07%** over 5
sessions — the label was informative with the sign *reversed*.

---

## 10. Statistics — the part that decides whether any of this is real

- **Within a family:** Holm.
- **To call anything a discovery:** Bonferroni over the ledger count at the time of the look. ~41
  families spent → two-sided α = 0.05/41 → **|t| ≳ 3.3**, rising with every family added.
- **Every displayed correlation is a look**, including the 36 matrix cells and anything never
  written up. Under independent-signals the look count is driven by what we *display*.
- **Non-independence:** overlapping 20-session windows on one symbol, and many symbols moving
  together on one day. Effective n is far below row count; significance must be computed against a
  block/cluster-aware null, not a naive t.
- **Real-minus-placebo on the same symbols**, always. Never an absolute number. This is the single
  discipline that separated signal from artefact in the event study.

### 10a. Every displayed correlation carries, in the same view

n · confidence interval · real-minus-placebo · how many correlations are shown alongside it ·
`INSUFFICIENT_N` rendered **instead of** the number below a floor.

Without the selection-set size, a reader picks the largest number on screen — which is by
construction the most likely to be noise. That is the event_category failure relocated onto the
user. **If the UI cannot carry these, the correlation is not published.**

---

## 11. Validation

| signal type | holdout |
|---|---|
| chart-only | sealed block 2023-01-01..2024-07-31, **one shot** |
| anything event-conditioned | **forward-only, pre-registered** — the seal cannot arbitrate it (the only event data inside is 28,168 rows at 0% classified) |

Walk-forward for parameter choices; the one-shot holdout is the arbiter, not the correction.

---

## 12. Phasing — what is actually buildable

**Phase 1 (now, no new data):** sector trend wired to the model path · volatility classifier
(percentile/z-score over raw VIX+ATR) · the four-group design on **chart + market only** · ATR
baseline · `up_5/up_10/down_5` labels · warm-up exclusion after the sealed gap.

**Phase 2 (needs `v_event_asof`):** case A/B/C separation · the matrix subset that has data ·
Pattern × Event interaction · event timing types 1 and 3.

**Phase 3 (needs new collection):** event→security role and exposure weight (the IRDAI case) ·
materiality from filing documents · regulator events into Postgres · weekend sweeps (type 4) ·
intraday beyond 785 symbols (type 2).

**Not in v1:** fundamental state as a predictor · direction claims of any kind · any statement about
tradeability. H#36 is the reminder — order filings genuinely reprice at the next open, entirely
inside the gap. Real and untradeable at once.

---

## 13. Open questions for the owner

1. **Sparsity is the likeliest killer.** Do we commit to publishing `NOT_MEASURABLE` cells rather
   than quietly dropping them?
2. **Is 3-of-16 enabled pattern families acceptable for v1**, or does the matrix wait for the
   registry to open up?
3. **Who owns the multiple-testing ledger** now that displayed correlations count as looks?
4. **Weekend collection (type 4)** — worth building, or accept the gap and mark it?
