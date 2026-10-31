# Functionality Verification Report — Daily Trader Copilot visual answer: Q15 daily review (backend, Release 3)

- **Branch:** feat/dtc-r3-daily-review (based on feat/dtc-r2-answers, PR #422)
- **Date:** 2026-10-31
- **Author:** Claude (FULL_STACK_DEVELOPER + QA_ENGINEER)
- **Environment:** unit tests in a `nivesh/backend:staging` container; real-data capture in-process inside the running
  `nivesh-staging-app-backend` container (read-only, no restart)
- **Changed areas:** backend routes/services: yes (`backend/services/copilot_visual/`) · frontend src: yes, small (a `₹`
  unit for `bars`; see `dtc_r3_daily_review_frontend_20261031.md`)

## Summary
IN PROGRESS — filled in after the runs below.

## Test Cases
> Authored up front (after reading the data the answer reads, before the implementation).

| ID | Area | Scenario | Type | Expected | Result |
|----|------|----------|------|----------|--------|
| R18 | intents | "What did I learn from today's trades?", "How did I do today?", "How did I do this week?", "my mistakes today", "mistakes this week", "review my trades today" | unit | `daily_review`; `period` = `week` when the question names the week, else `day` | |
| R19 | intents | "What should I avoid today?", "How is my portfolio doing?", "What is my overall P&L?", "How did I do in my portfolio?" | unit | still None (Q14 and the CAS portfolio stay out) | |
| R20 | intents | the 12 earlier intents' questions; "How are my trades going today?"; "review my open trades" | unit | unchanged (open_trades stays open_trades) | |
| B28 | daily_review | trades closed today, decisions today | unit | KPIs (closed, wins/losses, win rate, net realised P&L, average R), plan-vs-actual table with R, rule-adherence list, risk-check list, equity-curve bars (cumulative, ₹), hit-rate notice; as_of = today's session, fresh | |
| B29 | daily_review | nothing recorded today, activity on an older session | unit | the latest session with activity, both dates named in the headline; as_of = that session; a stale notice when it is older than the previous session | |
| B30 | daily_review | "this week" | unit | the ISO week (Mon–today), the range named in the headline | |
| B31 | daily_review | no closed trades and no decisions ever | unit | empty-state notices; no KPI figures, no curve, nothing invented | |
| B32 | daily_review | the closed-trades read fails | unit | listed as missing, none of its figures; decisions still shown | |
| B33 | daily_review | the decisions read fails | unit | listed as missing; trades still shown | |
| B34 | daily_review | blocked + reduced + allowed decisions, one superseded row | unit | counts per outcome without double counting; the most frequent refusal reason with its message | |
| B35 | daily_review | a trade with no usable stop (strategy, or stop ≥ fill) | unit | R shown as —, left out of Average R, the KPI says how many had a stop | |
| B36 | daily_review | entry_not_reached / cancelled closes | unit | counted as "not entered", no P&L, not wins or losses | |
| B37 | daily_review | wording | unit | no "buy now / recommend / pick / you should"; every follow-up resolves to an existing intent | |
| B38 | facts | the review payload | unit | facts() carries the KPIs, the table, the lists and the curve | |
| B39 | readers | closed_trades | unit | a plain read of desk_paper_trades (status closed) shaped like the desk; never the GET route that runs the exit rule | |
| C2 | contract | real staging capture, 13 intents | contract | `validate()` = [] for every payload | |
| CI | regression | full CI allowlist | unit | same FAILED names as origin/dev | |

## API / Endpoint Tests (staging)
IN PROGRESS.

## Data Correctness (staging)
IN PROGRESS.

## Inputs required from user
- none

## Verdict: IN PROGRESS
