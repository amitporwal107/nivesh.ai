# OVERRIDE — In-chat Strategy Lab (5-step equity workbench)

REASON: The backend path is VERIFIED on real staging (below). The one remaining check — the **browser render** of the widget via Playwright — is not run: the widget is LLM-surfaced ("build a strategy" in chat), which makes a deterministic Playwright run flaky, and the V5 PWA service-worker cache masks the new bundle until the user clears it. Per `.claude/VERIFICATION_PROTOCOL.md` this is the sanctioned loud, recorded skip — the **browser UI** is NOT claimed verified; the backend IS.

- **Slug:** strategy_lab
- **Branch:** feat/copilot-backtest
- **On origin/dev:** `1720b6dc` (Strategy Lab feature) + `9ca99e94` (advisor-mode routing fix)
- **Changed areas:** backend routes/services (yes) · frontend src (yes)

## What was built
- **Frontend:** `StrategyLabWidget.tsx` — in-chat 5-step workbench (Universe → Strategy → Screen → Backtest → Execute), AI-QuantAssist guidance per step; ports the verified `StrategyBuilderPage` logic. Registered in `ChatWidget.tsx` dispatch.
- **Backend:** `WidgetType.STRATEGY_LAB`; `_P_STRATEGY_LAB` intent pattern + routing; recommendation-node short-circuit emitting the seed widget; `strategy_lab` added to `chat.py` allow-lists; `_RESEARCH_INTENT_RE` (copilot.py) extended so advisor-mode "build a strategy" reaches the investor engine.
- **"Execute" is advisory-only:** saves the strategy + exports an equal-weight target-portfolio CSV. No order routing.

## Test cases + evidence
| TC | Scenario | Type | Result |
|----|----------|------|--------|
| TC-1 | Intent + research-gate patterns match "build a strategy"/"strategy lab", not portfolio/screen/book | unit | PASS (printed match tables) |
| TC-2 | All backend files compile; `WidgetType.STRATEGY_LAB` exists | unit | PASS (`py_compile OK`) |
| TC-3 | Frontend typechecks with new widget + dispatch | build | PASS (`tsc --noEmit` exit 0) |
| TC-4 | Step APIs (screen fundamental+sector, create/persist, backtest) work on real staging | api (staging) | PASS earlier this session |
| TC-5 | **Chat: "build a strategy" → `strategy_lab` widget emitted on staging** | api (staging) | **PASS** — real output below |
| TC-6 | Widget renders in browser + walk all 5 steps | e2e (Playwright) | **PENDING** (this OVERRIDE) |

### TC-5 real staging output (this session)
```
POST /api/chat/send  {"message":"build a strategy"}  (session: aporwal107@gmail.com, advisor mode)
backend healthy (attempt 1, ~20s elapsed)
attempt 1 -> strategy_lab | "Opening the Strategy Lab. Pick a universe, choose a factor
             template, then screen and backtest it on live, corp-action-ad…"
Strategy Lab widget surfaced
```
Control earlier same session: `screen stocks where roe over 15` → `ai_message.widget.widget_type = stock_screener` (confirms the widget-in-response path + advisor-mode research routing).

## To clear this OVERRIDE
1. Clear the V5 service-worker cache (incognito, or Application → Unregister SW + Clear site data) so the new bundle loads.
2. In chat send "build a strategy" → confirm the Strategy Lab widget renders → select universe → pick template → Run screen → Run backtest → Execute (export). Capture into `test_reports/strategy_lab.md`, end with `## Verdict: PASS`.

## Status
IN PROGRESS — backend trigger + step APIs VERIFIED on staging; frontend browser render pending Playwright (+ PWA cache clear). Not done, not claimed done.
