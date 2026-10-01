# Directional Movement Prediction Engine — PRD v1.0

Status: **PROPOSED — not approved to build.** Owner spec, 2026-10-01.
Convention follows `PATTERN_VALIDATION_PRD_V1.md`: the owner's design is recorded as written,
then a measured-reality section states what the data already says and which amendments are
required before this is buildable.

---

## Part 1 — Owner specification

### Objective

Identify stocks where the probability and magnitude of an **upward** move are sufficiently
asymmetric to support a profitable long trade. The existing movement model is **not discarded** —
it becomes the candidate-generation layer.

### The problem

The current model predicts `P(large movement)`. The trading objective needs
`P(UP before DOWN)`. These are not equivalent: a stock can have a high probability of +5% **and**
of −5%, and so be unsuitable for a long trade.

### Three mandatory layers

| layer | question |
|---|---|
| A — Movement | Will the stock move significantly? |
| B — Direction | If it moves, which way is more probable? |
| C — Tradeability | Does that produce positive net return after costs? |

### Prediction targets (barrier labels, 5-session max hold)

`+5% before −2%` · `+5% before −3%` · `+10% before −3%` · `+10% before −5%`

Entry is the next trading day's open. Labels: **UP** (target first), **DOWN** (stop first),
**TIME_EXIT** (neither within the hold), **AMBIGUOUS** (both inside one daily candle, ordering
unknowable). *AMBIGUOUS must never be automatically classified as UP or DOWN.*

### Directional edge

`DirectionalEdge = P(UP) − P(DOWN)`. A candidate with P(UP) 43% / P(DOWN) 41% is not a
directional trade however high its movement probability.

### Feature groups

Price structure · trend · breakout · volume confirmation · relative strength (vs NIFTY and
sector) · sector momentum · market regime · volatility · run-up · gaps · events · chart patterns
with lifecycle state.

Run-up and gap-up are **features, never filters** (§19, §20).

### Candidate generation

Research universe is the movement model's **top 50 / 100 / 200**. Top-10 remains a reported
cohort but is no longer assumed optimal.

### Control arms (mandatory)

- **Control A** — matched random stocks
- **Control B** — rank 301–400
- **Control C** — simple technical baseline (`close > SMA50 AND 20D return > 0`)

### Evaluation

Directional decile table showing monotone separation; calibration curves and Brier score;
bootstrap CIs; MFE/MAE; and the four-way failure decomposition — A target-first, B stop-first with
eventual upside, C time-exit with meaningful MFE, D low-MFE failure, plus E ambiguous kept separate.

### Critical success criterion

Not *"top decile made +0.4%"*. It is: **the top directional cohort generated materially higher net
return and target-before-stop probability than matched control, surviving costs and out-of-sample
validation.**

### What we must NOT do (§44, recorded verbatim in spirit)

Keep tuning stops until one turns positive · remove >25% run-up stocks · remove gap-ups ·
automatically prefer breakouts · treat top-10 rank as proof of quality · optimize thresholds on the
final test set · treat correlation as edge · use hit rate alone · ignore costs · use discretionary
exits · silently classify ambiguous bars.

---

## Part 2 — Measured reality, and the amendments this PRD requires

Everything below is measured, not argued. Sources: paper engine replay (165 sessions, 327,002
predictions), the charting post-sealed artefact (204,039 rows, 2024-08-26 → 2026-09-18), and the
A1 comparator.

### A. The decision tree contains a gate that has already been failed

§43 reads *"Does movement model beat control? NO → reconsider movement model."*

It does not. Measured on the engine's own replay, across the full stop/target matrix:

| portfolio | tgt/stop | TOP-10 net | control 301–400 net |
|---|---|---|---|
| P5 | 5%/2% | −0.800% | **−0.740%** |
| P5 | 5%/3% | −0.887% | **−0.820%** |
| P5 | 5%/5% | −1.107% | **−0.979%** |
| P10 | 10%/2% | −0.685% | **−0.613%** |
| P10 | 10%/3% | −0.797% | **−0.700%** |
| P10 | 10%/5% | −0.997% | **−0.842%** |

**Control wins 6/6.** By its own gate this PRD should be at "reconsider", yet §47 proceeds.

**Amendment:** the gate must distinguish two different claims. The movement model failed **as a
trade signal**. Whether it is useful **as a candidate filter feeding a directional model** is
untested and is what this PRD proposes to test. State that, or the document contradicts itself.

### B. The GO criteria must be numeric and frozen now

§46's "meaningful separation" cannot be adjudicated after results exist. The thresholds are
already computable. Break-even `P(UP before DOWN)` including measured friction is
`(stop + 0.628) / (target + stop)`:

| cell | measured base rate | **top decile must exceed** | lift required |
|---|---|---|---|
| +5% / −2% | 25.8% | **37.5%** | 1.46× |
| +5% / −3% | 33.3% | **45.4%** | 1.36× |
| +5% / −5% | 41.5% | **56.3%** | 1.36× |
| +10% / −2% | 13.2% | **21.9%** | 1.66× |
| +10% / −3% | 16.4% | **27.9%** | 1.70× |
| +10% / −5% | 20.1% | **37.5%** | 1.87× |

Required lift spans **1.36× to 1.87×**. For calibration, B5 ranking its own barrier label achieves
**2.33× (top decile) / 2.82× (top 1%)**, AUC 0.7184, replicated across two independent periods —
so the bar is demanding but has precedent.

### C. Friction is 0.628%, not a nominal 0.25%

Measured from the research cost engine (`nse-equity-statutory-v1@1`) over 8,759 costed exits:

| component | median | mean |
|---|---|---|
| statutory cost | 0.235% | 0.852% |
| **slippage** | **0.393%** | 0.334% |
| **all-in** | **0.628%** | 1.186% |

**100% of rows exceed the paper engine's 0.25% assumption**; 82.6% exceed 0.50%. `rules_v1` sets
`"slippage": 0.0`, and slippage alone is larger than its entire cost allowance. §25 must use the
real cost engine, and every EV calculation in this PRD must carry 0.628%.

### D. No power calculation — the most likely way this effort is wasted

The replay window is **165 sessions**. Trades cluster within a session, so the effective sample is
165 regardless of whether 10 or 100 names are taken per day. Prior arithmetic: at 5 names/day,
separating +0.50%/trade from zero needs ~550 sessions ≈ 2.2 years.

**Amendment:** compute the required session count *before building*. An underpowered sealed test
returns "not established" and will be misread as a null.

### E. Event features (§21) are largely unavailable over the research window

`event_category` / `sentiment` are **0% classified for 2024-Q2 → 2025-Q4**, reaching 68–83% only
from 2026-Q1. A label-based event history is about **nine months**, and the replay window sits
inside the unclassified block.

**Amendment:** §21 must list the features that exist, not twelve aspirational ones. Where events
are used, consume `nidp.v_event_asof` (migration 156), which applies the as-of rule **once** with
cross-exchange de-duplication — applying anything on top double-applies the rule.

### F. State the prior and the ledger position

Direction has been tested **~374 times across H#35–H#41 with 0 tradeable survivors**, against a
multiple-testing ledger with 40+ families spent. The barrier-label formulation here is genuinely
different from what failed, so this is not forbidden — but the significance threshold must be
stricter than a fresh programme's, and §46 needs a **programme-level stopping rule**: if the
directional MVP misses its pre-registered bar, direction is closed for this architecture rather
than iterated.

### G. Supporting evidence the model predicts magnitude, not sign

| | TOP 5 | control 301+ |
|---|---|---|
| high from entry | **+3.751%** | +1.696% |
| low from entry | **−3.354%** | −1.719% |
| close from entry | −0.145% | −0.102% |
| label hit | 22.4% | 3.0% |

The excursion is **2.2× larger in both directions** and close to symmetric. Only 7.7% of label hits
involved a ≥3% gap, so pre-pricing does not explain it. The ranking is monotone and well
calibrated for movement (35.0% actual vs 38.9% predicted at rank 1–5; 5.5% vs 4.79% at 301+)
— the skill is real, and it is skill at the wrong quantity.

Leakage was audited and is clean: six checks, **zero violations** across 346,940 snapshots. The
losses are real, not artefacts.

---

## Status

Not approved. Amendments A–F are prerequisites, not suggestions. The §45 MVP is correctly scoped
once B (numeric GO thresholds), C (real friction) and D (power) are settled.

Related: `PATTERN_VALIDATION_PRD_V1.md`, `CONFLUENCE_ENGINE_PRD_V1.md`,
`tpd3/pattern_engine/REGISTRY_SEED.md`.
