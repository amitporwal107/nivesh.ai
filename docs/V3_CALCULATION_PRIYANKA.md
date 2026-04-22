# V3 per-fund calculation — priyankamantri@gmail.com

**Engine:** `v3.0-phase1`  · **Coverage:** 100.0% (26/26 funds scored)

**Portfolio aggregates:** Avg Quality 57.01 · Avg Health 59.07 · Recs → EXIT 0 · SWITCH 0 · REVIEW 15

## Scoring formula reference

| Composite | Components & weights |
|---|---|
| **Quality** | Performance 25% · Risk-adjusted 20% · Consistency 20% · Drawdown 15% · Cost 10% · AUM/Age 10% |
| **Health**  | Manager-tenure 25% · AUM-stability 20% · Turnover 15% · Concentration 15% · Downside-protection 15% · Expense-trend 10% |
| **Exit**    | Overlap 25% · Tax-impact 25% · Quality-inverse 25% · Cost 15% · Portfolio-fit 10% |
| **Add**     | Gap-fit 30% · Low-overlap 25% · Quality 20% · Need 15% · Cost 10% |
| **Switch**  | (ΔQuality + ΔOverlap + Cost-saving − Tax-cost)/scale — Regular plans only; ≥2.0 = switch |

Each component is scored 0–10; composite = Σ(component × weight) / Σ(available weights) × 10, renormalised when primitives are missing.

---

## 1. HDFC Flexi Cap, Fund - Direct Plan -, Growth Option
- **Plan:** direct · **Value:** ₹379,692
- **Scores:** Q=67 · H=55 · E=42 · A=64 · SW=—
- **Recommendation:** **REVIEW** — Watch closely — Health 55/100 below floor.
- **Primitives:** AUM ₹91,335Cr · age 31.3y · mgr tenure 2.8y · max DD 13.4% · consistency 4.80 · downside-capture 76.3% · turnover 9% · top-10 47.2%

### Quality 67/100
| Component | Value /10 | Weight | Contribution /100 |
|---|---:|---:|---:|
| Performance | 7.36 | 25% | 18.40 |
| Risk Adjusted | 6.17 | 20% | 12.34 |
| Consistency | 4.80 | 20% | 9.60 |
| Drawdown | 7.31 | 15% | 10.96 |
| Cost | 5.75 | 10% | 5.75 |
| Aum Age | 10.00 | 10% | 10.00 |
| **Composite** | **6.71** | **100%** | **67.1** |

### Health 55/100
| Component | Value /10 | Weight | Contribution /100 |
|---|---:|---:|---:|
| Manager Tenure | 5.60 | 25% | 14.00 |
| Turnover | 1.57 | 15% | 2.35 |
| Concentration | 5.69 | 15% | 8.54 |
| Downside Protection | 7.37 | 15% | 11.05 |
| Expense Trend | 7.70 | 10% | 7.70 |
| *missing: aum_stability* | — | — | *renorm over 80%* |
| **Composite** | **5.46** | **100%** | **54.6** |

### Exit 42/100
Exit 42/100 combines portfolio overlap, tax drag, quality-inverse (3.3/10 from Q=67), expense ratio, and portfolio fit.

> **Guardrail:** recent_investment_lockout — exit action locked.

> _**Below par** — Quality 67/100, Health 55/100. Drags: Inconsistent — beats its category in only 48% of rolling 12-month windows (consistency 4.8/10); Portfolio turnover 9% is outside the healthy band (turnover score 1.6/10). Strength on quality: mature/large fund (10.0/10)._

---

## 2. HDFC Flexi Cap, Fund - Direct Plan -, Growth Option
- **Plan:** direct · **Value:** ₹356,422
- **Scores:** Q=67 · H=55 · E=42 · A=64 · SW=—
- **Recommendation:** **REVIEW** — Watch closely — Health 55/100 below floor.
- **Primitives:** AUM ₹91,335Cr · age 31.3y · mgr tenure 2.8y · max DD 13.4% · consistency 4.80 · downside-capture 76.3% · turnover 9% · top-10 47.2%

### Quality 67/100
| Component | Value /10 | Weight | Contribution /100 |
|---|---:|---:|---:|
| Performance | 7.36 | 25% | 18.40 |
| Risk Adjusted | 6.17 | 20% | 12.34 |
| Consistency | 4.80 | 20% | 9.60 |
| Drawdown | 7.31 | 15% | 10.96 |
| Cost | 5.75 | 10% | 5.75 |
| Aum Age | 10.00 | 10% | 10.00 |
| **Composite** | **6.71** | **100%** | **67.1** |

### Health 55/100
| Component | Value /10 | Weight | Contribution /100 |
|---|---:|---:|---:|
| Manager Tenure | 5.60 | 25% | 14.00 |
| Turnover | 1.57 | 15% | 2.35 |
| Concentration | 5.69 | 15% | 8.54 |
| Downside Protection | 7.37 | 15% | 11.05 |
| Expense Trend | 7.70 | 10% | 7.70 |
| *missing: aum_stability* | — | — | *renorm over 80%* |
| **Composite** | **5.46** | **100%** | **54.6** |

### Exit 42/100
Exit 42/100 combines portfolio overlap, tax drag, quality-inverse (3.3/10 from Q=67), expense ratio, and portfolio fit.

> **Guardrail:** recent_investment_lockout — exit action locked.

> _**Below par** — Quality 67/100, Health 55/100. Drags: Inconsistent — beats its category in only 48% of rolling 12-month windows (consistency 4.8/10); Portfolio turnover 9% is outside the healthy band (turnover score 1.6/10). Strength on quality: mature/large fund (10.0/10)._

---

## 3. HDFC Flexi Cap, Fund - Regular Plan, - Growth
- **Plan:** regular · **Value:** ₹219,673 · **Cost leak:** ~₹1,538/yr
- **Scores:** Q=67 · H=55 · E=42 · A=64 · SW=0.15
- **Recommendation:** **REVIEW** — Watch closely — Health 55/100 below floor.
- **Primitives:** AUM ₹91,335Cr · age 31.3y · mgr tenure 2.8y · max DD 13.4% · consistency 4.80 · downside-capture 76.3% · turnover 9% · top-10 47.2%

### Quality 67/100
| Component | Value /10 | Weight | Contribution /100 |
|---|---:|---:|---:|
| Performance | 7.36 | 25% | 18.40 |
| Risk Adjusted | 6.17 | 20% | 12.34 |
| Consistency | 4.80 | 20% | 9.60 |
| Drawdown | 7.31 | 15% | 10.96 |
| Cost | 5.75 | 10% | 5.75 |
| Aum Age | 10.00 | 10% | 10.00 |
| **Composite** | **6.71** | **100%** | **67.1** |

### Health 55/100
| Component | Value /10 | Weight | Contribution /100 |
|---|---:|---:|---:|
| Manager Tenure | 5.60 | 25% | 14.00 |
| Turnover | 1.57 | 15% | 2.35 |
| Concentration | 5.69 | 15% | 8.54 |
| Downside Protection | 7.37 | 15% | 11.05 |
| Expense Trend | 7.70 | 10% | 7.70 |
| *missing: aum_stability* | — | — | *renorm over 80%* |
| **Composite** | **5.46** | **100%** | **54.6** |

### Exit 42/100
Exit 42/100 combines portfolio overlap, tax drag, quality-inverse (3.3/10 from Q=67), expense ratio, and portfolio fit.

### Switch 0.15
Formula: ΔQuality + ΔOverlap + Cost-saving − Tax-cost (scaled). Cost-saving ≈ ₹1,538/yr → SW=0.15 — <2.0 → no switch (saving not worth tax/execution drag).

> **Guardrail:** recent_investment_lockout — exit action locked.

> _**Below par** — Quality 67/100, Health 55/100. Drags: Inconsistent — beats its category in only 48% of rolling 12-month windows (consistency 4.8/10); Portfolio turnover 9% is outside the healthy band (turnover score 1.6/10). Strength on quality: mature/large fund (10.0/10)._

---

## 4. HDFC Focused, Fund - Direct Plan -, Growth Option
- **Plan:** direct · **Value:** ₹245,127
- **Scores:** Q=65 · H=46 · E=35 · A=65 · SW=—
- **Recommendation:** **REVIEW** — Watch closely — Health 46/100 below floor.
- **Primitives:** max DD 17.3% · downside-capture 103.5%

### Quality 65/100
| Component | Value /10 | Weight | Contribution /100 |
|---|---:|---:|---:|
| Drawdown | 6.53 | 15% | 9.79 |
| *missing: performance, risk_adjusted, consistency, cost, aum_age* | — | — | *renorm over 15%* |
| **Composite** | **6.53** | **100%** | **65.3** |

### Health 46/100
| Component | Value /10 | Weight | Contribution /100 |
|---|---:|---:|---:|
| Downside Protection | 4.65 | 15% | 6.97 |
| *missing: manager_tenure, aum_stability, turnover, concentration, expense_trend* | — | — | *renorm over 15%* |
| **Composite** | **4.65** | **100%** | **46.5** |

### Exit 35/100
Exit 35/100 combines portfolio overlap, tax drag, quality-inverse (3.5/10 from Q=65), expense ratio, and portfolio fit.

> **Guardrail:** recent_investment_lockout — exit action locked.

> _**Below par** — Quality 65/100, Health 46/100. Drags: Downside capture 103.5% — amplifies benchmark losses (score 4.7/10)._

---

## 5. Axis Small Cap, Fund Direct Growth
- **Plan:** direct · **Value:** ₹672,789
- **Scores:** Q=59 · H=68 · E=62 · A=71 · SW=—
- **Recommendation:** **REVIEW** — Watch closely — Exit 62/100 elevated.
- **Primitives:** AUM ₹23,919Cr · age 12.4y · ER direct 0.56% · mgr tenure 2.7y · max DD 19.4% · consistency 4.00 · downside-capture 75.1% · turnover 38% · top-10 20.7%

### Quality 59/100
| Component | Value /10 | Weight | Contribution /100 |
|---|---:|---:|---:|
| Performance | 5.44 | 25% | 13.60 |
| Risk Adjusted | 4.89 | 20% | 9.78 |
| Consistency | 4.00 | 20% | 8.00 |
| Drawdown | 6.11 | 15% | 9.17 |
| Cost | 9.70 | 10% | 9.70 |
| Aum Age | 8.46 | 10% | 8.46 |
| **Composite** | **5.87** | **100%** | **58.7** |

### Health 68/100
| Component | Value /10 | Weight | Contribution /100 |
|---|---:|---:|---:|
| Manager Tenure | 5.40 | 25% | 13.50 |
| Turnover | 6.33 | 15% | 9.50 |
| Concentration | 10.00 | 15% | 15.00 |
| Downside Protection | 7.49 | 15% | 11.24 |
| Expense Trend | 4.80 | 10% | 4.80 |
| *missing: aum_stability* | — | — | *renorm over 80%* |
| **Composite** | **6.75** | **100%** | **67.5** |

### Exit 62/100
Exit 62/100 combines portfolio overlap, tax drag, quality-inverse (4.1/10 from Q=59), expense ratio, and portfolio fit.

> **Guardrail:** recent_investment_lockout — exit action locked.

> _**Acceptable** — Quality 59/100, Health 68/100. Drags: Inconsistent — beats its category in only 40% of rolling 12-month windows (consistency 4.0/10); Risk-adjusted returns are sub-par — Sharpe+Sortino combined score 4.9/10; Expense ratio is trending up (score 4.8/10). Strength on quality: competitive expense ratio (9.7/10). Exit score 62/100 — engine flags this for review._

---

## 6. HDFC Small Cap, Fund - Regular Plan, - Growth Plan
- **Plan:** regular · **Value:** ₹20,640 · **Cost leak:** ~₹144/yr
- **Scores:** Q=54 · H=74 · E=46 · A=65 · SW=0.01
- **Recommendation:** **REVIEW** — Watch closely — Quality 54/100 below floor.
- **Primitives:** AUM ₹33,724Cr · age 18.0y · ER direct 0.80% · mgr tenure 11.8y · max DD 22.8% · consistency 4.00 · downside-capture 76.4% · turnover 8% · top-10 28.1%

### Quality 54/100
| Component | Value /10 | Weight | Contribution /100 |
|---|---:|---:|---:|
| Performance | 5.05 | 25% | 12.62 |
| Risk Adjusted | 3.98 | 20% | 7.96 |
| Consistency | 4.00 | 20% | 8.00 |
| Drawdown | 5.45 | 15% | 8.18 |
| Cost | 8.50 | 10% | 8.50 |
| Aum Age | 9.11 | 10% | 9.11 |
| **Composite** | **5.44** | **100%** | **54.4** |

### Health 74/100
| Component | Value /10 | Weight | Contribution /100 |
|---|---:|---:|---:|
| Manager Tenure | 10.00 | 25% | 25.00 |
| Turnover | 1.30 | 15% | 1.95 |
| Concentration | 10.00 | 15% | 15.00 |
| Downside Protection | 7.36 | 15% | 11.04 |
| Expense Trend | 6.40 | 10% | 6.40 |
| *missing: aum_stability* | — | — | *renorm over 80%* |
| **Composite** | **7.42** | **100%** | **74.2** |

### Exit 46/100
Exit 46/100 combines portfolio overlap, tax drag, quality-inverse (4.6/10 from Q=54), expense ratio, and portfolio fit.

### Switch 0.01
Formula: ΔQuality + ΔOverlap + Cost-saving − Tax-cost (scaled). Cost-saving ≈ ₹144/yr → SW=0.01 — <2.0 → no switch (saving not worth tax/execution drag).

> **Guardrail:** recent_investment_lockout — exit action locked.

> _**Below par** — Quality 54/100, Health 74/100. Drags: Risk-adjusted returns are sub-par — Sharpe+Sortino combined score 4.0/10; Inconsistent — beats its category in only 40% of rolling 12-month windows (consistency 4.0/10); Portfolio turnover 8% is outside the healthy band (turnover score 1.3/10). Strength on quality: mature/large fund (9.1/10)._

---

## 7. HDFC Small Cap, Fund - Regular Plan, - Growth Plan
- **Plan:** regular · **Value:** ₹77,204 · **Cost leak:** ~₹144/yr
- **Scores:** Q=54 · H=74 · E=46 · A=65 · SW=0.01
- **Recommendation:** **REVIEW** — Watch closely — Quality 54/100 below floor.
- **Primitives:** AUM ₹33,724Cr · age 18.0y · ER direct 0.80% · mgr tenure 11.8y · max DD 22.8% · consistency 4.00 · downside-capture 76.4% · turnover 8% · top-10 28.1%

### Quality 54/100
| Component | Value /10 | Weight | Contribution /100 |
|---|---:|---:|---:|
| Performance | 5.05 | 25% | 12.62 |
| Risk Adjusted | 3.98 | 20% | 7.96 |
| Consistency | 4.00 | 20% | 8.00 |
| Drawdown | 5.45 | 15% | 8.18 |
| Cost | 8.50 | 10% | 8.50 |
| Aum Age | 9.11 | 10% | 9.11 |
| **Composite** | **5.44** | **100%** | **54.4** |

### Health 74/100
| Component | Value /10 | Weight | Contribution /100 |
|---|---:|---:|---:|
| Manager Tenure | 10.00 | 25% | 25.00 |
| Turnover | 1.30 | 15% | 1.95 |
| Concentration | 10.00 | 15% | 15.00 |
| Downside Protection | 7.36 | 15% | 11.04 |
| Expense Trend | 6.40 | 10% | 6.40 |
| *missing: aum_stability* | — | — | *renorm over 80%* |
| **Composite** | **7.42** | **100%** | **74.2** |

### Exit 46/100
Exit 46/100 combines portfolio overlap, tax drag, quality-inverse (4.6/10 from Q=54), expense ratio, and portfolio fit.

### Switch 0.01
Formula: ΔQuality + ΔOverlap + Cost-saving − Tax-cost (scaled). Cost-saving ≈ ₹144/yr → SW=0.01 — <2.0 → no switch (saving not worth tax/execution drag).

> **Guardrail:** recent_investment_lockout — exit action locked.

> _**Below par** — Quality 54/100, Health 74/100. Drags: Risk-adjusted returns are sub-par — Sharpe+Sortino combined score 4.0/10; Inconsistent — beats its category in only 40% of rolling 12-month windows (consistency 4.0/10); Portfolio turnover 8% is outside the healthy band (turnover score 1.3/10). Strength on quality: mature/large fund (9.1/10)._

---

## 8. Franklin India Small, Cap Fund - Growth, (erstwhile Franklin, India Smaller, Companies Fund -, Growth)
- **Plan:** regular · **Value:** ₹8,430 · **Cost leak:** ~₹59/yr
- **Scores:** Q=54 · H=80 · E=57 · A=62 · SW=0.01
- **Recommendation:** **REVIEW** — Watch closely — Quality 54/100 below floor.
- **Primitives:** AUM ₹11,724Cr · age 13.3y · ER direct 0.96% · mgr tenure 13.3y · max DD 24.1% · consistency 4.00 · downside-capture 84.0% · turnover 32% · top-10 21.0%

### Quality 54/100
| Component | Value /10 | Weight | Contribution /100 |
|---|---:|---:|---:|
| Performance | 5.85 | 25% | 14.62 |
| Risk Adjusted | 4.39 | 20% | 8.78 |
| Consistency | 4.00 | 20% | 8.00 |
| Drawdown | 5.18 | 15% | 7.77 |
| Cost | 7.70 | 10% | 7.70 |
| Aum Age | 7.42 | 10% | 7.42 |
| **Composite** | **5.43** | **100%** | **54.3** |

### Health 80/100
| Component | Value /10 | Weight | Contribution /100 |
|---|---:|---:|---:|
| Manager Tenure | 10.00 | 25% | 25.00 |
| Turnover | 5.34 | 15% | 8.01 |
| Concentration | 10.00 | 15% | 15.00 |
| Downside Protection | 6.60 | 15% | 9.90 |
| Expense Trend | 5.70 | 10% | 5.70 |
| *missing: aum_stability* | — | — | *renorm over 80%* |
| **Composite** | **7.95** | **100%** | **79.5** |

### Exit 57/100
Exit 57/100 combines portfolio overlap, tax drag, quality-inverse (4.6/10 from Q=54), expense ratio, and portfolio fit.

### Switch 0.01
Formula: ΔQuality + ΔOverlap + Cost-saving − Tax-cost (scaled). Cost-saving ≈ ₹59/yr → SW=0.01 — <2.0 → no switch (saving not worth tax/execution drag).

> **Guardrail:** recent_investment_lockout — exit action locked.

> _**Below par** — Quality 54/100, Health 80/100. Drags: Inconsistent — beats its category in only 40% of rolling 12-month windows (consistency 4.0/10); Risk-adjusted returns are sub-par — Sharpe+Sortino combined score 4.4/10. Strength on quality: competitive expense ratio (7.7/10)._

---

## 9. NIPPON INDIA, SMALL CAP FUND, - GROWTH PLAN, GROWTH OPTION
- **Plan:** regular · **Value:** ₹144,757 · **Cost leak:** ~₹1,013/yr
- **Scores:** Q=53 · H=57 · E=67 · A=69 · SW=0.10
- **Recommendation:** **REVIEW** — Watch closely — Quality 53/100 below floor; Exit 67/100 elevated.
- **Primitives:** AUM ₹2,523Cr · age 5.5y · ER direct 0.35% · mgr tenure 2.3y · max DD 26.1% · consistency 4.00 · downside-capture 100.0% · turnover 27% · top-10 12.1%

### Quality 53/100
| Component | Value /10 | Weight | Contribution /100 |
|---|---:|---:|---:|
| Performance | 5.49 | 25% | 13.72 |
| Risk Adjusted | 4.76 | 20% | 9.52 |
| Consistency | 4.00 | 20% | 8.00 |
| Drawdown | 4.77 | 15% | 7.15 |
| Cost | 10.00 | 10% | 10.00 |
| Aum Age | 5.05 | 10% | 5.05 |
| **Composite** | **5.34** | **100%** | **53.4** |

### Health 57/100
| Component | Value /10 | Weight | Contribution /100 |
|---|---:|---:|---:|
| Manager Tenure | 4.60 | 25% | 11.50 |
| Turnover | 4.50 | 15% | 6.75 |
| Concentration | 10.00 | 15% | 15.00 |
| Downside Protection | 5.00 | 15% | 7.50 |
| Expense Trend | 4.50 | 10% | 4.50 |
| *missing: aum_stability* | — | — | *renorm over 80%* |
| **Composite** | **5.66** | **100%** | **56.6** |

### Exit 67/100
Exit 67/100 combines portfolio overlap, tax drag, quality-inverse (4.7/10 from Q=53), expense ratio, and portfolio fit.

### Switch 0.10
Formula: ΔQuality + ΔOverlap + Cost-saving − Tax-cost (scaled). Cost-saving ≈ ₹1,013/yr → SW=0.10 — <2.0 → no switch (saving not worth tax/execution drag).

> **Guardrail:** recent_investment_lockout — exit action locked.

> _**Below par** — Quality 53/100, Health 57/100. Drags: Inconsistent — beats its category in only 40% of rolling 12-month windows (consistency 4.0/10); Risk-adjusted returns are sub-par — Sharpe+Sortino combined score 4.8/10; Portfolio turnover 27% is outside the healthy band (turnover score 4.5/10). Strength on quality: competitive expense ratio (10.0/10). Exit score 67/100 — engine flags this for review._

---

## 10. Aditya Birla Sun, Life Large Cap, Fund -IDCW-Direct, Plan(formerly, known as Aditya, Birla Sun Life, Frontline Equity, Fund)
- **Plan:** direct · **Value:** ₹706,343
- **Scores:** Q=52 · H=46 · E=46 · A=60 · SW=—
- **Recommendation:** **REVIEW** — Watch closely — Quality 52/100 below floor; Health 46/100 below floor.
- **Primitives:** AUM ₹26,702Cr · age 13.3y · ER direct 0.97% · mgr tenure 0.3y · max DD 16.7% · consistency 4.00 · downside-capture 95.1% · turnover 52% · top-10 46.8%

### Quality 52/100
| Component | Value /10 | Weight | Contribution /100 |
|---|---:|---:|---:|
| Performance | 4.53 | 25% | 11.32 |
| Risk Adjusted | 3.43 | 20% | 6.86 |
| Consistency | 4.00 | 20% | 8.00 |
| Drawdown | 6.66 | 15% | 9.99 |
| Cost | 7.65 | 10% | 7.65 |
| Aum Age | 8.65 | 10% | 8.65 |
| **Composite** | **5.25** | **100%** | **52.5** |

### Health 46/100
| Component | Value /10 | Weight | Contribution /100 |
|---|---:|---:|---:|
| Manager Tenure | 0.60 | 25% | 1.50 |
| Turnover | 8.67 | 15% | 13.01 |
| Concentration | 5.79 | 15% | 8.68 |
| Downside Protection | 5.49 | 15% | 8.24 |
| Expense Trend | 5.30 | 10% | 5.30 |
| *missing: aum_stability* | — | — | *renorm over 80%* |
| **Composite** | **4.59** | **100%** | **45.9** |

### Exit 46/100
Exit 46/100 combines portfolio overlap, tax drag, quality-inverse (4.8/10 from Q=52), expense ratio, and portfolio fit.

> _**Below par** — Quality 52/100, Health 46/100. Drags: Risk-adjusted returns are sub-par — Sharpe+Sortino combined score 3.4/10; Inconsistent — beats its category in only 40% of rolling 12-month windows (consistency 4.0/10); Short manager tenure (0.3y) — score 0.6/10. Strength on quality: mature/large fund (8.7/10)._

---

## 11. UTI Balanced, Advantage Fund -, Regular Plan
- **Plan:** regular · **Value:** ₹49,525 · **Cost leak:** ~₹176/yr
- **Scores:** Q=41 · H=65 · E=72 · A=59 · SW=0.02
- **Recommendation:** **REVIEW** — Watch closely — Quality 41/100 below floor; Exit 72/100 elevated.
- **Primitives:** AUM ₹2,878Cr · age 2.7y · ER direct 0.60% · mgr tenure 2.8y · max DD 10.5% · consistency 2.86 · turnover 88% · top-10 41.0%

### Quality 41/100
| Component | Value /10 | Weight | Contribution /100 |
|---|---:|---:|---:|
| Performance | 4.48 | 25% | 11.20 |
| Risk Adjusted | 0.00 | 20% | 0.00 |
| Consistency | 2.86 | 20% | 5.72 |
| Drawdown | 7.91 | 15% | 11.87 |
| Cost | 9.50 | 10% | 9.50 |
| Aum Age | 3.13 | 10% | 3.13 |
| **Composite** | **4.14** | **100%** | **41.4** |

### Health 65/100
| Component | Value /10 | Weight | Contribution /100 |
|---|---:|---:|---:|
| Manager Tenure | 5.60 | 25% | 14.00 |
| Turnover | 8.88 | 15% | 13.32 |
| Concentration | 7.24 | 15% | 10.86 |
| Expense Trend | 4.10 | 10% | 4.10 |
| *missing: aum_stability, downside_protection* | — | — | *renorm over 65%* |
| **Composite** | **6.50** | **100%** | **65.0** |

### Exit 72/100
Exit 72/100 combines portfolio overlap, tax drag, quality-inverse (5.9/10 from Q=41), expense ratio, and portfolio fit.

### Switch 0.02
Formula: ΔQuality + ΔOverlap + Cost-saving − Tax-cost (scaled). Cost-saving ≈ ₹176/yr → SW=0.02 — <2.0 → no switch (saving not worth tax/execution drag).

> **Guardrail:** recent_investment_lockout — exit action locked.

> _**Below par** — Quality 41/100, Health 65/100. Drags: Risk-adjusted returns are sub-par — Sharpe+Sortino combined score 0.0/10; Inconsistent — beats its category in only 28% of rolling 12-month windows (consistency 2.9/10); Expense ratio is trending up (score 4.1/10). Strength on quality: competitive expense ratio (9.5/10). Exit score 72/100 — engine flags this for review._

---

## 12. UTI Balanced, Advantage Fund -, Regular Plan
- **Plan:** regular · **Value:** ₹25,115 · **Cost leak:** ~₹176/yr
- **Scores:** Q=41 · H=65 · E=72 · A=59 · SW=0.02
- **Recommendation:** **REVIEW** — Watch closely — Quality 41/100 below floor; Exit 72/100 elevated.
- **Primitives:** AUM ₹2,878Cr · age 2.7y · ER direct 0.60% · mgr tenure 2.8y · max DD 10.5% · consistency 2.86 · turnover 88% · top-10 41.0%

### Quality 41/100
| Component | Value /10 | Weight | Contribution /100 |
|---|---:|---:|---:|
| Performance | 4.48 | 25% | 11.20 |
| Risk Adjusted | 0.00 | 20% | 0.00 |
| Consistency | 2.86 | 20% | 5.72 |
| Drawdown | 7.91 | 15% | 11.87 |
| Cost | 9.50 | 10% | 9.50 |
| Aum Age | 3.13 | 10% | 3.13 |
| **Composite** | **4.14** | **100%** | **41.4** |

### Health 65/100
| Component | Value /10 | Weight | Contribution /100 |
|---|---:|---:|---:|
| Manager Tenure | 5.60 | 25% | 14.00 |
| Turnover | 8.88 | 15% | 13.32 |
| Concentration | 7.24 | 15% | 10.86 |
| Expense Trend | 4.10 | 10% | 4.10 |
| *missing: aum_stability, downside_protection* | — | — | *renorm over 65%* |
| **Composite** | **6.50** | **100%** | **65.0** |

### Exit 72/100
Exit 72/100 combines portfolio overlap, tax drag, quality-inverse (5.9/10 from Q=41), expense ratio, and portfolio fit.

### Switch 0.02
Formula: ΔQuality + ΔOverlap + Cost-saving − Tax-cost (scaled). Cost-saving ≈ ₹176/yr → SW=0.02 — <2.0 → no switch (saving not worth tax/execution drag).

> **Guardrail:** recent_investment_lockout — exit action locked.

> _**Below par** — Quality 41/100, Health 65/100. Drags: Risk-adjusted returns are sub-par — Sharpe+Sortino combined score 0.0/10; Inconsistent — beats its category in only 28% of rolling 12-month windows (consistency 2.9/10); Expense ratio is trending up (score 4.1/10). Strength on quality: competitive expense ratio (9.5/10). Exit score 72/100 — engine flags this for review._

---

## 13. SUNDARAM, VALUE FUND -, REGULAR, GROWTH
- **Plan:** regular · **Value:** ₹97,809 · **Cost leak:** ~₹685/yr
- **Scores:** Q=37 · H=69 · E=43 · A=38 · SW=0.07
- **Recommendation:** **REVIEW** — Watch closely — Quality 37/100 below floor.
- **Primitives:** AUM ₹1,212Cr · age 26.4y · ER direct 1.71% · mgr tenure 5.2y · max DD 16.1% · consistency 3.60 · downside-capture 89.0% · turnover 49% · top-10 44.7%

### Quality 37/100
| Component | Value /10 | Weight | Contribution /100 |
|---|---:|---:|---:|
| Performance | 2.35 | 25% | 5.88 |
| Risk Adjusted | 2.04 | 20% | 4.08 |
| Consistency | 3.60 | 20% | 7.20 |
| Drawdown | 6.77 | 15% | 10.15 |
| Cost | 3.95 | 10% | 3.95 |
| Aum Age | 5.78 | 10% | 5.78 |
| **Composite** | **3.70** | **100%** | **37.0** |

### Health 69/100
| Component | Value /10 | Weight | Contribution /100 |
|---|---:|---:|---:|
| Manager Tenure | 8.20 | 25% | 20.50 |
| Turnover | 8.17 | 15% | 12.25 |
| Concentration | 6.32 | 15% | 9.48 |
| Downside Protection | 6.10 | 15% | 9.15 |
| Expense Trend | 3.70 | 10% | 3.70 |
| *missing: aum_stability* | — | — | *renorm over 80%* |
| **Composite** | **6.89** | **100%** | **68.9** |

### Exit 43/100
Exit 43/100 combines portfolio overlap, tax drag, quality-inverse (6.3/10 from Q=37), expense ratio, and portfolio fit.

### Switch 0.07
Formula: ΔQuality + ΔOverlap + Cost-saving − Tax-cost (scaled). Cost-saving ≈ ₹685/yr → SW=0.07 — <2.0 → no switch (saving not worth tax/execution drag).

> **Guardrail:** recent_investment_lockout — exit action locked.

> _**Below par** — Quality 37/100, Health 69/100. Drags: Risk-adjusted returns are sub-par — Sharpe+Sortino combined score 2.0/10; Trailing returns trail the category average (performance component 2.4/10); Expense ratio is trending up (score 3.7/10). Strength on health: long-tenured manager (8.2/10)._

---

## 14. quant Multi Asset, Allocation Fund -, Direct Plan
- **Plan:** direct · **Value:** ₹138,264
- **Scores:** Q=29 · H=21 · E=82 · A=53 · SW=—
- **Recommendation:** **REVIEW** — High exit signal (Exit 82/100) but exit is currently locked — holding < 6 months — lockout.
- **Primitives:** AUM ₹53Cr · age 2.1y · ER direct 0.40% · mgr tenure 1.1y · max DD 10.5% · consistency 0.71 · turnover 3% · top-10 62.9%

### Quality 29/100
| Component | Value /10 | Weight | Contribution /100 |
|---|---:|---:|---:|
| Performance | 1.59 | 25% | 3.98 |
| Risk Adjusted | 0.00 | 20% | 0.00 |
| Consistency | 0.71 | 20% | 1.42 |
| Drawdown | 7.90 | 15% | 11.85 |
| Cost | 10.00 | 10% | 10.00 |
| Aum Age | 1.66 | 10% | 1.66 |
| **Composite** | **2.89** | **100%** | **28.9** |

### Health 21/100
| Component | Value /10 | Weight | Contribution /100 |
|---|---:|---:|---:|
| Manager Tenure | 2.20 | 25% | 5.50 |
| Turnover | 0.46 | 15% | 0.69 |
| Concentration | 1.78 | 15% | 2.67 |
| Expense Trend | 4.90 | 10% | 4.90 |
| *missing: aum_stability, downside_protection* | — | — | *renorm over 65%* |
| **Composite** | **2.12** | **100%** | **21.2** |

### Exit 82/100
Exit 82/100 combines portfolio overlap, tax drag, quality-inverse (7.1/10 from Q=29), expense ratio, and portfolio fit.

> **Guardrail:** recent_investment_lockout — exit action locked.

> _**Below par** — Quality 29/100, Health 21/100. Drags: Risk-adjusted returns are sub-par — Sharpe+Sortino combined score 0.0/10; Inconsistent — beats its category in only 7% of rolling 12-month windows (consistency 0.7/10); Portfolio turnover 3% is outside the healthy band (turnover score 0.5/10). Strength on quality: competitive expense ratio (10.0/10). Exit score 82/100 — engine flags this for review._

---

## 15. Parag Parikh Large, Cap Fund -, Regular Plan, Growth
- **Plan:** regular · **Value:** ₹483,960 · **Cost leak:** ~₹3,388/yr
- **Scores:** Q=26 · H=33 · E=83 · A=50 · SW=0.34
- **Recommendation:** **REVIEW** — High exit signal (Exit 83/100) but exit is currently locked — holding < 6 months — lockout.
- **Primitives:** AUM ₹551Cr · age 0.2y · mgr tenure 0.3y · top-10 43.8%

### Quality 26/100
| Component | Value /10 | Weight | Contribution /100 |
|---|---:|---:|---:|
| Risk Adjusted | 0.00 | 20% | 0.00 |
| Cost | 9.75 | 10% | 9.75 |
| Aum Age | 0.67 | 10% | 0.67 |
| *missing: performance, consistency, drawdown* | — | — | *renorm over 40%* |
| **Composite** | **2.60** | **100%** | **26.1** |

### Health 33/100
| Component | Value /10 | Weight | Contribution /100 |
|---|---:|---:|---:|
| Manager Tenure | 0.60 | 25% | 1.50 |
| Concentration | 6.55 | 15% | 9.82 |
| Expense Trend | 5.10 | 10% | 5.10 |
| *missing: aum_stability, turnover, downside_protection* | — | — | *renorm over 50%* |
| **Composite** | **3.29** | **100%** | **32.9** |

### Exit 83/100
Exit 83/100 combines portfolio overlap, tax drag, quality-inverse (7.4/10 from Q=26), expense ratio, and portfolio fit.

### Switch 0.34
Formula: ΔQuality + ΔOverlap + Cost-saving − Tax-cost (scaled). Cost-saving ≈ ₹3,388/yr → SW=0.34 — <2.0 → no switch (saving not worth tax/execution drag).

> **Guardrail:** recent_investment_lockout — exit action locked.

> _**Below par** — Quality 26/100, Health 33/100. Drags: Risk-adjusted returns are sub-par — Sharpe+Sortino combined score 0.0/10; Small/young fund (AUM ₹551Cr · age 0.2y) — maturity score 0.7/10; Short manager tenure (0.3y) — score 0.6/10. Strength on quality: competitive expense ratio (9.8/10). Exit score 83/100 — engine flags this for review._

---

## 16. Parag Parikh Flexi, Cap Fund - Direct, Plan Growth
- **Plan:** direct · **Value:** ₹170,211
- **Scores:** Q=72 · H=71 · E=40 · A=80 · SW=—
- **Recommendation:** **HOLD** — Neither urgent action nor conviction-grade add — keep holding.
- **Primitives:** AUM ₹128,966Cr · age 12.9y · ER direct 0.62% · mgr tenure 12.9y · max DD 11.0% · consistency 4.40 · downside-capture 52.2% · turnover 15% · top-10 49.8%

### Quality 72/100
| Component | Value /10 | Weight | Contribution /100 |
|---|---:|---:|---:|
| Performance | 6.39 | 25% | 15.97 |
| Risk Adjusted | 8.30 | 20% | 16.60 |
| Consistency | 4.40 | 20% | 8.80 |
| Drawdown | 7.80 | 15% | 11.70 |
| Cost | 9.40 | 10% | 9.40 |
| Aum Age | 10.00 | 10% | 10.00 |
| **Composite** | **7.25** | **100%** | **72.5** |

### Health 71/100
| Component | Value /10 | Weight | Contribution /100 |
|---|---:|---:|---:|
| Manager Tenure | 10.00 | 25% | 25.00 |
| Turnover | 2.56 | 15% | 3.84 |
| Concentration | 5.04 | 15% | 7.56 |
| Downside Protection | 9.78 | 15% | 14.67 |
| Expense Trend | 6.10 | 10% | 6.10 |
| *missing: aum_stability* | — | — | *renorm over 80%* |
| **Composite** | **7.15** | **100%** | **71.5** |

### Exit 40/100
Exit 40/100 combines portfolio overlap, tax drag, quality-inverse (2.8/10 from Q=72), expense ratio, and portfolio fit.

> **Guardrail:** recent_investment_lockout — exit action locked.

> _**Strong fund** — Quality 72/100, Health 71/100. Drags: Inconsistent — beats its category in only 44% of rolling 12-month windows (consistency 4.4/10); Portfolio turnover 15% is outside the healthy band (turnover score 2.6/10). Strength on quality: mature/large fund (10.0/10)._

---

## 17. HDFC Balanced, Advantage Fund -, Direct Plan -, Growth Option
- **Plan:** direct · **Value:** ₹232,356
- **Scores:** Q=71 · H=64 · E=39 · A=77 · SW=—
- **Recommendation:** **HOLD** — Neither urgent action nor conviction-grade add — keep holding.
- **Primitives:** AUM ₹98,458Cr · age 13.3y · ER direct 0.75% · mgr tenure 3.7y · max DD 10.2% · consistency 4.40 · turnover 15% · top-10 30.8%

### Quality 71/100
| Component | Value /10 | Weight | Contribution /100 |
|---|---:|---:|---:|
| Performance | 7.72 | 25% | 19.30 |
| Risk Adjusted | 6.33 | 20% | 12.66 |
| Consistency | 4.40 | 20% | 8.80 |
| Drawdown | 7.96 | 15% | 11.94 |
| Cost | 8.75 | 10% | 8.75 |
| Aum Age | 10.00 | 10% | 10.00 |
| **Composite** | **7.14** | **100%** | **71.4** |

### Health 64/100
| Component | Value /10 | Weight | Contribution /100 |
|---|---:|---:|---:|
| Manager Tenure | 6.70 | 25% | 16.75 |
| Turnover | 2.43 | 15% | 3.65 |
| Concentration | 9.80 | 15% | 14.70 |
| Expense Trend | 6.20 | 10% | 6.20 |
| *missing: aum_stability, downside_protection* | — | — | *renorm over 65%* |
| **Composite** | **6.35** | **100%** | **63.5** |

### Exit 39/100
Exit 39/100 combines portfolio overlap, tax drag, quality-inverse (2.9/10 from Q=71), expense ratio, and portfolio fit.

> **Guardrail:** recent_investment_lockout — exit action locked.

> _**Acceptable** — Quality 71/100, Health 64/100. Drags: Inconsistent — beats its category in only 44% of rolling 12-month windows (consistency 4.4/10); Portfolio turnover 15% is outside the healthy band (turnover score 2.4/10). Strength on quality: mature/large fund (10.0/10)._

---

## 18. Parag Parikh Flexi, Cap Fund - Regular, Plan Growth
- **Plan:** regular · **Value:** ₹85,095 · **Cost leak:** ~₹596/yr
- **Scores:** Q=70 · H=74 · E=42 · A=78 · SW=0.06
- **Recommendation:** **HOLD** — Neither urgent action nor conviction-grade add — keep holding.
- **Primitives:** AUM ₹128,966Cr · age 12.9y · ER direct 0.62% · mgr tenure 12.9y · max DD 11.2% · consistency 4.40 · downside-capture 53.4% · turnover 15% · top-10 49.8%

### Quality 70/100
| Component | Value /10 | Weight | Contribution /100 |
|---|---:|---:|---:|
| Performance | 5.96 | 25% | 14.90 |
| Risk Adjusted | 7.75 | 20% | 15.50 |
| Consistency | 4.40 | 20% | 8.80 |
| Drawdown | 7.76 | 15% | 11.64 |
| Cost | 9.40 | 10% | 9.40 |
| Aum Age | 10.00 | 10% | 10.00 |
| **Composite** | **7.02** | **100%** | **70.2** |

### Health 74/100
| Component | Value /10 | Weight | Contribution /100 |
|---|---:|---:|---:|
| Manager Tenure | 10.00 | 25% | 25.00 |
| Turnover | 2.56 | 15% | 3.84 |
| Concentration | 5.04 | 15% | 7.56 |
| Downside Protection | 9.66 | 15% | 14.49 |
| Expense Trend | 8.10 | 10% | 8.10 |
| *missing: aum_stability* | — | — | *renorm over 80%* |
| **Composite** | **7.37** | **100%** | **73.7** |

### Exit 42/100
Exit 42/100 combines portfolio overlap, tax drag, quality-inverse (3.0/10 from Q=70), expense ratio, and portfolio fit.

### Switch 0.06
Formula: ΔQuality + ΔOverlap + Cost-saving − Tax-cost (scaled). Cost-saving ≈ ₹596/yr → SW=0.06 — <2.0 → no switch (saving not worth tax/execution drag).

> **Guardrail:** recent_investment_lockout — exit action locked.

> _**Strong fund** — Quality 70/100, Health 74/100. Drags: Inconsistent — beats its category in only 44% of rolling 12-month windows (consistency 4.4/10); Portfolio turnover 15% is outside the healthy band (turnover score 2.6/10). Strength on quality: mature/large fund (10.0/10)._

---

## 19. HDFC Balanced, Advantage Fund -, Regular Plan -, Growth
- **Plan:** regular · **Value:** ₹86,026 · **Cost leak:** ~₹602/yr
- **Scores:** Q=69 · H=64 · E=41 · A=75 · SW=0.06
- **Recommendation:** **HOLD** — Neither urgent action nor conviction-grade add — keep holding.
- **Primitives:** AUM ₹98,458Cr · age 25.6y · ER direct 0.75% · mgr tenure 3.7y · max DD 10.3% · consistency 4.00 · turnover 15% · top-10 30.8%

### Quality 69/100
| Component | Value /10 | Weight | Contribution /100 |
|---|---:|---:|---:|
| Performance | 7.37 | 25% | 18.43 |
| Risk Adjusted | 5.89 | 20% | 11.78 |
| Consistency | 4.00 | 20% | 8.00 |
| Drawdown | 7.94 | 15% | 11.91 |
| Cost | 8.75 | 10% | 8.75 |
| Aum Age | 10.00 | 10% | 10.00 |
| **Composite** | **6.89** | **100%** | **68.9** |

### Health 64/100
| Component | Value /10 | Weight | Contribution /100 |
|---|---:|---:|---:|
| Manager Tenure | 6.70 | 25% | 16.75 |
| Turnover | 2.43 | 15% | 3.65 |
| Concentration | 9.80 | 15% | 14.70 |
| Expense Trend | 6.40 | 10% | 6.40 |
| *missing: aum_stability, downside_protection* | — | — | *renorm over 65%* |
| **Composite** | **6.38** | **100%** | **63.8** |

### Exit 41/100
Exit 41/100 combines portfolio overlap, tax drag, quality-inverse (3.1/10 from Q=69), expense ratio, and portfolio fit.

### Switch 0.06
Formula: ΔQuality + ΔOverlap + Cost-saving − Tax-cost (scaled). Cost-saving ≈ ₹602/yr → SW=0.06 — <2.0 → no switch (saving not worth tax/execution drag).

> **Guardrail:** recent_investment_lockout — exit action locked.

> _**Acceptable** — Quality 69/100, Health 64/100. Drags: Inconsistent — beats its category in only 40% of rolling 12-month windows (consistency 4.0/10); Portfolio turnover 15% is outside the healthy band (turnover score 2.4/10). Strength on quality: mature/large fund (10.0/10)._

---

## 20. Kotak Flexicap, Fund - Direct, Growth (Erstwhile, Kotak Standard, Multicap Fund - Dir, Gr)
- **Plan:** direct · **Value:** ₹303,798
- **Scores:** Q=62 · H=66 · E=43 · A=73 · SW=—
- **Recommendation:** **HOLD** — Neither urgent action nor conviction-grade add — keep holding.
- **Primitives:** AUM ₹50,146Cr · age 13.3y · ER direct 0.59% · mgr tenure 13.3y · max DD 16.3% · consistency 4.40 · downside-capture 88.9% · turnover 10% · top-10 42.6%

### Quality 62/100
| Component | Value /10 | Weight | Contribution /100 |
|---|---:|---:|---:|
| Performance | 6.00 | 25% | 15.00 |
| Risk Adjusted | 4.15 | 20% | 8.30 |
| Consistency | 4.40 | 20% | 8.80 |
| Drawdown | 6.74 | 15% | 10.11 |
| Cost | 9.55 | 10% | 9.55 |
| Aum Age | 10.00 | 10% | 10.00 |
| **Composite** | **6.18** | **100%** | **61.8** |

### Health 66/100
| Component | Value /10 | Weight | Contribution /100 |
|---|---:|---:|---:|
| Manager Tenure | 10.00 | 25% | 25.00 |
| Turnover | 1.67 | 15% | 2.50 |
| Concentration | 6.85 | 15% | 10.28 |
| Downside Protection | 6.11 | 15% | 9.17 |
| Expense Trend | 5.80 | 10% | 5.80 |
| *missing: aum_stability* | — | — | *renorm over 80%* |
| **Composite** | **6.59** | **100%** | **65.9** |

### Exit 43/100
Exit 43/100 combines portfolio overlap, tax drag, quality-inverse (3.8/10 from Q=62), expense ratio, and portfolio fit.

> **Guardrail:** recent_investment_lockout — exit action locked.

> _**Acceptable** — Quality 62/100, Health 66/100. Drags: Risk-adjusted returns are sub-par — Sharpe+Sortino combined score 4.2/10; Inconsistent — beats its category in only 44% of rolling 12-month windows (consistency 4.4/10); Portfolio turnover 10% is outside the healthy band (turnover score 1.7/10). Strength on quality: mature/large fund (10.0/10)._

---

## 21. ICICI Prudential, Large Cap Fund, (erstwhile Bluechip, Fund) - Direct Plan, - Growth
- **Plan:** direct · **Value:** ₹663,275
- **Scores:** Q=61 · H=61 · E=45 · A=68 · SW=—
- **Recommendation:** **HOLD** — Neither urgent action nor conviction-grade add — keep holding.
- **Primitives:** AUM ₹69,948Cr · age 13.3y · ER direct 0.87% · mgr tenure 5.3y · max DD 15.4% · consistency 4.40 · downside-capture 85.9% · turnover 18% · top-10 52.7%

### Quality 61/100
| Component | Value /10 | Weight | Contribution /100 |
|---|---:|---:|---:|
| Performance | 5.60 | 25% | 14.00 |
| Risk Adjusted | 4.81 | 20% | 9.62 |
| Consistency | 4.40 | 20% | 8.80 |
| Drawdown | 6.92 | 15% | 10.38 |
| Cost | 8.15 | 10% | 8.15 |
| Aum Age | 10.00 | 10% | 10.00 |
| **Composite** | **6.09** | **100%** | **60.9** |

### Health 61/100
| Component | Value /10 | Weight | Contribution /100 |
|---|---:|---:|---:|
| Manager Tenure | 8.30 | 25% | 20.75 |
| Turnover | 3.00 | 15% | 4.50 |
| Concentration | 4.33 | 15% | 6.50 |
| Downside Protection | 6.41 | 15% | 9.62 |
| Expense Trend | 7.50 | 10% | 7.50 |
| *missing: aum_stability* | — | — | *renorm over 80%* |
| **Composite** | **6.11** | **100%** | **61.1** |

### Exit 45/100
Exit 45/100 combines portfolio overlap, tax drag, quality-inverse (3.9/10 from Q=61), expense ratio, and portfolio fit.

> **Guardrail:** recent_investment_lockout — exit action locked.

> _**Acceptable** — Quality 61/100, Health 61/100. Drags: Inconsistent — beats its category in only 44% of rolling 12-month windows (consistency 4.4/10); Risk-adjusted returns are sub-par — Sharpe+Sortino combined score 4.8/10; Portfolio turnover 18% is outside the healthy band (turnover score 3.0/10). Strength on quality: mature/large fund (10.0/10)._

---

## 22. SBI Contra Fund -, Direct Plan -, Growth
- **Plan:** direct · **Value:** ₹235,914
- **Scores:** Q=60 · H=71 · E=43 · A=70 · SW=—
- **Recommendation:** **HOLD** — Neither urgent action nor conviction-grade add — keep holding.
- **Primitives:** AUM ₹43,754Cr · age 13.3y · ER direct 0.75% · mgr tenure 8.0y · max DD 15.8% · consistency 4.00 · downside-capture 87.4% · turnover 8% · top-10 33.8%

### Quality 60/100
| Component | Value /10 | Weight | Contribution /100 |
|---|---:|---:|---:|
| Performance | 5.20 | 25% | 13.00 |
| Risk Adjusted | 5.41 | 20% | 10.82 |
| Consistency | 4.00 | 20% | 8.00 |
| Drawdown | 6.83 | 15% | 10.25 |
| Cost | 8.75 | 10% | 8.75 |
| Aum Age | 9.68 | 10% | 9.68 |
| **Composite** | **6.05** | **100%** | **60.5** |

### Health 71/100
| Component | Value /10 | Weight | Contribution /100 |
|---|---:|---:|---:|
| Manager Tenure | 10.00 | 25% | 25.00 |
| Turnover | 1.33 | 15% | 2.00 |
| Concentration | 9.04 | 15% | 13.56 |
| Downside Protection | 6.26 | 15% | 9.39 |
| Expense Trend | 6.50 | 10% | 6.50 |
| *missing: aum_stability* | — | — | *renorm over 80%* |
| **Composite** | **7.06** | **100%** | **70.6** |

### Exit 43/100
Exit 43/100 combines portfolio overlap, tax drag, quality-inverse (4.0/10 from Q=60), expense ratio, and portfolio fit.

> **Guardrail:** recent_investment_lockout — exit action locked.

> _**Acceptable** — Quality 60/100, Health 71/100. Drags: Inconsistent — beats its category in only 40% of rolling 12-month windows (consistency 4.0/10); Portfolio turnover 8% is outside the healthy band (turnover score 1.3/10). Strength on quality: mature/large fund (9.7/10)._

---

## 23. ICICI Prudential, Value Fund, (erstwhile Value, Discovery Fund) -, Growth
- **Plan:** regular · **Value:** ₹85,486 · **Cost leak:** ~₹1,420/yr
- **Scores:** Q=59 · H=73 · E=44 · A=56 · SW=0.14
- **Recommendation:** **HOLD** — Neither urgent action nor conviction-grade add — keep holding.
- **Primitives:** AUM ₹55,852Cr · age 21.7y · mgr tenure 5.3y · max DD 14.2% · consistency 4.00 · downside-capture 72.4% · turnover 52% · top-10 53.9%

### Quality 59/100
| Component | Value /10 | Weight | Contribution /100 |
|---|---:|---:|---:|
| Performance | 5.19 | 25% | 12.97 |
| Risk Adjusted | 6.27 | 20% | 12.54 |
| Consistency | 4.00 | 20% | 8.00 |
| Drawdown | 7.16 | 15% | 10.74 |
| Cost | 4.95 | 10% | 4.95 |
| Aum Age | 10.00 | 10% | 10.00 |
| **Composite** | **5.92** | **100%** | **59.2** |

### Health 73/100
| Component | Value /10 | Weight | Contribution /100 |
|---|---:|---:|---:|
| Manager Tenure | 8.30 | 25% | 20.75 |
| Turnover | 8.67 | 15% | 13.01 |
| Concentration | 4.04 | 15% | 6.06 |
| Downside Protection | 7.76 | 15% | 11.64 |
| Expense Trend | 6.90 | 10% | 6.90 |
| *missing: aum_stability* | — | — | *renorm over 80%* |
| **Composite** | **7.29** | **100%** | **72.9** |

### Exit 44/100
Exit 44/100 combines portfolio overlap, tax drag, quality-inverse (4.1/10 from Q=59), expense ratio, and portfolio fit.

### Switch 0.14
Formula: ΔQuality + ΔOverlap + Cost-saving − Tax-cost (scaled). Cost-saving ≈ ₹1,420/yr → SW=0.14 — <2.0 → no switch (saving not worth tax/execution drag).

> **Guardrail:** recent_investment_lockout — exit action locked.

> _**Acceptable** — Quality 59/100, Health 73/100. Drags: Inconsistent — beats its category in only 40% of rolling 12-month windows (consistency 4.0/10); High expense ratio (5.0/10); Top-10 holdings = 53.9% of corpus (concentration risk, score 4.0/10). Strength on quality: mature/large fund (10.0/10)._

---

## 24. ICICI Prudential, Value Fund, (erstwhile Value, Discovery Fund) -, Growth
- **Plan:** regular · **Value:** ₹202,866 · **Cost leak:** ~₹1,420/yr
- **Scores:** Q=59 · H=73 · E=44 · A=56 · SW=0.14
- **Recommendation:** **HOLD** — Neither urgent action nor conviction-grade add — keep holding.
- **Primitives:** AUM ₹55,852Cr · age 21.7y · mgr tenure 5.3y · max DD 14.2% · consistency 4.00 · downside-capture 72.4% · turnover 52% · top-10 53.9%

### Quality 59/100
| Component | Value /10 | Weight | Contribution /100 |
|---|---:|---:|---:|
| Performance | 5.19 | 25% | 12.97 |
| Risk Adjusted | 6.27 | 20% | 12.54 |
| Consistency | 4.00 | 20% | 8.00 |
| Drawdown | 7.16 | 15% | 10.74 |
| Cost | 4.95 | 10% | 4.95 |
| Aum Age | 10.00 | 10% | 10.00 |
| **Composite** | **5.92** | **100%** | **59.2** |

### Health 73/100
| Component | Value /10 | Weight | Contribution /100 |
|---|---:|---:|---:|
| Manager Tenure | 8.30 | 25% | 20.75 |
| Turnover | 8.67 | 15% | 13.01 |
| Concentration | 4.04 | 15% | 6.06 |
| Downside Protection | 7.76 | 15% | 11.64 |
| Expense Trend | 6.90 | 10% | 6.90 |
| *missing: aum_stability* | — | — | *renorm over 80%* |
| **Composite** | **7.29** | **100%** | **72.9** |

### Exit 44/100
Exit 44/100 combines portfolio overlap, tax drag, quality-inverse (4.1/10 from Q=59), expense ratio, and portfolio fit.

### Switch 0.14
Formula: ΔQuality + ΔOverlap + Cost-saving − Tax-cost (scaled). Cost-saving ≈ ₹1,420/yr → SW=0.14 — <2.0 → no switch (saving not worth tax/execution drag).

> **Guardrail:** recent_investment_lockout — exit action locked.

> _**Acceptable** — Quality 59/100, Health 73/100. Drags: Inconsistent — beats its category in only 40% of rolling 12-month windows (consistency 4.0/10); High expense ratio (5.0/10); Top-10 holdings = 53.9% of corpus (concentration risk, score 4.0/10). Strength on quality: mature/large fund (10.0/10)._

---

## 25. SBI Contra Fund -, Regular Plan -, Growth
- **Plan:** regular · **Value:** ₹165,286 · **Cost leak:** ~₹1,157/yr
- **Scores:** Q=57 · H=72 · E=45 · A=67 · SW=0.12
- **Recommendation:** **HOLD** — Neither urgent action nor conviction-grade add — keep holding.
- **Primitives:** AUM ₹43,754Cr · age 26.8y · ER direct 0.75% · mgr tenure 8.0y · max DD 16.2% · consistency 3.60 · downside-capture 88.9% · turnover 8% · top-10 33.8%

### Quality 57/100
| Component | Value /10 | Weight | Contribution /100 |
|---|---:|---:|---:|
| Performance | 4.70 | 25% | 11.75 |
| Risk Adjusted | 4.94 | 20% | 9.88 |
| Consistency | 3.60 | 20% | 7.20 |
| Drawdown | 6.77 | 15% | 10.15 |
| Cost | 8.75 | 10% | 8.75 |
| Aum Age | 9.68 | 10% | 9.68 |
| **Composite** | **5.74** | **100%** | **57.4** |

### Health 72/100
| Component | Value /10 | Weight | Contribution /100 |
|---|---:|---:|---:|
| Manager Tenure | 10.00 | 25% | 25.00 |
| Turnover | 1.33 | 15% | 2.00 |
| Concentration | 9.04 | 15% | 13.56 |
| Downside Protection | 6.11 | 15% | 9.17 |
| Expense Trend | 7.50 | 10% | 7.50 |
| *missing: aum_stability* | — | — | *renorm over 80%* |
| **Composite** | **7.15** | **100%** | **71.5** |

### Exit 45/100
Exit 45/100 combines portfolio overlap, tax drag, quality-inverse (4.3/10 from Q=57), expense ratio, and portfolio fit.

### Switch 0.12
Formula: ΔQuality + ΔOverlap + Cost-saving − Tax-cost (scaled). Cost-saving ≈ ₹1,157/yr → SW=0.12 — <2.0 → no switch (saving not worth tax/execution drag).

> **Guardrail:** recent_investment_lockout — exit action locked.

> _**Acceptable** — Quality 57/100, Health 72/100. Drags: Inconsistent — beats its category in only 36% of rolling 12-month windows (consistency 3.6/10); Trailing returns trail the category average (performance component 4.7/10); Portfolio turnover 8% is outside the healthy band (turnover score 1.3/10). Strength on quality: mature/large fund (9.7/10)._

---

## 26. HDFC Small Cap, Fund - Direct, Growth Plan
- **Plan:** direct · **Value:** ₹673,246
- **Scores:** Q=56 · H=73 · E=45 · A=66 · SW=—
- **Recommendation:** **HOLD** — Neither urgent action nor conviction-grade add — keep holding.
- **Primitives:** AUM ₹33,724Cr · age 13.3y · ER direct 0.80% · mgr tenure 11.8y · max DD 22.6% · consistency 4.00 · downside-capture 74.9% · turnover 8% · top-10 28.1%

### Quality 56/100
| Component | Value /10 | Weight | Contribution /100 |
|---|---:|---:|---:|
| Performance | 5.48 | 25% | 13.70 |
| Risk Adjusted | 4.38 | 20% | 8.76 |
| Consistency | 4.00 | 20% | 8.00 |
| Drawdown | 5.48 | 15% | 8.22 |
| Cost | 8.50 | 10% | 8.50 |
| Aum Age | 9.11 | 10% | 9.11 |
| **Composite** | **5.63** | **100%** | **56.3** |

### Health 73/100
| Component | Value /10 | Weight | Contribution /100 |
|---|---:|---:|---:|
| Manager Tenure | 10.00 | 25% | 25.00 |
| Turnover | 1.30 | 15% | 1.95 |
| Concentration | 10.00 | 15% | 15.00 |
| Downside Protection | 7.51 | 15% | 11.26 |
| Expense Trend | 5.00 | 10% | 5.00 |
| *missing: aum_stability* | — | — | *renorm over 80%* |
| **Composite** | **7.28** | **100%** | **72.8** |

### Exit 45/100
Exit 45/100 combines portfolio overlap, tax drag, quality-inverse (4.4/10 from Q=56), expense ratio, and portfolio fit.

> **Guardrail:** recent_investment_lockout — exit action locked.

> _**Acceptable** — Quality 56/100, Health 73/100. Drags: Inconsistent — beats its category in only 40% of rolling 12-month windows (consistency 4.0/10); Risk-adjusted returns are sub-par — Sharpe+Sortino combined score 4.4/10; Portfolio turnover 8% is outside the healthy band (turnover score 1.3/10). Strength on quality: mature/large fund (9.1/10)._

---

