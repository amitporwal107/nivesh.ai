# OVERRIDE — copilot chat on Claude: live verification pending

REASON: Blocked on a secret only the account owner can supply. No `ANTHROPIC_API_KEY` exists on the staging app VM or in the files provided, so a real chat turn through Claude cannot be run. Asked the user for the key on 2026-10-12.

Commit `6d026a5b` on `dev`, deployed to staging by CI (`Deploy backend → CloudPe app VM [staging]`: success).

## What is verified

- Unit tests, new image (`nidp/tests/services/test_copilot_llm_provider.py`): `17 passed in 4.63s`.
  Provider selection, the model id, no sampling parameters in the Claude request payload,
  text-only reading of block replies and stream chunks, intent JSON inside a code fence.
- Existing copilot tests: the same 9 fail before and after this change
  (`tests/test_copilot_backtest.py` ×8, `tests/test_copilot_symbol_resolution.py` ×1); none new.
- Staging after deploy:
  ```
  langchain-anthropic 1.4.4 | anthropic 0.125.0
  active copilot provider on staging: openai | model: gpt-4o-mini | anthropic key present: False
  GET https://staging.niveshcopilot.com/api/healthz → HTTP 200
  ```
  With no key the provider is unchanged, so the deploy is inert.
- Prompts: no prompt constant differs (`git diff` over `copilot_agent/` shows 0 changed
  prompt/system/rules lines); only the model constructor and reply reading changed.

## Test cases still to run once the key is set

| # | Case | Expected |
|---|---|---|
| L1 | `_llm.llm_provider()` on staging | `anthropic`, model `claude-opus-5-5` |
| L2 | One real call through `make_chat_llm` with an existing node prompt | text reply, no 400 |
| L3 | Intent classification on a real question | valid agent, not the fallback |
| L4 | `POST /api/chat/stream` as a signed-in user | SSE tokens are plain text; no reasoning text leaks |
| L5 | A portfolio question end to end | answer grounded in tool data; widget emitted |
| L6 | Backend log during the turn | no `Stream error`, no 4xx from the provider |

UNVERIFIED until then: any behaviour of the copilot on Claude with real requests.
