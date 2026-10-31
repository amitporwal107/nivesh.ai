# Test Cases — LLM input hardening (delimited prompt data, system prompt override, git credentials)

- **Branch:** fix/llm-input-hardening (from origin/dev 19263e08)
- **Date:** 2026-10-24
- **Author:** Claude (FULL_STACK_DEVELOPER + QA_ENGINEER)
- **Written:** before implementation. Results are recorded in `OVERRIDE_llm_input_hardening.md`.

## Scope

1. Text retrieved from data sources (exchange filings, management commentary, market feeds, fund
   events, broker position and quote) is delimited and labelled as data in the copilot prompts, and
   every specialist system prompt says that content inside the delimiters is data, not instructions.
2. `POST /api/copilot/agents/oneshot`: only admins may set `system_prompt`.
3. `services/fix_agent.py`: the GitHub token is never part of a clone or push URL, never on the
   git command line and never in the clone's `.git/config`.

## Test cases

| ID | Area | Scenario | Type | Expected |
|----|------|----------|------|----------|
| TC-1 | llm_safety | `wrap_external_data("x", "src")` | unit | returns `<external_data source="src">x</external_data>` |
| TC-2 | llm_safety | text contains `</external_data>`, `<external_data ...>`, `</User_Input>` (any case, inner spaces) | unit | each tag is escaped (`&lt;...`), exactly one closing delimiter remains, at the end |
| TC-3 | llm_safety | source label with spaces, quotes or `>` | unit | label reduced to `[a-z0-9_.-]`; no attribute break-out |
| TC-4 | llm_safety | empty string and `None` | edge | an empty, well-formed block; no exception |
| TC-5 | llm_safety | text longer than the cap | edge | body cut to the cap plus a `[truncated]` marker; block still closed; no exception |
| TC-6 | llm_safety | existing `wrap_user_input` behaviour | unit | unchanged: wraps, rejects the closing tag and over-long input |
| TC-7 | copilot rules | `ANTI_HALLUCINATION_RULES` | unit | contains the data-not-instructions rule naming the `external_data` tag |
| TC-8 | ToolResult | `as_llm_context()` ok and error | unit | wrapped in `external_data` with `source=<tool_name>`; existing `TOOL=` / `error` text still present |
| TC-9 | stocks_insights node | filings + commentary from a mocked tool, LLM mocked | unit | system prompt holds the filings inside one `external_data source="stocks_insights"` block; a delimiter planted in a headline is escaped; the user role holds the question only |
| TC-10 | market node | market_research mocked, LLM mocked | unit | TOOL_DATA line wrapped with `source="market_research"`; system prompt carries the rule |
| TC-11 | stock node | instrument research + tool results mocked, LLM mocked | unit | every TOOL_DATA line, including `instrument_research`, is wrapped |
| TC-12 | chat stream | question asked from a broker position | unit (route) | engine input = question + position facts inside `external_data source="broker_position"`; thread stores the question as asked |
| TC-13 | chat stream | question without a position | unit (route) | engine input = question only (unchanged) |
| TC-14 | chat stream | symbol lookup on the wrapped text (single-stock and index positions) | unit | resolves the same symbol as the unwrapped text |
| TC-15 | oneshot | non-admin sends `system_prompt` | api | 403 `system_prompt_not_allowed`; LLM not called |
| TC-16 | oneshot | admin (`role=admin` and legacy `is_admin`) sends `system_prompt` | api | 200; the LLM receives the admin's prompt |
| TC-17 | oneshot | non-admin, no `system_prompt` (absent / null / empty) | api | 200; default agent prompt, as before |
| TC-18 | oneshot | unknown agent_id without `system_prompt` | api | 400 as before |
| TC-19 | fix_agent | `_clone` command (subprocess mocked) | unit | argv contains no token and no `@` credentials; the token reaches git only through the environment as an auth header scoped to `https://github.com/` |
| TC-20 | fix_agent | real `git clone` from a local bare repo through `_clone` | unit (real git, no network) | `remote.origin.url` has no credentials; the token string appears nowhere under `.git/` |
| TC-21 | fix_agent | `_push_and_pr` against a local bare repo, GitHub API mocked | unit (real git, no network) | branch arrives in the bare repo; push argv has no token; hooks disabled for the push; PR request still sent with the token in the `Authorization` header |
| TC-22 | fix_agent | `run_fix` with the agent disabled | unit | stays disabled: marked failed with the existing message; no clone |
| TC-23 | regression | existing suites: llm_safety/llm_guard, chat routes, copilot agent graph, copilot agents, broker contract chart, stocks_insights, market tool | regression | all pass (an existing assertion on the engine input is updated for the wrapper) |

## Verification commands

- `sudo docker run --rm --network none -v $WT:/work:ro -w /work/backend ... nivesh/backend:staging python -m pytest <new + existing tests> -q -p no:cacheprovider`
- `python -m compileall -q` on the changed packages.
- Staging verification needs a merge to dev, a backend restart and user/admin session tokens; recorded as an override.
