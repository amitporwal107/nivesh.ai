# Action Dashboard Enhancements - Complete Specification

**Document:** Implementation Roadmap  
**Date:** April 19, 2026  
**Status:** IN PROGRESS

---

## ✅ Completed in This Session

### 1. AMC Concentration Check
- ✅ Updated `_suggest_debt_fund()` to accept `excluded_amcs` parameter
- ✅ Current HDFC exposure: **35.1%** (should be <15%)
- ✅ Debt fund suggestion now avoids HDFC, suggests:
  - ICICI Prudential Corporate Bond (5-Star)
  - Axis Treasury Advantage (4-Star)
  - SBI Magnum Gilt (4-Star)

**Next:** Calculate AMC exposure in `generate_plan()` and pass to `_suggest_debt_fund()`

---

## 🚧 In Progress

### 2. Tax Calculation Breakdown UI
**Location:** `/app/frontend/src/components/v2/PlanCard.js` (expanded section)

**Add to expanded action details:**
```jsx
{action.type === "EXIT" && (
  <div className="tax-breakdown">
    <h5>Tax Calculation (STCG/LTCG)</h5>
    <table>
      <tr><td>Current Value</td><td>₹{action.amount}</td></tr>
      <tr><td>Invested Amount</td><td>₹{invested}</td></tr>
      <tr><td>Capital Gain</td><td>₹{gain}</td></tr>
      <tr><td>Holding Period</td><td>{days} days ({years} years)</td></tr>
      <tr><td>Tax Type</td><td>{isLTCG ? "LTCG (10%)" : "STCG (15%)"}</td></tr>
      <tr><td>Tax Liability</td><td>₹{tax}</td></tr>
      <tr><td>Post-tax Proceeds</td><td>₹{postTax}</td></tr>
    </table>
    <div className="disclaimer">
      ⚠️ This calculation does not consider your tax bracket
    </div>
  </div>
)}
```

---

### 3. Action Status Workflow

**Backend API:** `/app/backend/routes/plans.py`

**New Endpoint:**
```python
@router.patch("/{plan_id}/actions/{action_id}/status")
async def update_action_status(
    plan_id: str,
    action_id: str,
    status: str,  # PENDING, IN_PROGRESS, DONE, REVIEW
    user_id: str = Depends(get_current_user)
):
    # Update action status
    # Track timestamp
    # Return updated plan
```

**Frontend:** Add status dropdown to each action card

---

### 4. Feedback System

**Backend Schema:** Add to action object
```python
{
  "action_id": "act_001",
  "feedback": {
    "useful": true/false/null,
    "comment": "string",
    "submitted_at": "ISO timestamp"
  }
}
```

**Frontend:** Add feedback UI below action details
```jsx
<div className="feedback-section">
  <p>Was this recommendation useful?</p>
  <button>👍 Yes</button>
  <button>👎 No</button>
  <textarea placeholder="Optional feedback"></textarea>
</div>
```

---

## 📋 Remaining Tasks

### Phase 1 Tasks:

- [ ] Calculate AMC exposure in `generate_plan()`
- [ ] Pass `excluded_amcs` to `_suggest_debt_fund()`
- [ ] Add tax breakdown UI to expanded action view
- [ ] Add tax disclaimer
- [ ] Create status update API endpoint
- [ ] Add status dropdown to action cards
- [ ] Track action completion timestamps

### Phase 2 Tasks:

- [ ] Add minimize/expand toggle to action cards
- [ ] Fix text truncation (show full fund names)
- [ ] Add feedback UI (👍/👎 + comment)
- [ ] Save feedback to database
- [ ] Track feedback analytics

### Phase 3 Tasks (Next Session):

- [ ] Generate comprehensive signals for ALL 64 holdings
- [ ] Link signals in Insights Dashboard to actions
- [ ] Add "View Action Plan" button on each signal
- [ ] Detect all issue types:
  - [ ] Fund overlaps (all pairs)
  - [ ] AMC concentration
  - [ ] Stock concentration
  - [ ] Regular vs Direct duplicates
  - [ ] Expense ratio leaks
  - [ ] Quality/performance issues
  - [ ] Asset allocation gaps

---

## Current AMC Exposure (User: priyankamantri@gmail.com)

| Rank | AMC | Exposure | Funds | Value | Status |
|------|-----|----------|-------|-------|--------|
| 1 | HDFC | **35.1%** | 9 | ₹22.8L | ⚠️ CRITICAL |
| 2 | ICICI | 14.6% | 3 | ₹9.5L | ✅ OK |
| 3 | Parag Parikh | 11.3% | 3 | ₹7.3L | ✅ OK |
| 4 | Aditya Birla | 10.8% | 1 | ₹7.0L | ✅ OK |
| 5 | Axis | 10.3% | 1 | ₹6.7L | ✅ OK |

**Recommendation:** Avoid suggesting any HDFC funds. Diversify into ICICI/Axis/SBI/Kotak.

---

## Files Modified

- `/app/backend/services/action_plan_manager.py` - Added AMC-aware debt fund suggestion
- `/app/memory/ACTION_DASHBOARD_ENHANCEMENTS_SPEC.md` - This document

---

**Status:** Step 1 complete (AMC concentration). Continuing with Steps 2-4...
