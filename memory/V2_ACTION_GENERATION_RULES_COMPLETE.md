# V2 Action Plan Generation Rules - Complete Specification

## Requirements from User (19 Apr 2026)

### Image 1: AI Overview - Portfolio Issues
**Detected Issues:**
1. High equity exposure: 100%
2. No debt allocation: 0%
3. Regular vs Direct cost leak: ₹14K/year

**Actions Required:**
- Add debt allocation
- Generate Regular → Direct switch actions

---

### Image 2: Benchmark - Underperforming Funds
**Underperforming Funds (2):**
1. Franklin India Small Cap Fund - Growth (+5.36% vs benchmark +8.16%)
2. Aditya Birla Sun Life Large Cap Fund - IDCW Direct (-4.01% vs benchmark -0.59%)

**Rule:** For each underperforming fund, suggest **same category** fund with highest ADD score

---

### Image 3: AMC Concentration
**HDFC Exposure: 22.5%** (Target: <15%)

**9 HDFC Funds:**
- HDFC Balanced Advantage Fund - Direct Plan
- HDFC Small Cap Fund - Regular Plan (duplicate)
- HDFC Balanced Advantage Fund - Regular Plan
- HDFC Small Cap Fund - Regular Plan (duplicate)
- HDFC Flexi Cap Fund - Direct Plan

**Rule:** Exit HDFC funds with highest exit scores to bring concentration below 15%

---

### Image 4: Fund-to-Fund Overlap (Stock-Level)
**Overlap Pairs:**

1. **HDFC Flexi Cap Direct vs Regular** - 95.8% overlap, 62 shared stocks
   - Rule: Exit Regular (Direct exists)

2. **HDFC Small Cap Regular vs Direct** - 89.7% overlap, 83 shared stocks
   - Rule: Exit Regular (Direct exists)

3. **Parag Parikh Flexi Cap Direct vs Regular** - 85.8% overlap, 60 shared stocks
   - Rule: Exit Regular (Direct exists)

4. **HDFC Balanced Advantage Direct vs Regular** - 79.0% overlap, 191 shared stocks
   - Rule: Exit Regular (Direct exists)

5. **Aditya Birla Large Cap Direct vs Parag Parikh Large Cap Regular** - 65.2% overlap, 47 shared stocks
   - Rule: Different funds → Exit the one with highest exit score

6. **ICICI Prudential Large Cap Direct vs Parag Parikh Large Cap Regular** - 60.6% overlap, 56 shared stocks
   - Rule: Different funds → Exit the one with highest exit score

---

## Implementation Rules

### Rule 1: Regular vs Direct Consolidation (Highest Priority)
```
IF overlap_pair.fund_a == overlap_pair.fund_b (same scheme, different plan type):
    IF one is Regular and one is Direct:
        EXIT the Regular plan
        REASON: "Same fund exists as Direct plan with lower expense ratio"
```

### Rule 2: AMC Concentration Reduction
```
FOR each AMC with exposure > 15%:
    1. Get all funds from that AMC
    2. Sort by exit_score (descending)
    3. Mark top N funds for EXIT until AMC exposure drops below 15%
    REASON: "Reducing AMC concentration from X% to target <15%"
```

### Rule 3: Underperformer Replacement
```
FOR each fund with performance < benchmark:
    1. Find funds in SAME category
    2. Sort by ADD score (quality + performance)
    3. Generate EXIT action for underperformer
    4. Generate ADD action for top same-category fund
    REASON: "Underperforming vs benchmark by X%. Replacing with higher-rated fund in same category."
```

### Rule 4: Different Fund Overlap Resolution
```
FOR overlap_pairs with overlap > 60% (different funds):
    1. Calculate exit_score for both funds
    2. EXIT the fund with HIGHER exit score
    REASON: "High overlap (X%) with [other fund]. Consolidating to reduce duplication."
```

### Rule 5: Asset Allocation Rebalancing
```
IF equity > 90% AND debt < 10%:
    ADD debt fund (use excluded_amcs list)
    REASON: "Portfolio lacks debt allocation for risk management"
```

### Rule 6: Regular vs Direct Cost Leak
```
Calculate annual_cost_leak = Σ(regular_funds.expense_ratio - equivalent_direct.expense_ratio) × fund_value

IF annual_cost_leak > ₹10,000:
    Generate switch actions for each Regular fund that has Direct equivalent
    REASON: "Switching to Direct plan saves ₹X/year in expense ratio"
```

---

## Priority Order
1. **P0**: Regular → Direct consolidation (same fund)
2. **P0**: AMC concentration reduction
3. **P1**: Underperformer replacement
4. **P1**: Different fund overlap resolution
5. **P2**: Asset allocation rebalancing

---

## Expected Output Example

### For Regular vs Direct:
```
EXIT: HDFC Flexi Cap Fund Regular Growth (₹5.2L)
REASON: Direct plan exists with 0.5% lower expense ratio. Saves ₹2,600/year.
EXIT SCORE: 8.5 (Cost: 10, Overlap: 9.5, Quality: 7)
```

### For Underperformer:
```
EXIT: Franklin India Small Cap Fund (₹3.8L)
REASON: Underperforming benchmark by 2.8%. Quality score: 4.2/10

ADD: Axis Small Cap Fund - Direct Growth (₹3.8L)
REASON: Top-rated small cap fund. Quality score: 8.5/10. Better risk-adjusted returns.
```

### For AMC Concentration:
```
EXIT: HDFC Small Cap Fund Regular (₹2.1L)
REASON: Reducing HDFC concentration from 22.5% to 18%. Among 9 HDFC funds, this has exit score 7.2.
```

---

## Technical Implementation Notes

1. **Detect Regular vs Direct pairs**: Normalize scheme names, strip "Regular"/"Direct" keywords
2. **Category matching**: Use AMFI category classification
3. **Exit score calculation**: Already implemented (Overlap×0.3 + Quality×0.25 + Tax×0.2 + Cost×0.15 + Fit×0.1)
4. **ADD score calculation**: Quality×0.4 + Performance×0.3 + Cost×0.2 + Category_fit×0.1
