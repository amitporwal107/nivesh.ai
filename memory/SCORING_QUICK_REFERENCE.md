# V2 Scoring Logic - Quick Reference Card

## Exit Score Formula

```
Exit Score = (Overlap × 30%) + (Tax × 25%) + (Cost × 15%) + (Quality × 20%) + (Fit × 10%)
```

**Threshold:** Score ≥ 4.0 → EXIT recommended

---

## Component Scores (All 0-10 scale, higher = worse)

### 1. Overlap Score (30% weight)

**Calculation:**
```
For each fund, find overlap pairs → Calculate avg overlap %

0-20% overlap   → Score 0-3   (Low)
20-50% overlap  → Score 3-7   (Medium)
50%+ overlap    → Score 7-10  (High)
```

**Example:** 95.8% overlap → Score 9.75

---

### 2. Tax Score (25% weight)

**Formula:**
```
Tax % of Exit = (Tax Liability / Exit Amount) × 100

< 3%      → Score 2.0
3-7%      → Score 3-6
7-12%     → Score 6-9
> 12%     → Score 9-10
```

**Tax Rates:**
- STCG (≤ 1 year): 15%
- LTCG (> 1 year): 10% (after ₹1L exemption)

**Example:** 6.8% tax → Score 5.85

---

### 3. Quality Score (20% weight)

**Based on:**
- 3Y returns vs category average (40%)
- Sharpe ratio (30%)
- Consistency/drawdown (20%)
- Alpha (10%)

**Return Gap Scoring:**
```
> +5%        → Score 0   (Excellent)
+2% to +5%  → Score 2   (Good)
-2% to +2%  → Score 5   (Average)
-5% to -2%  → Score 7   (Poor)
< -5%       → Score 10  (Critical)
```

---

### 4. Cost Score (15% weight)

**Expense Ratio:**
```
< 0.3%      → Score 0   (Very low)
0.3-0.5%    → Score 2   (Low)
0.5-1.0%    → Score 5   (Average)
1.0-1.5%    → Score 7   (High)
> 1.5%      → Score 10  (Very high)
```

**Penalty:** +2 if Regular plan when Direct exists

---

### 5. Portfolio Fit Score (10% weight)

**Allocation vs Target:**
```
Under-allocated     → Score 0   (Keep)
Within target       → Score 3   (Neutral)
Slightly over       → Score 6   (Consider exit)
Significantly over  → Score 9   (Exit)
```

---

## Real Example: Axis Small Cap Fund

### Input Data
- Current Value: ₹6,67,877
- Capital Gain: ₹3,02,876
- Tax: ₹45,431 (STCG @ 15%)
- Holding: 0 days
- Expense Ratio: 0.48%
- Category: Small Cap

### Calculation
```
Overlap:  2.96 × 0.30 = 0.888
Tax:      5.85 × 0.25 = 1.463
Cost:     2.80 × 0.15 = 0.420
Quality:  4.25 × 0.20 = 0.850
Fit:      5.00 × 0.10 = 0.500
                      -------
Exit Score            = 4.12
```

### Decision
**EXIT recommended** (4.12 ≥ 4.0)

**Drivers:**
- ✅ Overlap: 2.96 (LOW - not an issue!)
- ⚠️ Tax: 5.85 (Moderate STCG impact)
- ✅ Cost: 2.80 (Low expense ratio)
- ⚠️ Quality: 4.25 (Moderate underperformance)
- ⚠️ Fit: 5.0 (Portfolio rebalancing)

---

## Decision Matrix

| Score Range | Action | Priority |
|-------------|--------|----------|
| 0-2.0 | KEEP | - |
| 2.0-3.5 | HOLD | Low |
| 3.5-4.5 | Consider EXIT | Medium |
| 4.5-6.0 | EXIT | High |
| > 6.0 | EXIT URGENT | Critical |

---

## Key Takeaways

1. **Higher score = Stronger exit signal**
2. **Overlap weight is highest** (30%) - redundancy is most wasteful
3. **Tax score based on actual %**, not just holding period
4. **No single factor dominates** - it's a weighted combination
5. **Score ≥ 4.0 triggers EXIT recommendation**

---

**Full Documentation:** `/app/memory/V2_SCORING_LOGIC.md`
