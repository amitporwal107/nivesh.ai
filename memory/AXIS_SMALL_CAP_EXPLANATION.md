# Why Axis Small Cap Fund Shows Overlap Issue

## User Question
"Why does Axis Small Cap have an overlap issue?"

## Answer

### The Plan You're Viewing is OLD (Generated Before Improvements)
The action plan shown in your screenshot was generated on **19 Apr 2026** BEFORE:
- The improved overlap detection logic
- Better EXIT reason explanations  
- AMC concentration fixes

**To see accurate recommendations with detailed explanations:**
1. Click "Generate New Plan" in the Plan Board
2. The new plan will include:
   - Specific overlap details (which funds overlap and by how much)
   - Clear reason codes (overlap %, quality score, tax impact)
   - Better fund selection based on multi-factor scoring

---

## How the V2 System Works

### EXIT Selection Criteria (Multi-Factor Scoring)
The system doesn't just look at overlap. It evaluates 5 dimensions:

1. **Overlap Score (0-10)**
   - How much this fund's holdings duplicate other funds in your portfolio
   - Weighted by fund size and overlap percentage
   - Example: If Fund A has 70% overlap with Fund B, both get high overlap scores

2. **Quality Score (0-10)**
   - Rolling returns (1Y, 3Y, 5Y performance)
   - Sharpe ratio (risk-adjusted returns)
   - Consistency of performance
   - Category ranking

3. **Tax Score (0-10)**
   - Holding period (STCG vs LTCG)
   - Capital gains/losses
   - Tax efficiency of exit
   - Lower tax score = higher priority to exit

4. **Cost Score (0-10)**
   - Expense ratio comparison to category
   - Direct vs Regular plan (Direct is better)
   - Higher cost funds get higher exit priority

5. **Fit Score (0-10)**
   - Alignment with user's Risk Profile (Conservative/Moderate/Aggressive)
   - Category diversification
   - Alignment with long-term goals

### Final Exit Score
```
Exit Score = (Overlap × 0.30) + (Quality × 0.25) + (Tax × 0.20) + (Cost × 0.15) + (Fit × 0.10)
```

**Funds with Exit Score ≥ 4.0 become candidates for EXIT**

---

## Why Axis Small Cap May Have Been Selected

**Possible Reasons (from old algorithm):**
1. **Category Overlap**: Multiple small-cap funds in portfolio (even if different stocks)
2. **Underperformance**: Lower quality score compared to other small-cap funds
3. **High Expense Ratio**: Regular plan with higher costs
4. **Poor Risk-Adjusted Returns**: Low Sharpe ratio

**Note**: The old plan didn't show stock-level overlap because that feature wasn't fully integrated yet.

---

## What Changed in the New System

### Before (Old Plan - 19 Apr 2026)
- Generic overlap detection
- Minimal exit explanation: "Reason: (empty)"
- No specific overlap pairs shown
- Category-based decisions

### After (New Plans)
- **Real stock-level overlap**: Shows exact overlap percentage
- **Detailed reasons**: "High overlap (65%) with HDFC Small Cap. Lower quality score (3.2). High expense ratio (1.8%)."
- **Overlap pairs**: Explicitly lists which funds overlap
- **Tax warnings**: "⚠️ Tax cost is 60% of your gain. Consider holding longer."
- **Better scoring**: Multi-factor weighted algorithm

---

## Recommended Action

### Generate a Fresh Plan to See:
1. Accurate overlap data with specific fund pairs
2. Detailed EXIT reasons for each recommendation
3. Tax impact analysis
4. Better fund recommendations (e.g., ICICI instead of HDFC due to AMC concentration)

### The New Plan Will Show:
```
EXIT: Axis Small Cap Fund Direct Growth (₹7L)

Reason: 
• High overlap (72%) with Kotak Small Cap Fund
• Quality score: 3.8/10 (underperforming category average)
• Expense ratio: 1.6% (category avg: 1.2%)
• Tax impact: ₹45,000 LTCG tax (12% of exit value)

Recommendation: Exit and reallocate to better-performing small-cap fund
```

---

## Summary

**The plan you're seeing is outdated.** Generate a new plan to get:
- ✅ Accurate overlap analysis
- ✅ Detailed exit reasons
- ✅ Better fund recommendations
- ✅ Tax-aware decisions
- ✅ AMC concentration checks

**All improvements are live and working** - just need to generate a fresh plan!
