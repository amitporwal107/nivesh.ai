# Functional Requirements Document — NIVESH V2 FRONTEND
**Layer:** Nivesh V2 Frontend (Plan Board & Decision Engine UI Layer)
**Status:** VALIDATED AGAINST CODE — May 2026
**Validation Source:** `src/components/v2/`, `src/components/insights/`, `src/components/copilot/` (SaveAsPlanCard bridge)

---

## DOCUMENT NOTES — What "V2 Frontend" Means

> **V2 Frontend** = all UI surfaces that expose the V2.5 decision engine and V3 scoring outputs:
> - **`/components/v2/`** — the Plan Board: PlanBoardView, PlanHeroCard, ActionPlanView, ActionCard, SignalsWidget, HealthProjectionCard, V3ScoreBadges
> - **`/components/insights/`** — per-holding decision intelligence: PortfolioIntelligenceTab, V3PortfolioInsights, V3FundBreakdown, DecisionCard, DecisionVerdict, SwitchCostPanel, PortfolioBuilderView
>
> The `SaveAsPlanCard.jsx` in `/copilot/` is the **bridge** from scenario exploration to plan activation.
> Both V1 and V2 components live in the same React 19 app. The "V2" badge appears only on the Plan Board tab in Sidebar.js.

---

## 1. Module: Plan Board (V2 Action Plan UI)

### FR-FE-V2-001 — Plan Board View
| Field | Value |
|---|---|
| **Requirement ID** | FR-FE-V2-001 |
| **Module** | Plan Board |
| **Feature** | Active Plan + History Grid |
| **Priority** | Critical |
| **Source** | `src/components/v2/PlanBoardView.js` |
| **Status** | Live |

**APIs Called:**
- `GET /api/plans/active` — load active plan
- `GET /api/plans/history?limit=20` — plan history grid
- `POST /api/plans/generate` — generate new plan
- `GET /api/plans/active/health-projection` — projected health if all actions executed

**Layout:**
1. **Top bar** — "Generate New Plan" button + "Plan Board V2" header
2. **Active Plan Section** — `PlanHeroCard` + `ActionPlanView` (if plan exists) OR empty state CTA
3. **Plan History Grid** — `PlanCard` list of past plans (archived + completed)

**Empty State:** When user has no active plan → full-width CTA "Generate Your Action Plan" with 3-bullet description of what the engine does

**Acceptance Criteria:**
- User navigates to `#plan_board` tab → active plan loaded or empty state shown
- "Generate New Plan" → `POST /api/plans/generate` → preview plan rendered in PlanHeroCard
- Plan history shows last 20 plans, latest first
- Plan history shows completion stats (X/Y actions done)

---

### FR-FE-V2-002 — Plan Hero Card (V2.5 Summary)
| Field | Value |
|---|---|
| **Requirement ID** | FR-FE-V2-002 |
| **Module** | Plan Board |
| **Feature** | Portfolio Score Summary Hero |
| **Priority** | Critical |
| **Source** | `src/components/v2/PlanHeroCard.js` |
| **Status** | Live |

**Components Rendered:**
1. **Portfolio Score Donut** — 0-100 score with letter grade, coloured by severity
2. **Confidence Badge** — data completeness percentage (drives Low-Confidence Guardrail UI)
3. **Before → After Grid** — two columns: current state vs projected state if all actions taken
   - Freed capital (₹)
   - Tax impact (₹ liability)
   - Post-tax proceeds (₹)
   - Actions count (pending/done/skipped)
4. **Improvements Delta Pills** — specific gains: "Save ₹18,400/yr in fees" / "Reduce overlap 85% → 32%"
5. **Status Banners:**
   - `DEGRADED` — shown when Postgres unreachable; "Analytics partially available"
   - `DO-NOTHING` — shown when portfolio_score ≥ 75 and Rule 7 fires (PORTFOLIO_HEALTHY)
6. **Save as Active Plan button** — only shown on `preview` status plans

**Acceptance Criteria:**
- `preview` plan → "Save as Active Plan" button visible
- `active` plan → "Save" button hidden; plan in read mode
- `degraded: true` → degraded banner shown; analytics partially hidden
- Score ≥ 75 + no high-priority actions → Do-Nothing banner shown
- Before/After numbers match `freed_capital`, `tax_liability`, `post_tax_proceeds` from API

---

### FR-FE-V2-003 — Action Plan View
| Field | Value |
|---|---|
| **Requirement ID** | FR-FE-V2-003 |
| **Module** | Plan Board |
| **Feature** | Expanded Plan Detail + Actions List |
| **Priority** | Critical |
| **Source** | `src/components/v2/ActionPlanView.js` |
| **Status** | Live |

**Layout:**
1. **Plan Summary** (`PlanSummary.js`) — freed capital, tax impact breakdown per action
2. **Signals Widget** (`SignalsWidget.js`) — portfolio risk flags collapsed/expanded
3. **Actions List** — `ActionCard` per action, sorted by priority
4. **Refresh Button** — "Refresh Plan" → `POST /api/plans/generate` → new preview
5. **Plan Summary Text** — LLM-generated 200-word plain-English explanation (narrates deterministic decisions)

---

### FR-FE-V2-004 — Action Card
| Field | Value |
|---|---|
| **Requirement ID** | FR-FE-V2-004 |
| **Module** | Plan Board |
| **Feature** | Individual Action Item |
| **Priority** | Critical |
| **Source** | `src/components/v2/ActionCard.js` |
| **Status** | Live |

**Card Header:**
- Action type icon: EXIT (red arrow) / ADD (green plus) / SWITCH (blue arrows) / HOLD (grey)
- Action type badge: pill coloured by type
- Fund name (bold)
- Amount (₹ formatted)

**Card Body:**
- Reason text (deterministic, rule-cited)
- Reason codes as chips (e.g., `OVERLAP_CONSOLIDATION`, `AMC_CONCENTRATION_EXIT`)
- V3 Score Badges cluster: Q/H/E/A pills (see FR-FE-V2-006)
- Tax impact: "LTCG: ₹12,400 (12.5%)" or "Tax-pending" if buy_date unknown
- Confidence level: HIGH / MEDIUM / LOW

**Card Footer:**
- Status: PENDING / COMPLETED / SKIPPED (with timestamp if done)
- Mark as Done button (→ `PATCH /api/plans/{id}/actions/{aid}/status`)
- Skip button
- Thumbs up / Thumbs down feedback (→ `POST /api/plans/{id}/actions/{aid}/feedback`)
- Optional completion note (free text)

**Acceptance Criteria:**
- EXIT action card shows exit_score, tax impact, reason_text
- ADD action card shows add_score, reason_text, no tax row (new investment)
- SWITCH action shows switch_score, ₹ saving/year, payback period
- Mark Done → status chip updates to COMPLETED without page refresh
- Feedback submitted → thumbs icon toggles state

---

### FR-FE-V2-005 — Signals Widget
| Field | Value |
|---|---|
| **Requirement ID** | FR-FE-V2-005 |
| **Module** | Plan Board |
| **Feature** | Portfolio Risk Signals |
| **Priority** | High |
| **Source** | `src/components/v2/SignalsWidget.js`, `SignalDetailModal.js` |
| **Status** | Live |

**Signal Severities:** HIGH (red) / MEDIUM (amber) / LOW (grey)

**Signal Types:**
- `OVERLAP_REDUNDANCY` — two funds with >80% shared stocks
- `OVEREXPOSURE` — AMC/sector concentration above threshold
- `QUALITY_ISSUES` — fund danger classification = CRITICAL
- `ALLOCATION_GAP` — debt below risk-profile floor
- `COST_LEAK` — Regular plan savings > ₹5K/year

**Interaction:**
- Widget initially collapsed (shows count of HIGH signals)
- Expand → list of signal chips
- Click signal chip → `SignalDetailModal` with: title, description, impact ₹, affected funds, recommended actions

---

### FR-FE-V2-006 — V3 Score Badges
| Field | Value |
|---|---|
| **Requirement ID** | FR-FE-V2-006 |
| **Module** | Plan Board |
| **Feature** | Score Pill Cluster |
| **Priority** | High |
| **Source** | `src/components/v2/V3ScoreBadges.js` |
| **Status** | Live |

**Pills Displayed:** Q (Quality) / H (Health) / E (Exit) / A (Add)

**Colour Coding:**
| Score | Colour |
|---|---|
| ≥ 70 | Green |
| 50–69 | Amber |
| < 50 | Red |

**Guardrail Flag:** If any guardrail blocked an action → shows lock icon with tooltip

**Missing Primitives:** If `quality_missing > 2` → pill shows confidence indicator (lighter opacity + "~" prefix)

---

### FR-FE-V2-007 — Health Projection Card
| Field | Value |
|---|---|
| **Requirement ID** | FR-FE-V2-007 |
| **Module** | Plan Board |
| **Feature** | Before/After Health Projection |
| **Priority** | Medium |
| **Source** | `src/components/v2/HealthProjectionCard.jsx` |
| **Status** | Live |

**Displays:**
- Current portfolio health score vs projected score (if all pending actions completed)
- Component-level before/after: diversification / cost / performance / risk
- Delta arrows with ₹ or % impact

**API:** `GET /api/plans/active/health-projection`

---

## 2. Module: Per-Holding Decision Intelligence (V2 Insights Layer)

### FR-FE-V2-008 — Portfolio Intelligence Tab
| Field | Value |
|---|---|
| **Requirement ID** | FR-FE-V2-008 |
| **Module** | Insights — V2 |
| **Feature** | Fund Overlap & Concentration Analysis |
| **Priority** | Critical |
| **Source** | `src/components/insights/PortfolioIntelligenceTab.jsx` |
| **Status** | Live |

**Sections:**
1. **Compression Score Card** — "Your 14 funds effectively give you exposure to 8 unique stocks"
2. **Pairwise Overlap Matrix** — n×n heatmap: row/col = fund names, cell = overlap % (colour-coded)
3. **Top Stock Overexposure** — stocks appearing in ≥ 3 funds with combined weight
4. **Redundancy Suggestions** — "Remove [Fund X] — 89% of its exposure is already covered by [Fund Y]"
5. **What-If Simulator** — "Remove this fund" → recalculates compression score + overlap matrix

**Interactive:**
- Drag-to-resize panels
- Click cell → fund pair detail (shared stocks list)
- What-if: toggle fund off → immediate recalculation

**API:** `GET /api/intelligence/portfolio` (full intelligence payload)

---

### FR-FE-V2-009 — V3 Portfolio Insights
| Field | Value |
|---|---|
| **Requirement ID** | FR-FE-V2-009 |
| **Module** | Insights — V2 |
| **Feature** | Per-Fund V3 Score Leaderboard |
| **Priority** | Critical |
| **Source** | `src/components/insights/V3PortfolioInsights.jsx` |
| **Status** | Live |

**Sections:**
1. **Headline Tiles** — portfolio-level aggregates: Avg Quality / Funds at Risk / Cost Leakage ₹/yr / Overlap Pairs
2. **Fund Leaderboard** — sorted: CRITICAL → WARNING → OK → descending quality
   - Per fund: Quality/Health/Exit/Add scores, danger badge, explanation text
   - Expandable row → `V3FundBreakdown`
3. **Danger-Zone Tile** — CRITICAL funds highlighted with action CTAs

**API:** `GET /api/insights/v3-portfolio`

---

### FR-FE-V2-010 — V3 Fund Breakdown (Per-Holding Drill-Down)
| Field | Value |
|---|---|
| **Requirement ID** | FR-FE-V2-010 |
| **Module** | Insights — V2 |
| **Feature** | Expandable Fund Score Detail |
| **Priority** | High |
| **Source** | `src/components/insights/V3FundBreakdown.jsx` |
| **Status** | Live |

**Expanded Row Shows:**
- Q/H/E/A/SW pill cluster with numeric values
- Deterministic explanation paragraph (from `v3_explainer.py`)
- Component bars for Quality and Health (drill into what drove the score)
- Missing primitives list with "~" confidence indicator
- Switch score: value + recommended/not-recommended verdict

---

### FR-FE-V2-011 — Decision Card (Per-Holding Recommendation)
| Field | Value |
|---|---|
| **Requirement ID** | FR-FE-V2-011 |
| **Module** | Insights — V2 |
| **Feature** | "What Should I Do?" Unified Card |
| **Priority** | High |
| **Source** | `src/components/insights/DecisionCard.jsx` |
| **Status** | Live |

**Answers 4 Questions per holding:**
1. **WHY** — what triggered this verb (Exit/Switch/Add/Hold)?
2. **WHAT TO DO** — specific action (e.g., "Switch from Regular to Direct of HDFC Top 100")
3. **COST & TAX** — switch cost as % of corpus, broken down
4. **WORTH IT?** — yes/no based on whether expected alpha covers friction

**Action Verb Taxonomy:**
| Verb | Condition |
|---|---|
| STAY | No significant issue; good quality |
| SWITCH-TO-DIRECT | Same fund, Regular plan → save expense ratio |
| SWITCH-TO-PEER | Exit current fund; buy better peer in same category |
| EXIT-TO-CASH | Fund broken; fix isn't another fund |
| REVIEW | Low confidence or manager change |

---

### FR-FE-V2-012 — Decision Verdict
| Field | Value |
|---|---|
| **Requirement ID** | FR-FE-V2-012 |
| **Module** | Insights — V2 |
| **Feature** | Cost-Benefit Override Logic |
| **Priority** | Medium |
| **Source** | `src/components/insights/DecisionVerdict.jsx` |
| **Status** | Live |

**Hero Recommendation Banner with override logic:**
- If `expected_alpha < cost_over_3yr` → verdict = "DO NOT ADD" even if add_score is high
- Shows: "Adding more would cost ₹X over 3yr but deliver only ₹Y in alpha — not worth it"

---

### FR-FE-V2-013 — Switch Cost Panel
| Field | Value |
|---|---|
| **Requirement ID** | FR-FE-V2-013 |
| **Module** | Insights — V2 |
| **Feature** | Switch Cost Breakdown |
| **Priority** | High |
| **Source** | `src/components/insights/SwitchCostPanel.jsx` |
| **Status** | Live |

**Breakdown Items:**
- Exit load % + ₹ amount
- Tax drag % + ₹ amount (LTCG/STCG)
- Slippage % (bid-ask estimate)
- Total switch cost ₹
- Annual saving ₹ (expense ratio delta × corpus)
- Payback months (switch_cost / annual_saving × 12)
- Alpha % over peer (expected outperformance)

---

### FR-FE-V2-014 — Portfolio Builder View
| Field | Value |
|---|---|
| **Requirement ID** | FR-FE-V2-014 |
| **Module** | Insights — V2 |
| **Feature** | Blank-Slate Portfolio Design |
| **Priority** | Medium |
| **Source** | `src/components/insights/PortfolioBuilderView.jsx` |
| **Status** | Live |

**Flow:**
1. Empty-state entry point (user has no holdings OR clicks "Design New Portfolio")
2. Risk-profile chat (free-text input → AI extracts risk + goals + horizon)
3. System generates proposed portfolio (fund list + allocation %)
4. What-if simulation: adjust SIP amount / time horizon → project corpus
5. PDF export or WhatsApp-ready summary

**API:** `POST /api/portfolio-builder/generate`

---

## 3. Module: Copilot → V2 Bridge

### FR-FE-V2-015 — Save As Plan Card
| Field | Value |
|---|---|
| **Requirement ID** | FR-FE-V2-015 |
| **Module** | Plan Board — Bridge |
| **Feature** | Generate Plan from Scenario |
| **Priority** | High |
| **Source** | `src/components/copilot/SaveAsPlanCard.jsx` |
| **Status** | Live |

**Description:** The only copilot component that directly invokes the V2 engine. Appears at the bottom of scenario exploration in `AICopilotView`.

**On Click:**
1. `POST /api/plans/generate` → creates preview plan
2. `POST /api/plans/{id}/save` → activates plan
3. Dispatches browser event `nivesh:plan-saved`
4. `PlanBoardView` listens for this event → re-fetches active plan
5. Shows "Plan Generated! View in Plan Board" toast notification

**State Transitions:**
```
Scenario explored → SaveAsPlanCard CTA visible → onClick 
  → plan.status: preview → active 
  → PlanBoardView refreshes
```

---

## 4. Module: Plan History

### FR-FE-V2-016 — Plan Card (History Grid)
| Field | Value |
|---|---|
| **Requirement ID** | FR-FE-V2-016 |
| **Module** | Plan Board |
| **Feature** | Past Plans Summary Card |
| **Priority** | Medium |
| **Source** | `src/components/v2/PlanCard.js` |
| **Status** | Live |

**Card Shows:**
- Plan creation date
- Status pill: ACTIVE / COMPLETED / ARCHIVED
- Action summary: "3 EXIT, 1 ADD, 1 SWITCH"
- Completion stats: "2/5 actions completed (40%)"
- Portfolio score at time of creation
- "Expand" button → shows full ActionPlanView for that historical plan

---

## 5. Gap Analysis — V2 Frontend (Docs vs Code)

| Documented Feature | Code Status | Notes |
|---|---|---|
| HOLD action type rendering | **NOT IMPLEMENTED** | No HOLD action card variant; V3.1 planned |
| Insight severity colour coding | **PARTIAL** | HIGH signals show red in SignalsWidget; per-insight severity chips not in InsightsView |
| Mobile-optimised Plan Board | **PARTIAL** | Tailwind responsive classes present; not thoroughly tested on mobile |
| WhatsApp-ready plan export | **DOCUMENTED** | In PortfolioBuilderView but endpoint integration status unclear |
| Dark mode on Plan Board | **PARTIAL** | dark: Tailwind prefixes; not all V2 cards tested in dark |

---

## 6. Requirement Traceability Matrix

| Req ID | Feature | Status | Component | API Endpoint | Priority |
|---|---|---|---|---|---|
| FR-FE-V2-001 | Plan Board Hub | IMPLEMENTED | PlanBoardView.js | GET /api/plans/active | Critical |
| FR-FE-V2-002 | Hero Card | IMPLEMENTED | PlanHeroCard.js | GET /api/plans/active | Critical |
| FR-FE-V2-003 | Action Plan View | IMPLEMENTED | ActionPlanView.js | GET /api/plans/{id} | Critical |
| FR-FE-V2-004 | Action Card | IMPLEMENTED | ActionCard.js | PATCH /api/plans/{id}/actions/{aid}/status | Critical |
| FR-FE-V2-005 | Signals Widget | IMPLEMENTED | SignalsWidget.js | (from plan payload) | High |
| FR-FE-V2-006 | Score Badges | IMPLEMENTED | V3ScoreBadges.js | (from plan payload) | High |
| FR-FE-V2-007 | Health Projection | IMPLEMENTED | HealthProjectionCard.jsx | GET /api/plans/active/health-projection | Medium |
| FR-FE-V2-008 | Portfolio Intelligence | IMPLEMENTED | PortfolioIntelligenceTab.jsx | GET /api/intelligence/portfolio | Critical |
| FR-FE-V2-009 | V3 Score Leaderboard | IMPLEMENTED | V3PortfolioInsights.jsx | GET /api/insights/v3-portfolio | Critical |
| FR-FE-V2-010 | Fund Breakdown | IMPLEMENTED | V3FundBreakdown.jsx | (from v3-portfolio) | High |
| FR-FE-V2-011 | Decision Card | IMPLEMENTED | DecisionCard.jsx | (from holdings-enriched) | High |
| FR-FE-V2-012 | Decision Verdict | IMPLEMENTED | DecisionVerdict.jsx | (from holdings-enriched) | Medium |
| FR-FE-V2-013 | Switch Cost Panel | IMPLEMENTED | SwitchCostPanel.jsx | (from holdings-enriched) | High |
| FR-FE-V2-014 | Portfolio Builder | IMPLEMENTED | PortfolioBuilderView.jsx | POST /api/portfolio-builder/generate | Medium |
| FR-FE-V2-015 | Save As Plan | IMPLEMENTED | SaveAsPlanCard.jsx | POST /api/plans/generate | High |
| FR-FE-V2-016 | Plan History | IMPLEMENTED | PlanCard.js | GET /api/plans/history | Medium |

---

*Document generated May 2026. Validated against commit on branch `nivesh-v2-copilot`.*
