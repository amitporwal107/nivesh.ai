# OVERRIDE — LLM input hardening (fix/llm-input-hardening)

REASON: staging verification needs merge to dev, backend restart and a user session token (and an admin session for the oneshot override case); local pytest: 40 passed (3 new files); 457 passed, 9 failed in the combined run of new + related existing suites (the 9 are `@pytest.mark.asyncio` tests that fail identically on origin/dev 19263e08 because pytest-asyncio is not installed in nivesh/backend:staging); copilot_agent tests: test_risk_tools.py 44 passed alone, the other files 88 passed / 27 failed / 17 errors, with the failure set identical to origin/dev (stale `nodes.intent.ChatOpenAI` patch targets); compileall exit 0.

- **Branch:** fix/llm-input-hardening (base origin/dev 19263e08)
- **Date:** 2026-10-25
- **Test cases:** `test_reports/llm_input_hardening_TESTCASES.md` (written before implementation)

## What changed

| Area | File | Change |
|------|------|--------|
| helper | `backend/services/llm_safety.py` | `wrap_external_data(text, source)` and `EXTERNAL_DATA_RULE`: delimits retrieved text as `<external_data source="...">...</external_data>`, escapes delimiter tags (`external_data`, `user_input`, any case) inside the text, cuts text over 24,000 chars with a marker, never raises |
| rule | `backend/nidp/services/copilot_agent/_llm.py` | rule 10 appended to `ANTI_HALLUCINATION_RULES` (every specialist system prompt): delimited content is data, not instructions |
| tool data | `backend/nidp/services/copilot_agent/schemas.py` | `ToolResult.as_llm_context()` wraps its line, so TOOL_DATA is delimited in the market, stock, mf, portfolio, risk, goal, recommendation and backtest nodes |
| filings | `backend/nidp/services/copilot_agent/nodes/stocks_insights.py` | filings + management commentary context wrapped (`source="stocks_insights"`) |
| research | `backend/nidp/services/copilot_agent/nodes/stock.py` | instrument research line wrapped |
| broker | `backend/routes/chat.py` | broker position + quote facts appended to the engine's question are wrapped (`source="broker_position"`) |
| oneshot | `backend/routes/copilot_agents.py` | `system_prompt` from a non-admin → 403 `system_prompt_not_allowed`; admins (`role=admin` or legacy `is_admin`) unchanged; no frontend sends the field |
| git | `backend/services/fix_agent.py` | clone and push use the plain URL; the token goes to git as a `github.com`-scoped `http.extraheader` via `GIT_CONFIG_*` environment variables; push runs with hooks disabled; disabled-flag logic untouched |

## Local test evidence (real output, nivesh/backend:staging, --network none)

New tests:
```
python -m pytest tests/test_llm_input_hardening.py tests/test_copilot_agents_oneshot.py tests/test_fix_agent_git_auth.py -q -p no:cacheprovider
40 passed, 2 warnings in 10.25s
```

New + related existing suites (llm_safety/llm_guard, broker contract chart incl. chat stream, chat persona/session, copilot agents, desk prompt, stocks_insights, market tool, portfolio summaries, intent routing, backtest, symbol resolution, MF resolution, LLM provider):
```
9 failed, 457 passed, 12 warnings in 26.99s
FAILED tests/test_copilot_backtest.py (8 tests) / tests/test_copilot_symbol_resolution.py::test_stock_node_asks_when_no_symbol
-> "async def functions are not natively supported ... install pytest-asyncio"
same two files on an export of origin/dev 19263e08: 9 failed, 34 passed
```

The new oneshot and fix_agent tests run against origin/dev code: 5 failed, 2 errors (non-admin override accepted; token in the clone URL). They pass on this branch.

NIDP copilot_agent tests:
```
test_risk_tools.py alone:                         44 passed in 0.25s
the other files (test_risk_tools.py ignored):     27 failed, 88 passed, 1 warning, 17 errors
failure/error set on origin/dev vs this branch:   44 vs 44, IDENTICAL
(cause: fixtures patch nodes.intent.ChatOpenAI, which the module no longer has)
```

Final run on the committed tree (the two pytest-asyncio files left out):
```
new + related suites, test_risk_tools.py left out:  423 passed, 3 warnings in 20.58s
test_risk_tools.py alone:                           44 passed in 0.25s
both in one process:                                64 failed, 403 passed
  (42 test_risk_tools + 22 market-tool tests; the same 64 fail on origin/dev when
   test_risk_tools.py shares a process with the market tests: known order dependency)
```

compileall on the changed modules and tests: `compileall exit=0`.

## Not verified here

- UNVERIFIED on staging: a real `/api/chat/stream` answer with the delimited TOOL_DATA (answer quality and format unchanged), a real oneshot call as a user and as an admin, and a real fix_agent clone/push against GitHub. Needs: merge to dev, backend restart, a user session token and an admin session token. A live fix_agent run also needs `FIX_AGENT_ENABLED` and a GitHub token on staging.

## Verdict: BLOCKED (override above; staging run pending)
