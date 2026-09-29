# B0–B5 ladder + market sensitivity — first results

**Run:** 2026-09-29 · `pre_sealed` 2021-01-22 .. 2022-12-01 · charting-study-v2
**Code:** `research/charting/baselines/` · **Spec:** `PATTERN_VALIDATION_PRD_V1.md` §§5–10, 33
**Status:** FIRST RESULT. Not validated out-of-sample. The sealed block is untouched.

---

## 1. Two labels, two different answers

### Label A — `up_5 @ H=20` (max favourable excursion ≥ +5%)

`117,208 rows · 1,647 symbols · base rate 72.0%`

| rung | feats | OOS AUC | increment | Brier |
|---|---:|---:|---:|---:|
| B0 base rate | 0 | 0.5000 | — | 0.2015 |
| B1 volatility | 4 | 0.6016 | **+0.1016** | 0.1965 |
| B2 price/size | 5 | 0.6086 | +0.0070 | 0.1956 |
| B3 liquidity | 8 | 0.6094 | +0.0008 | 0.1955 |
| B4 market+calendar | 18 | 0.6709 | +0.0615 | 0.1867 |
| B5 technical | 32 | 0.6728 | +0.0018 | 0.1861 |
| **P1 + pattern** | 44 | 0.6732 | **+0.0005** | 0.1860 |

**This label is weak and the result reflects that.** 72% of rows touch +5% and 61.6% of the same
rows also touch −5% — most hit both, so it is close to asking "did the stock move at all".
Volatility answers that, and nothing after it adds much.

### Label B — the `pct_10` race (reached +10% BEFORE −10%)

`61,921 rows · 1,635 symbols · P(TARGET) 48.6%` — a true coin flip
Excluded, never zeroed: AMBIGUOUS 97 (both barriers on one bar, order unknowable), NONE 15,620
(never resolved), unavailable 56,105.

| rung | feats | OOS AUC | increment | Brier |
|---|---:|---:|---:|---:|
| B0 base rate | 0 | 0.5000 | — | 0.2498 |
| B1 volatility | 4 | 0.6294 | **+0.1294** | 0.2380 |
| B2 price/size | 5 | 0.6288 | −0.0006 | 0.2381 |
| B3 liquidity | 8 | 0.6351 | +0.0063 | 0.2371 |
| B4 market+calendar | 18 | 0.6891 | **+0.0540** | 0.2237 |
| B5 technical | 32 | 0.7399 | **+0.0508** | 0.2067 |
| **P1 + pattern** | 44 | 0.7455 | **+0.0056** | 0.2045 |

per-fold B5 `0.744 0.743 0.726 0.760 0.726` · P1 `0.747 0.752 0.733 0.767 0.728`

**AUC 0.74 on a symmetric direction question.** Every fold improves when the pattern block is
added — 5 of 5 — though each by only ~0.005.

---

## 2. The finding that mattered most: the bull-market confound does NOT hold

2021–22 contained a large Indian small-cap run. In a rising market jumpy stocks go up, so
volatility can look like it predicts *direction* while really detecting *"the market went up"*.
Volatility alone scoring 0.629 on a coin-flip question is the tell. A prediction was recorded
before the test: the edge would concentrate in strong breadth and collapse elsewhere.

**It was wrong.**

| advance/decline | n | B5 AUC | pattern |
|---|---:|---:|---:|
| ADVANCING | 24,985 | 0.7290 | +0.0072 |
| BALANCED | 15,491 | 0.7442 | +0.0065 |
| **DECLINING** | 21,445 | **0.7481** | +0.0037 |

The model is **strongest when the market is declining**. It also holds across every VIX band
(0.723–0.746), every market-trend class (0.723–0.766), all four half-years (0.673–0.755) and in
bear regimes (0.646). If this were a bull-market artifact, declining-breadth periods are exactly
where it would fail. They are where it is best.

### One cut tested nothing, and that is not support

`breadth_pct_above_sma200` returned only **STRONG (53,581)** and **UNKNOWN (8,340)** — no weak or
mixed bucket. That measure essentially never fell below 60% in this window, so the pre-set bands
had no contrast. **That dimension is uninformative here, not confirmatory.** The advance/decline
cut carried the test.

---

## 3. Where the information actually is

| source | label A | label B |
|---|---:|---:|
| volatility | +0.1016 | +0.1294 |
| price + liquidity | +0.0078 | +0.0057 |
| market regime + calendar | +0.0615 | +0.0540 |
| technical state | +0.0018 | **+0.0508** |
| **pattern** | **+0.0005** | **+0.0056** |

Volatility and market context dominate both. Technical state matters for DIRECTION (+0.0508) and
not for movement (+0.0018) — consistent with the standing finding that technicals predict movement,
except that here they carry direction once volatility and regime are controlled.

**Price and liquidity are near-worthless in the ladder, despite beating volatility univariately**
(0.706 and 0.688 vs 0.635). They are proxies for volatility. An adversarial review used those
univariate numbers to argue the ATR baseline was a strawman; nested, the argument dissolves. This
is the clearest demonstration in the whole exercise of why §4 requires a ladder rather than a
baseline race.

---

## 4. What this does NOT show

- **Not out-of-sample.** `pre_sealed` only. The sealed block 2023-01..2024-07 is unread.
- **Not "patterns work".** Every row IS a pattern, so `pattern_present` is a constant. P1 vs B5
  tests WHICH pattern and in what state. Presence needs non-pattern rows (§30's G0–G3).
- **No symbol-clustered intervals yet.** Effective n is nearer 1,635 than 61,921; increments of
  +0.005 need an interval before they are quoted.
- **The segment maxima are not findings.** The pattern increment is largest in BEAR (+0.0180),
  2021H1 (+0.0175) and UNKNOWN-breadth (+0.0172), which *suggests* patterns matter more when
  conditions are uncertain. Those are the three largest of sixteen cells. Picking the largest is
  the selection trap this apparatus exists to prevent.
- **3 of 16 pattern families** are enabled.

## 5. Apparatus notes

- **B0 = 0.5000 exactly**, all five folds, at full scale. It is the only model with a known correct
  answer and it earns its place as a canary: pooling out-of-fold predictions across folds gave B0
  an AUC of 0.3821, because each fold's intercept differs, so a row's score depended on which fold
  it landed in. That contaminated every rung until it was caught.
- Folds hold out **whole symbols**, never rows.
- 30 PRD-named features are absent and listed in `features.MISSING`, including the entire sector
  rung. A rung missing half its specification is a weaker control than it looks.
