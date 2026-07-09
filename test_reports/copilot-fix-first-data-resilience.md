# Functionality Verification — Copilot "fix first" / "portfolio health" missing tools

**Bug (reproduced live on staging, both modes):** In **investor** mode the copilot returns
*"I couldn't retrieve the data needed to answer this — please try again…"* for
"What's the one thing I should fix first?" and "What's my portfolio health?". In
**advisor** mode the same question answers over the client book. Deterministic repro:
`X-Active-Profile: <SELF profile id>` header → investor; no header → advisor.

## Root cause (found on the DEPLOYED code, not my stale local branch)

The copilot portfolio node calls `port_mod.get_portfolio_health_score(user_id)` and
`port_mod.get_top_recommendations(user_id)` ([nodes/portfolio.py:116,128]), but those two
functions were **missing from `services/copilot_tools/portfolio.py`** on `origin/dev`
(the deployed code). So `port_mod.get_top_recommendations` raised **AttributeError**,
which the node's coarse outer `try/except` ([nodes/portfolio.py:215]) turned into a single
"Portfolio data unavailable" — discarding the good `get_portfolio_summary` + `get_portfolio_xirr`
— which trips the copilot's rule-4 fallback ([_llm.py:74]).

Confirmed by mapping question→tool on staging:
- "Summarise my portfolio" (→ `get_portfolio_summary`, present) ✅
- "Am I too concentrated?" (routed to the risk agent) ✅
- "What's my portfolio health?" (→ `get_portfolio_health_score`, **missing**) ❌
- "What's the one thing I should fix first?" (→ `get_top_recommendations`, **missing**) ❌

The advisor path answers because it uses a different (client-book) flow that never calls
these tools.

## Fix
1. `services/copilot_tools/portfolio.py` — **add** `get_portfolio_health_score` and
   `get_top_recommendations` (mirroring the dashboard: `build_portfolio_health` /
   `build_dashboard_recommendations`, both present on dev; post-processing kept *inside*
   the `try` so a shape change degrades to `ok=False` instead of throwing).
2. `nidp/services/copilot_agent/nodes/portfolio.py` — `_fetch_portfolio_data` now preserves
   the results already collected (summary/XIRR/…) when a later tool throws, so one bad
   tool can't nuke the whole answer.

## Test cases (staging, real streamed answers — after deploy)

| # | Mode | Question | Expected |
|---|------|----------|----------|
| 1 | investor (`X-Active-Profile: SELF`) | "What's the one thing I should fix first?" | real ranked recommendations, NOT "couldn't retrieve" |
| 2 | investor | "What's my portfolio health?" | real score/grade + fixes, NOT "couldn't retrieve" |
| 3 | investor | "Summarise my portfolio" | still works (regression) |
| 4 | advisor (no header) | "What's the one thing I should fix first?" | still answers over the client book (regression) |

## Local checks

```
$ python3 -m py_compile backend/services/copilot_tools/portfolio.py \
    backend/nidp/services/copilot_agent/nodes/portfolio.py   # OK
```
(The backend pytest suite can't run in this sandbox — 24 collection errors, all
`REACT_APP_BACKEND_URL`/missing-fixture env issues, unrelated to this change. The copilot
agent runs in the streaming generator, so the real proof is the staging re-run below.)

## Real output — staging, both modes

_(filled after deploy)_

## Verdict: PENDING (implementation + py_compile done; awaiting staging deploy + both-mode re-run)
