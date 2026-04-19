# Nivesh Copilot V2 — UI Wireframes & Structure
**Version:** 2.0  
**Date:** April 2026

---

## 1. UI PHILOSOPHY SHIFT

### V1 (Current) → V2 (New)

| Aspect | V1 | V2 |
|--------|----|----|
| **Primary Focus** | Analytics & Insights | Action Plan |
| **User Intent** | "Show me data" | "Tell me what to do" |
| **Navigation** | Tab-based (Insights, Portfolio, Chat) | Plan-first (Actions primary) |
| **Persistence** | None (ephemeral) | Plan always visible |
| **Call-to-Action** | Implicit (user decides) | Explicit ("Mark as Done") |

---

## 2. INFORMATION ARCHITECTURE

```
┌─────────────────────────────────────────────────────────┐
│  HEADER                                                 │
│  ┌──────────────────┬──────────────────┐              │
│  │ Nivesh.AI Logo   │  [V1 ⇄ V2 Toggle] │              │
│  └──────────────────┴──────────────────┘              │
└─────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────┐
│  SECTION 1: ACTION PLAN (Primary - Always Visible)     │
│  ┌─────────────────────────────────────────────────┐   │
│  │  Your Action Plan                               │   │
│  │  Progress: ████████░░ 2/3 Completed (66%)       │   │
│  │                                                  │   │
│  │  ┌─────────────────────────────────────────┐   │   │
│  │  │ ❌ Action 1: EXIT HDFC Flexi Cap       │   │   │
│  │  │    Amount: ₹4,80,000                    │   │   │
│  │  │    Reason: 95% overlap                  │   │   │
│  │  │    Tax: ₹0 (LTCG within exemption)     │   │   │
│  │  │    [✓ Mark as Done] [Skip]             │   │   │
│  │  └─────────────────────────────────────────┘   │   │
│  │                                                  │   │
│  │  ┌─────────────────────────────────────────┐   │   │
│  │  │ ✅ Action 2: EXIT Reliance Industries  │   │   │
│  │  │    Status: COMPLETED (Apr 20, 2026)     │   │   │
│  │  └─────────────────────────────────────────┘   │   │
│  │                                                  │   │
│  │  [Refresh Plan] [View Details]                 │   │
│  └─────────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────┐
│  SECTION 2: PORTFOLIO SIGNALS (Collapsible)            │
│  ┌─────────────────────────────────────────────────┐   │
│  │  Portfolio Signals  [▼ Expand]                  │   │
│  │  • High Overlap (₹4.8L duplicate)               │   │
│  │  • Overexposure to Financial sector (35%)       │   │
│  │  • 1 underperforming fund                       │   │
│  └─────────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────┐
│  SECTION 3: DEEP ANALYTICS (Optional - Collapsed)      │
│  ┌─────────────────────────────────────────────────┐   │
│  │  Deep Analytics  [▼ Expand]                     │   │
│  │  [Tabs: Overview | Intelligence | Chat | Admin] │   │
│  └─────────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────────┘
```

---

## 3. DETAILED WIREFRAMES

### 3.1 Action Plan Section (Primary View)

```
┌─────────────────────────────────────────────────────────────┐
│  Your Action Plan                                           │
│  Updated: Apr 19, 2026 • Plan v1                            │
├─────────────────────────────────────────────────────────────┤
│                                                             │
│  Progress Tracker                                           │
│  ████████████████████████████░░░░░░░░░░░░  66% Complete   │
│  2 of 3 actions completed                                   │
│                                                             │
├─────────────────────────────────────────────────────────────┤
│                                                             │
│  ┌───────────────────────────────────────────────────────┐ │
│  │ 🔴 Action 1: EXIT Mutual Fund                         │ │
│  │                                                        │ │
│  │ Fund: HDFC Flexi Cap Direct Plan Growth               │ │
│  │ Amount: ₹4,80,000                                      │ │
│  │ Confidence: HIGH                                       │ │
│  │                                                        │ │
│  │ Why Exit?                                              │ │
│  │ • 95% overlap with HDFC Flexi Cap Fund Growth         │ │
│  │ • Underperforming category by 3%                      │ │
│  │ • High expense ratio (1.2%)                           │ │
│  │                                                        │ │
│  │ Tax Impact:                                            │ │
│  │ • Holding period: 1.2 years (LTCG eligible)           │ │
│  │ • Capital gain: ₹80,000                               │ │
│  │ • Tax liability: ₹0 (within ₹1L exemption)            │ │
│  │ • Post-tax proceeds: ₹4,80,000                        │ │
│  │                                                        │ │
│  │ Status: PENDING                                        │ │
│  │                                                        │ │
│  │ [✓ Mark as Done] [Skip This Action] [View Details]   │ │
│  └───────────────────────────────────────────────────────┘ │
│                                                             │
│  ┌───────────────────────────────────────────────────────┐ │
│  │ ✅ Action 2: EXIT Stock                              │ │
│  │                                                        │ │
│  │ Stock: Reliance Industries Ltd.                       │ │
│  │ Amount: ₹2,50,000                                      │ │
│  │                                                        │ │
│  │ Status: COMPLETED                                      │ │
│  │ Completed on: Apr 20, 2026                            │ │
│  │ Note: "Sold via Zerodha"                              │ │
│  │                                                        │ │
│  │ [View Details]                                         │ │
│  └───────────────────────────────────────────────────────┘ │
│                                                             │
│  ┌───────────────────────────────────────────────────────┐ │
│  │ 🟢 Action 3: ADD Debt Fund                           │ │
│  │                                                        │ │
│  │ Fund: HDFC Corporate Bond Fund Direct Growth          │ │
│  │ Amount: ₹3,00,000                                      │ │
│  │ Confidence: HIGH                                       │ │
│  │                                                        │ │
│  │ Why Add?                                               │ │
│  │ • Portfolio lacks debt allocation (5% → target 20%)   │ │
│  │ • Low correlation with equity                         │ │
│  │ • Reduces portfolio volatility                        │ │
│  │                                                        │ │
│  │ Status: PENDING                                        │ │
│  │                                                        │ │
│  │ [✓ Mark as Done] [Skip This Action] [View Details]   │ │
│  └───────────────────────────────────────────────────────┘ │
│                                                             │
├─────────────────────────────────────────────────────────────┤
│                                                             │
│  Summary                                                    │
│  • Freed capital (post-tax): ₹7,09,500                     │
│  • Reinvestment plan: 42% debt, 58% equity                 │
│  • Tax efficiency: 97.2%                                    │
│                                                             │
│  [🔄 Refresh Plan] [📊 View Impact Simulation]            │
│                                                             │
└─────────────────────────────────────────────────────────────┘
```

---

### 3.2 Portfolio Signals Widget (Collapsed)

```
┌─────────────────────────────────────────────────────────────┐
│  Portfolio Signals  [▼ Show Details]                        │
├─────────────────────────────────────────────────────────────┤
│                                                             │
│  ⚠️  3 signals detected:                                    │
│                                                             │
│  🔴 High Overlap — ₹4.8L locked in duplicate holdings      │
│  🟡 Overexposure — 35% in Financial sector                 │
│  🟠 Weak Performance — 1 fund underperforming category     │
│                                                             │
│  [👁️ View All Signals]                                     │
│                                                             │
└─────────────────────────────────────────────────────────────┘
```

---

### 3.3 Portfolio Signals Widget (Expanded)

```
┌─────────────────────────────────────────────────────────────┐
│  Portfolio Signals  [▲ Hide Details]                        │
├─────────────────────────────────────────────────────────────┤
│                                                             │
│  ┌───────────────────────────────────────────────────────┐ │
│  │ 🔴 Signal 1: High Overlap / Redundancy                │ │
│  │    Severity: HIGH                                      │ │
│  │                                                        │ │
│  │    Problem:                                            │ │
│  │    2 of your mutual funds hold 95% similar stocks.    │ │
│  │                                                        │ │
│  │    Impact:                                             │ │
│  │    ₹4,80,000 locked in duplicate holdings.            │ │
│  │    Not getting diversification benefit.                │ │
│  │                                                        │ │
│  │    Affected Assets:                                    │ │
│  │    • HDFC Flexi Cap Direct (₹4.8L)                    │ │
│  │    • HDFC Flexi Cap Regular (₹4.5L)                   │ │
│  │                                                        │ │
│  │    Recommended Action:                                 │ │
│  │    EXIT one of the overlapping funds                  │ │
│  │    → See Action 1 in your plan                        │ │
│  │                                                        │ │
│  │    [View Overlap Details] [Dismiss Signal]            │ │
│  └───────────────────────────────────────────────────────┘ │
│                                                             │
│  ┌───────────────────────────────────────────────────────┐ │
│  │ 🟡 Signal 2: Overexposure / Concentration Risk        │ │
│  │    Severity: MEDIUM                                    │ │
│  │                                                        │ │
│  │    Problem:                                            │ │
│  │    35% of portfolio in Financial Services sector.     │ │
│  │                                                        │ │
│  │    Impact:                                             │ │
│  │    High sector concentration risk.                    │ │
│  │    Target: < 25% per sector                           │ │
│  │                                                        │ │
│  │    Top Exposures:                                      │ │
│  │    • HDFC Bank: 4.9% (₹3.2L)                          │ │
│  │    • ICICI Bank: 3.8% (₹2.5L)                         │ │
│  │    • Axis Bank: 2.1% (₹1.4L)                          │ │
│  │                                                        │ │
│  │    Recommended Action:                                 │ │
│  │    REDUCE exposure to Financial sector                │ │
│  │    → See Action 2 in your plan                        │ │
│  │                                                        │ │
│  │    [View Sector Breakdown] [Dismiss Signal]           │ │
│  └───────────────────────────────────────────────────────┘ │
│                                                             │
│  ┌───────────────────────────────────────────────────────┐ │
│  │ 🟠 Signal 3: Performance / Quality Issues             │ │
│  │    Severity: MEDIUM                                    │ │
│  │                                                        │ │
│  │    Problem:                                            │ │
│  │    1 fund underperforming its category.               │ │
│  │                                                        │ │
│  │    Impact:                                             │ │
│  │    Missing out on ₹45,000 in potential returns.       │ │
│  │                                                        │ │
│  │    Weak Performers:                                    │ │
│  │    • XYZ Large Cap Fund                               │ │
│  │      1Y return: 8.2% vs category avg: 12.5%           │ │
│  │      High expense ratio: 1.8%                         │ │
│  │                                                        │ │
│  │    Recommended Action:                                 │ │
│  │    EXIT underperforming fund                          │ │
│  │    → Covered in Action 1                              │ │
│  │                                                        │ │
│  │    [View Performance Report] [Dismiss Signal]         │ │
│  └───────────────────────────────────────────────────────┘ │
│                                                             │
└─────────────────────────────────────────────────────────────┘
```

---

### 3.4 Deep Analytics Section (Collapsed)

```
┌─────────────────────────────────────────────────────────────┐
│  Deep Analytics  [▼ Explore More]                          │
├─────────────────────────────────────────────────────────────┤
│                                                             │
│  Want to dig deeper? Explore detailed charts, tables,      │
│  and insights.                                              │
│                                                             │
│  [📊 View Analytics Dashboard]                             │
│                                                             │
└─────────────────────────────────────────────────────────────┘
```

---

### 3.5 Deep Analytics Section (Expanded)

This becomes the current V1 Insights tabs:

```
┌─────────────────────────────────────────────────────────────┐
│  Deep Analytics  [▲ Collapse]                              │
├─────────────────────────────────────────────────────────────┤
│                                                             │
│  [Overview] [Portfolio Intelligence] [AI Copilot] [Admin]  │
│                                                             │
│  ┌───────────────────────────────────────────────────────┐ │
│  │                                                        │ │
│  │  (Current V1 Insights content goes here)              │ │
│  │  - Compression Hero                                    │ │
│  │  - Top Stocks Panel                                    │ │
│  │  - Overlap Heatmap (with drill-down)                  │ │
│  │  - Sector Exposure                                     │ │
│  │  - etc.                                                │ │
│  │                                                        │ │
│  └───────────────────────────────────────────────────────┘ │
│                                                             │
└─────────────────────────────────────────────────────────────┘
```

---

## 4. VERSION TOGGLE UI

### 4.1 Login Page Toggle

```
┌─────────────────────────────────────────────────────────────┐
│                                                             │
│                    NIVESH.AI                                │
│          AI-Powered Wealth Management                       │
│                                                             │
│  ┌──────────────────────────────────────────────────────┐  │
│  │  [Google Sign In]                                     │  │
│  └──────────────────────────────────────────────────────┘  │
│                                                             │
│  ┌──────────────────────────────────────────────────────┐  │
│  │  ☑️  Try New Action Plan Experience (Beta)          │  │
│  │      Get personalized action plan with your portfolio │  │
│  └──────────────────────────────────────────────────────┘  │
│                                                             │
└─────────────────────────────────────────────────────────────┘
```

---

### 4.2 Dashboard Header Toggle

```
┌─────────────────────────────────────────────────────────────┐
│  Nivesh.AI          [Dashboard ▼] [Insights] [Profile]     │
│                                                             │
│  Dropdown Menu:                                             │
│  ┌────────────────────────────────────┐                    │
│  │  ◉ V2: Action Plan View            │                    │
│  │  ○ V1: Dashboard View (Classic)    │                    │
│  │  ──────────────────────────────    │                    │
│  │  Settings                           │                    │
│  │  Help                               │                    │
│  │  Logout                             │                    │
│  └────────────────────────────────────┘                    │
└─────────────────────────────────────────────────────────────┘
```

---

## 5. USER FLOWS

### 5.1 First-Time User (Plan Creation)

```
1. User logs in
     ↓
2. No active plan → Show "Generate Plan" CTA
     ↓
3. User clicks "Generate Your Action Plan"
     ↓
4. Backend: Compute signals + actions (loading: 5-10s)
     ↓
5. Show Plan Preview Modal:
   ┌──────────────────────────────────────┐
   │  Your Action Plan is Ready!          │
   │  We detected 3 key issues:           │
   │  • High overlap (₹4.8L)              │
   │  • Overexposure to Financial         │
   │  • 1 weak performer                  │
   │                                      │
   │  Recommended Actions:                │
   │  1. EXIT HDFC Flexi Cap (₹4.8L)     │
   │  2. EXIT Reliance (₹2.5L)           │
   │  3. ADD Debt Fund (₹3L)             │
   │                                      │
   │  Total freed capital: ₹7.1L          │
   │  Tax impact: ₹20K                    │
   │                                      │
   │  [Save This Plan] [Modify] [Cancel] │
   └──────────────────────────────────────┘
     ↓
6. User clicks "Save This Plan"
     ↓
7. Plan saved → Redirect to Action Plan view
     ↓
8. User sees full plan with 3 actions
```

---

### 5.2 Returning User (View Active Plan)

```
1. User logs in
     ↓
2. Has active plan → Auto-redirect to Action Plan view
     ↓
3. User sees:
   • Progress tracker (2/3 completed)
   • Action 1: PENDING
   • Action 2: COMPLETED ✓
   • Action 3: PENDING
     ↓
4. User clicks "Mark as Done" on Action 1
     ↓
5. Modal: "Confirm Action Completion"
   ┌──────────────────────────────────────┐
   │  Did you complete this action?       │
   │                                      │
   │  ✓ Exited HDFC Flexi Cap (₹4.8L)    │
   │                                      │
   │  [Add Note (optional)]               │
   │  [ Redeemed via Groww app   ]        │
   │                                      │
   │  [✓ Confirm] [Cancel]                │
   └──────────────────────────────────────┘
     ↓
6. Action marked COMPLETED
     ↓
7. Progress bar updates: 3/3 (100%)
     ↓
8. Show completion modal:
   ┌──────────────────────────────────────┐
   │  🎉 All Actions Completed!           │
   │                                      │
   │  You've successfully optimized your  │
   │  portfolio. Well done!               │
   │                                      │
   │  [Generate New Plan] [View Summary]  │
   └──────────────────────────────────────┘
```

---

### 5.3 Portfolio Update → Plan Refresh

```
1. User uploads new CAS
     ↓
2. Portfolio updated → System detects change
     ↓
3. Banner appears:
   ┌──────────────────────────────────────┐
   │  ℹ️  Portfolio Updated                │
   │  Your action plan may be outdated.   │
   │  [Refresh Plan] [Keep Current Plan]  │
   └──────────────────────────────────────┘
     ↓
4. User clicks "Refresh Plan"
     ↓
5. Backend: Recompute signals + actions
     ↓
6. Show "Plan Updated" modal:
   ┌──────────────────────────────────────┐
   │  Plan Refreshed (v2)                 │
   │                                      │
   │  Changes:                            │
   │  • Action 1: No change               │
   │  • Action 2: Amount updated (₹2.5L → ₹2.8L) │
   │  • Action 3: NEW - Exit XYZ Fund    │
   │                                      │
   │  [View New Plan] [Compare Versions]  │
   └──────────────────────────────────────┘
     ↓
7. Old plan archived to plan_history
     ↓
8. New plan (v2) becomes active
```

---

## 6. RESPONSIVE DESIGN

### Mobile View (< 768px)

```
┌──────────────────────────┐
│  [☰] Nivesh.AI   [👤]    │
├──────────────────────────┤
│                          │
│  Your Action Plan        │
│  Progress: 66%           │
│  ████████░░░             │
│                          │
│  ┌────────────────────┐ │
│  │ Action 1           │ │
│  │ EXIT HDFC Flexi    │ │
│  │ ₹4.8L              │ │
│  │ [Details ▼]        │ │
│  └────────────────────┘ │
│                          │
│  ┌────────────────────┐ │
│  │ Action 2 ✓         │ │
│  │ COMPLETED          │ │
│  └────────────────────┘ │
│                          │
│  [Refresh]              │
│                          │
├──────────────────────────┤
│  Signals [▼]            │
├──────────────────────────┤
│  Analytics [▼]          │
└──────────────────────────┘
```

---

## 7. INTERACTION STATES

### Action Card States

**PENDING:**
```
┌─────────────────────────────────┐
│ 🔴 Action 1: EXIT               │
│ ...                             │
│ [✓ Mark as Done] [Skip]        │
└─────────────────────────────────┘
```

**COMPLETED:**
```
┌─────────────────────────────────┐
│ ✅ Action 2: EXIT               │
│ Status: COMPLETED               │
│ Completed on: Apr 20, 2026      │
│ [View Details]                  │
└─────────────────────────────────┘
```

**SKIPPED:**
```
┌─────────────────────────────────┐
│ ⊘ Action 3: ADD                │
│ Status: SKIPPED                 │
│ Skipped on: Apr 21, 2026        │
│ [Undo Skip]                     │
└─────────────────────────────────┘
```

---

## 8. ACCESSIBILITY

- ✅ ARIA labels for all interactive elements
- ✅ Keyboard navigation support (Tab, Enter, Esc)
- ✅ Screen reader friendly
- ✅ High contrast mode support
- ✅ Focus indicators visible

---

## 9. ANIMATION & TRANSITIONS

- Progress bar fills smoothly (0.5s ease)
- Action cards expand/collapse (0.3s ease)
- Signal widget expand/collapse (0.3s ease)
- Success animations on action completion
- Loading spinners during plan generation

---

**Document Version:** 1.0  
**Last Updated:** 2026-04-19  
**Author:** E1 Agent  
**Status:** Draft for Review
