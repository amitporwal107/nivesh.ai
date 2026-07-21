# OVERRIDE — Copilot "Something went wrong answering that." (bad default model id)

- **Branch:** feat/research-qa-exercise
- **Date:** 2026-07-21
- **Author:** Claude (Full-Stack + QA)
- **Changed areas:** backend services: **yes** (`backend/nidp/services/copilot_agent/_llm.py`) · frontend src: no

REASON: Root cause + one-line config fix are verified with real executed output below; the
live staging chat/stream E2E is not runnable from this environment (stale GCP token, policy-
blocked SSH, no local backend deps, no session token) — see the explicit asks at the bottom.

The root cause and the one-line config fix are **verified with real, executed
output below** (the copilot's default model id flipped from an inaccessible `gpt-5.5` to the
account's known-good `gpt-4o-mini`, and temperature tuning is restored). The remaining proof —
a **live staging chat/stream E2E** showing the copilot now answers the failing query — cannot
be run from this environment:
- the GCP token at `/app/.gcp-token` is **stale** (`gcloud secrets list` → `UNAUTHENTICATED`),
- `gcloud compute ssh … --command` to `nivesh-app-vm` is **blocked by the auto-mode policy**,
- the backend is **not runnable locally** (no `langchain_openai`, no OpenAI/DAAS creds),
- and the authenticated endpoint needs a **session token I was not given**.

I will not fabricate a staging result. This OVERRIDE is the sanctioned, non-silent skip for the
E2E portion. **To close it:** deploy this branch to staging (redeploy pulls `dev`) and run the
curl in "API / Endpoint Tests" with a real `session_token`; also confirm the deployed env does
**not** pin `COPILOT_LLM_MODEL=gpt-5.5` (see "Inputs required").

## Summary
The Research-tab copilot returned **"Something went wrong answering that."** for every ask
(screenshot: "COPILOT · GROUNDED IN FILINGS · ROUTE 1.00" then the error). Root cause: commit
`c1d86d05` set the shared copilot model default to **`gpt-5.5`** — an id the commit message
itself flags as *unverified against the live OpenAI account*. **All** copilot nodes (intent,
stocks_insights, stock, market, risk, recommendation, backtest) build `ChatOpenAI(model=COPILOT_LLM_MODEL)`
from that one constant, so an inaccessible id returns `model_not_found` on the node's LLM call,
which propagates to the `/api/chat/stream` `except` block and is streamed as an `error` event →
the frontend shows the generic line. On the pinned Research surface, intent classification is
bypassed (hence the synthetic `ROUTE 1.00`), so the first — and failing — LLM call is the
answer composition in `stocks_insights_node`. Fix: revert the default to the known-good
`gpt-4o-mini` (COPILOT_CHATBOT.prd §7; the exact remedy applied to the identical prior `gpt-5`
incident). `gpt-5.x` remains available to ops via the `COPILOT_LLM_MODEL` env / GSM once the
account's access is confirmed.

## Evidence the diagnosis is correct (real, from the repo this session)
- `git log -S'"gpt-5.5"'` → `c1d86d05 fix(copilot): set COPILOT_LLM_MODEL default to gpt-5.5`,
  whose message reads: *"if the account … lacks gpt-5.5 access, the nodes will 'model_not_found'
  and surface 'trouble connecting to my AI engine'."* The prior default's message: *"the previous
  'gpt-5' default broke the copilot nodes on accounts without gpt-5 access."*
- Model-id usage across `backend/` (real refs): `gpt-4o` ×35, `gpt-4o-mini` ×32, `gpt-5.5` ×3
  (all in this one file's default/doc). The only literal `model="gpt-…"` call-sites resolve to
  `gpt-4o-mini`.
- All seven copilot nodes import `COPILOT_LLM_MODEL` from `_llm.py` → one bad id = whole-copilot outage.
- No `COPILOT_LLM_MODEL` override found anywhere in the repo's compose/env/Dockerfiles.

## Test Cases (authored before the edit)

| ID | Area | Scenario | Type | Expected | Result |
|----|------|----------|------|----------|--------|
| TC-1 | config | `_llm.COPILOT_LLM_MODEL` default (no env override) | unit | `gpt-4o-mini` (known-good), not `gpt-5.5` | **PASS** (real output below) |
| TC-2 | config | `temperature_for(0.1)` under the default | unit | `0.1` (tuning restored; not force-`1.0`) | **PASS** (real output below) |
| TC-3 | config | env override still wins | unit | `COPILOT_LLM_MODEL=gpt-5.5` → default yields `gpt-5.5` | **PASS** (real output below) |
| TC-4 | api (staging) | `POST /api/chat/stream` `{message:"Biggest order wins this fortnight…", agent:"stocks_insights", page:"research"}` | e2e | SSE ends with a `done` event carrying a grounded answer; **no** `error` event | **BLOCKED** — needs deploy + session token |
| TC-5 | ui (staging) | Research tab → click the curated "Biggest order wins…" theme → Ask | e2e | Copilot renders an answer card, not "Something went wrong answering that." | **BLOCKED** — needs deploy + session token |

## Unit Tests (executed this session — real output)
- **TC-1 / TC-2** — default + temperature:
  - Command: `python3 -c "import importlib.util; spec=importlib.util.spec_from_file_location('m','nidp/services/copilot_agent/_llm.py'); m=importlib.util.module_from_spec(spec); spec.loader.exec_module(m); print(m.COPILOT_LLM_MODEL, m.temperature_for(0.1))"`
  - Output (after fix): `gpt-4o-mini 0.1`
  - Output (before fix, for contrast): `gpt-5.5 1.0`
  - Result: **PASS**
- **TC-3** — env override precedence:
  - Command: `COPILOT_LLM_MODEL=gpt-5.5 python3 -c "…exec _llm.py…; print(m.COPILOT_LLM_MODEL)"`
  - Output: `gpt-5.5`
  - Result: **PASS** (ops can still opt into gpt-5.x with no code change)

## API / Endpoint Tests (staging) — REQUIRED, currently BLOCKED
- **Endpoint:** `POST /api/chat/stream`
  - Command (run after deploy, with a real token):
    `curl -N -sk 'https://staging.niveshcopilot.com/api/chat/stream' -H 'Content-Type: application/json' -H 'Cookie: session_token=<TOKEN>' -d '{"message":"Biggest order wins this fortnight — by value, sector, and counterparty (govt/PSU/private)","agent":"stocks_insights","page":"research"}'`
  - Expected: stream contains `data: {"type":"done",…}` with a non-empty answer; **no** `data: {"type":"error",…}`.
  - Result: **BLOCKED** (cannot reach staging headlessly this session).

## Data Correctness
- The fix is a model-id config change; it does not alter what data is read/written. Answer
  grounding is unchanged (still the DAAS filings/commentary the node already retrieves). The
  only behavioural delta is that the LLM compose step now succeeds instead of `model_not_found`.

## Inputs required from user
1. **Deploy this branch to staging** (staging redeploys from `dev`) so the endpoint carries the fix.
2. **A staging `session_token`** to run the TC-4 curl / TC-5 Playwright against the authed endpoint.
3. **Confirm the deployed env does not pin `COPILOT_LLM_MODEL=gpt-5.5`.** The code default now
   resolves to `gpt-4o-mini`, but an explicit env/GSM value would still override it. If one is
   set, unset it (or set it to `gpt-4o-mini`) and restart the backend. Re-add a `gpt-5.x` id
   **only after** confirming the OpenAI account has access to it.

## Verdict: BLOCKED
<!-- Root cause + config fix VERIFIED with real output (TC-1..TC-3). Live staging E2E
     (TC-4/TC-5) is the sanctioned OVERRIDE skip above: needs deploy + session token. -->
