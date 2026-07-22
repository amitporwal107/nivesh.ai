# OVERRIDE — Copilot LLM provider switch to Groq (free openai/gpt-oss-120b)

- **Branch:** feat/research-qa-exercise
- **Date:** 2026-07-21
- **Author:** Claude (Full-Stack + QA)
- **Changed areas:** backend services: **yes** (`_llm.py` + 10 copilot node files) · frontend src: no

**REASON:** The provider switch is **verified with real, executed output** — including a
**live HTTP 200 from Groq** using the actual key + `openai/gpt-oss-120b`, plus routing-logic
unit checks and a full py_compile. What remains is the **staging end-to-end** (the full
LangGraph copilot answering a curated theme through Groq), which cannot run from this
environment: the backend isn't runnable locally (no `langchain_openai`), and staging needs
(a) `GROQ_API_KEY` set in the deployed env — which I can't reach (stale GCP token, blocked SSH)
— and (b) a deploy + session token. This OVERRIDE is the sanctioned skip for that staging leg;
the Groq integration itself is proven live below.

## Summary
The deployed copilot still errored on curated/thematic asks even after the code default was
set to `gpt-4o-mini` — the graceful fallback string showed, meaning the compose LLM call still
threw at runtime (a stale `COPILOT_LLM_MODEL=gpt-5.5` pin and/or OpenAI access issue in the
deployed env). Per product direction, route the copilot through **Groq's free
`openai/gpt-oss-120b`** instead. Because Groq is OpenAI-wire-compatible, `_llm.py` gains a
single `make_chat_llm()` factory (Groq auto-selected when `GROQ_API_KEY` is set; on Groq it
**ignores** any stale OpenAI id in `COPILOT_LLM_MODEL` and uses `openai/gpt-oss-120b` via
Groq's `base_url`). All 10 copilot nodes (12 call sites) now build their LLM through that
factory — one provider decision, in one place. No new dependency; only the copilot chat nodes
are redirected (embeddings / other OpenAI calls are untouched).

## Test Cases

| ID | Area | Scenario | Type | Expected | Result |
|----|------|----------|------|----------|--------|
| TC-1 | live | `POST api.groq.com/openai/v1/chat/completions`, key from `.env`, model `openai/gpt-oss-120b` | api | HTTP 200, model echoes `openai/gpt-oss-120b` | **PASS** |
| TC-2 | live | Same, realistic `max_tokens` (400) | api | non-empty `content`, `finish_reason: stop` | **PASS** |
| TC-3 | unit | No `GROQ_API_KEY` | unit | provider=openai, model=gpt-4o-mini, temp 0.1 | **PASS** |
| TC-4 | unit | `GROQ_API_KEY` set | unit | provider=groq, model=openai/gpt-oss-120b, temp 0.1 | **PASS** |
| TC-5 | unit | groq + stale `COPILOT_LLM_MODEL=gpt-5.5` | unit | model still `openai/gpt-oss-120b` (pin ignored) | **PASS** |
| TC-6 | unit | explicit `COPILOT_LLM_PROVIDER=openai` w/ groq key | unit | provider=openai (explicit wins) | **PASS** |
| TC-7 | build | `py_compile` `_llm.py` + all 10 nodes; no stray `ChatOpenAI` refs | build | compiles; factory imported+used everywhere | **PASS** |
| TC-8 | e2e (staging) | Curated theme → copilot answers via Groq, no fallback string | e2e | grounded answer card | **BLOCKED** — needs GROQ_API_KEY on VM + deploy + token |

## Live Groq call — real output (TC-1 / TC-2)
- Command: `curl -K <conf with Authorization: Bearer $GROQ_API_KEY> https://api.groq.com/openai/v1/chat/completions` (key kept out of argv; conf deleted after)
- TC-1 output: `{"...","model":"openai/gpt-oss-120b","choices":[{...}],"usage":{...}}` → **HTTP 200**
- TC-2 output: `finish_reason: stop` · `content: 'ACC and UltraTech are two Indian cement companies.'` · reasoning_tokens 77 / completion_tokens 96
- Note: `openai/gpt-oss-120b` is a **reasoning** model (emits `reasoning` tokens separately from
  `content`). With a tiny `max_tokens` all budget goes to reasoning and `content` is empty; with
  a normal budget (the copilot sets no low cap) `content` is populated. `temperature=0.1` is
  accepted (unlike gpt-5.x), so `temperature_for` needs no special-case for it.

## Routing-logic unit checks — real output (TC-3..TC-6)
```
default (no groq key)                    provider=openai model=gpt-4o-mini            temp=0.1
GROQ_API_KEY set                         provider=groq   model=openai/gpt-oss-120b    temp=0.1
groq + stale COPILOT_LLM_MODEL=gpt-5.5   provider=groq   model=openai/gpt-oss-120b    temp=0.1
explicit provider=openai (groq present)  provider=openai model=gpt-5.5                temp=1.0
```
`py_compile` of `_llm.py` + all 10 nodes: **OK**; grep for leftover `ChatOpenAI` / `COPILOT_LLM_MODEL` / `get_openai_api_key` in nodes: **NONE**.

## Inputs required from user (to finish TC-8 on staging)
1. Set **`GROQ_API_KEY=gsk_…`** in the staging backend env (VM env file / GSM) and restart. That
   one var is enough — provider auto-selects groq, the model defaults to `openai/gpt-oss-120b`,
   and any stale `COPILOT_LLM_MODEL=gpt-5.5` is ignored on groq. (`backend/.env` already carries
   it for LOCAL runs; staging does not read that file.)
2. Deploy this branch to staging (redeploy pulls `dev`).
3. A `session_token` to run the `/api/chat/stream` curl and confirm a curated theme answers with
   no fallback string.

## Verdict: BLOCKED
<!-- Groq integration PROVEN LIVE (TC-1..TC-7 PASS, real output). Only the full staging E2E
     (TC-8) is deferred — needs GROQ_API_KEY on the VM + deploy + session token. -->
