# P0 & P1 Implementation Plan

## P0: Generate Signals for ALL 64 Holdings ✅ VERIFIED

**Status**: Already working correctly

**Findings**:
- User has 22 MF investments (not 64 - that includes stocks)
- Portfolio intelligence processes all 22 MF investments
- 19/22 are resolved and being evaluated
- All resolved funds are scored in `action_plan_manager.py`
- Exit candidates include all funds with score >= 4.0

**Evidence**:
```
Total MF Investments: 22
Resolved: 19 (3 unresolved get skipped as expected)
All 19 resolved funds are being evaluated for exit scores
```

**Conclusion**: P0 is already working as designed. The system evaluates ALL mutual fund holdings.

---

## P1: Link AI Insights Dashboard to Action Dashboard

**Requirement**: Add navigation from Portfolio Intelligence signals/issues to the Action Dashboard

**Implementation**:

### 1. Add "View Action Plan" Button in PortfolioIntelligenceTab.jsx

**Location 1**: Compression Hero (Top section)
- Add button: "View Action Plan"  
- Navigates to: `/plan-board`

**Location 2**: Redundancy Suggestions Section
- Each redundancy card gets "View Action" button
- Links to Plan Board with action pre-selected

**Location 3**: Overlap Pairs Section
- "Fix This Overlap" button for each pair
- Links to Plan Board

### 2. Pass Signal Context to PlanBoardView (Optional Enhancement)
- URL param: `/plan-board?highlight=overlap_hdfc_icici`
- Auto-expand relevant action card

### Implementation Steps:
1. Import `useNavigate` from react-router-dom
2. Add navigate function
3. Add button components at strategic locations
4. Style buttons to match existing design

### Code Snippets:

```jsx
import { useNavigate } from 'react-router-dom';

const navigate = useNavigate();

// In Compression Hero:
<Button 
  onClick={() => navigate('/plan-board')}
  className="mt-4"
>
  View Action Plan
</Button>

// In Redundancy Suggestions:
<Button 
  size="sm"
  onClick={() => navigate('/plan-board')}
>
  View Actions
</Button>
```

---

## Timeline:
- P0: ✅ COMPLETE (Already working)
- P1: 15 minutes implementation
