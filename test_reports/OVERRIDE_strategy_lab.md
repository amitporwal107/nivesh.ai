# OVERRIDE — In-chat Strategy Lab (5-step equity workbench)

REASON: This is a large new full-stack feature (a `strategy_lab` chat widget + a copilot intent trigger). The backend trigger + widget are verified locally, and the step-execution APIs it drives were already verified on real staging earlier this session. But the **end-to-end in-chat UI flow** can only be verified after (a) this branch deploys to dev/staging, (b) the V5 PWA service-worker cache is cleared so the new bundle loads, and (c) a session token to drive the chat. The widget is also LLM-surfaced (user types "build a strategy"), which makes a deterministic Playwright run flaky. Per `.claude/VERIFICATION_PROTOCOL.md` this is the sanctioned loud, recorded skip — the UI flow is **NOT** claimed verified yet.

- **Slug:** strategy_lab
- **Branch:** feat/copilot-backtest
- **Changed areas:** backend routes/services (yes) · frontend src (yes)

## What was built
- **Frontend:** `frontend-v5/src/components/chat/StrategyLabWidget.tsx` — an in-chat 5-step workbench (Universe → Strategy → Screen → Backtest → Execute) with an "AI QuantAssist" guidance line per step. Ports the verified `StrategyBuilderPage` logic (same `/api/strategy-builder/*` calls). Registered in `ChatWidget.tsx` dispatch (`case "strategy_lab"`).
- **Backend:** `WidgetType.STRATEGY_LAB` (schemas.py); `_P_STRATEGY_LAB` intent pattern + routing to the recommendation node (intent_patterns.py); a short-circuit in `recommendation.py` that emits the `strategy_lab` seed widget on "build a strategy"; `strategy_lab` added to both widget allow-lists in `chat.py`.
- **"Execute" step is honest:** it saves the strategy + exports an equal-weight target-portfolio CSV. No order routing (brokers are read-only; live execution is a compliance-gated later phase) — nothing is faked.

## Test cases + local evidence (real output this session)
| TC | Scenario | Type | Result |
|----|----------|------|--------|
| TC-1 | Intent pattern matches "build a strategy", "build a quality strategy", "strategy lab/builder"; does NOT match "build a portfolio"/"screen stocks"/"markets" | unit | **PASS** (printed match table) |
| TC-2 | `WidgetType.STRATEGY_LAB` exists; all 4 backend files compile | unit | **PASS** (`py_compile OK`) |
| TC-3 | Frontend typechecks with the new widget + dispatch | build | **PASS** (`tsc --noEmit` exit 0) |
| TC-4 | The step APIs the widget calls (screen / create / backtest) work on real staging | api (staging) | **PASS earlier this session** — fundamental screen (roe≥15 → 6 stocks), sector in/not_in, create+persist all green |
| TC-5 | Chat: "build a strategy" → `strategy_lab` widget renders → walk all 5 steps | e2e (staging UI) | **PENDING** — needs deploy + PWA cache clear + session (this OVERRIDE) |

## To clear this OVERRIDE
1. Deploy this branch to dev (app + frontend staging redeploy automatically).
2. Clear the V5 service-worker cache (Application → Unregister SW → Clear site data) so the new bundle loads.
3. In the copilot chat, send "build a strategy" → confirm the Strategy Lab widget appears → select a universe → pick a template → Run screen → Run backtest → Execute (export). Paste results into `test_reports/strategy_lab.md`, end with `## Verdict: PASS`.

## Status
IN PROGRESS — backend trigger + widget built and locally verified; step-execution backend staging-verified; in-chat UI flow pending deploy + verification. Not done, not claimed done.
