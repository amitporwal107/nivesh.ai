# OVERRIDE — Research copilot "Something went wrong answering that."

- **Branch:** feat/research-qa-exercise
- **Date:** 2026-07-21
- **Author:** Claude (Full-Stack + QA)
- **Changed areas:** backend services: **yes** (`backend/services/copilot_tools/stocks_insights.py`, `backend/nidp/services/copilot_agent/nodes/stocks_insights.py`) · frontend src: no

**REASON:** The root cause is reproduced and the fix is unit-verified below with real,
unedited output. The required **live staging API E2E cannot be run from this environment**
for three independent reasons: (1) staging deploys from `dev`, so the currently-deployed
copilot does **not** contain this fix — a staging call now would exercise the OLD code, not
the change; (2) the authenticated live reproduction (`POST /api/chat/stream` with a session
token) is **blocked by the sandbox permission classifier** (it writes a chat message), so I
cannot even reproduce against the deployed copilot from here; (3) the `gcloud` credentials in
this environment are stale, so I can neither deploy to staging nor read the app-backend logs.
I will not fabricate a staging stream result. This OVERRIDE is the sanctioned, non-silent
skip for the staging-E2E portion; the defect and the fix are verified locally. See
**"To finish staging verification"** at the bottom for the exact next step.

## Root cause (diagnosed, not guessed)

The `/research` tab pins the copilot to the `stocks_insights` agent. The failing query
— *"Biggest order wins this fortnight — by value, sector, and counterparty (govt/PSU/private)"* —
resolves to **no ticker** (verified: `resolve_symbol()` → `None`), so it runs in **thematic**
(cross-company) mode.

The UI showed `COPILOT · GROUNDED IN FILINGS · ROUTE 1.00` then the error. `ROUTE 1.00` is
emitted only *after* intent routing (pinned agents get `confidence=1.0`, `intent.py:162`), so
the exception happened **after routing, inside `stocks_insights_node`**. Every other call in
that node is guarded (tool call, `emit_widget`, `frame_for_persona`, `_strip_dangling_citations`),
which isolates the throw to the answer-compose step.

`StocksInsightsResult.as_llm_context()` built its context by slicing DAAS fields directly:

```python
filed = (e.get("filed_at") or "")[:10]          # line 107 (pre-fix)
... f"{(e.get('headline') or '')[:120]}"        # line 109 (pre-fix)
```

The per-ticker `/announcements` feed returns ISO-**string** dates, but the thematic
market-pulse / events-search feed can return `filed_at` as a **numeric epoch**. `int[:10]`
raises `TypeError: 'int' object is not subscriptable`. That throw is unguarded → it
propagates to the `/chat/stream` handler (`chat.py:1527`), which saves an error message and
emits an SSE `{"type":"error"}` frame → the client shows the generic
*"Something went wrong answering that."* with no answer. This is exactly the observed
symptom and explains why a **thematic** ask fails while a **$TICKER** ask succeeds.

## The fix

1. **Root-cause (`copilot_tools/stocks_insights.py`):** `str()`-coerce every DAAS value
   before slicing / `.strip()` / `.replace()` in `as_llm_context()` (events + commentary
   blocks). A non-string field can no longer raise.
2. **Defense-in-depth (`nodes/stocks_insights.py`):** wrap the whole compose step
   (context build + LLM `ainvoke`) in a guard that logs loudly and degrades to an honest
   fallback answer — so **no** future hiccup in this node can again abort the turn with a
   raw SSE `error` frame. This matches the node's existing "never break the turn" discipline
   (already applied to the tool call).

## Test cases (authored against the diagnosis) — VERIFIED (real output)

| ID | Scenario | Type | Expected | Result |
|----|----------|------|----------|--------|
| TC1 | thematic event, `filed_at` = epoch int | unit | `as_llm_context()` returns a string, no raise | PASS |
| TC2 | thematic event, `filed_at` = datetime | unit | no raise | PASS |
| TC3 | thematic event, `headline` = int | unit | no raise | PASS |
| TC4 | all-string event (happy path) | unit | no raise, unchanged output | PASS |
| TC5 | commentary, `company`/`doc_type` None, `page` str | unit | no raise | PASS |
| TC6 | commentary, `company` = int | unit | no raise | PASS |
| TC7 | `build_widget_data` on all above shapes | unit | no raise, valid widget | PASS |
| TC8 | epoch row still yields a date token in context | unit | coerced string present | PASS |

### Before/after (same code path, exact query shapes)

Pre-fix (real output):
```
filed_at=int      :: as_llm_context RAISED -> TypeError: 'int' object is not subscriptable
filed_at=datetime :: as_llm_context RAISED -> TypeError: 'datetime.datetime' object is not subscriptable
headline=int      :: as_llm_context RAISED -> TypeError: 'int' object is not subscriptable
```
Post-fix (real output):
```
filed_at=int      :: as_llm_context OK
filed_at=datetime :: as_llm_context OK
headline=int      :: as_llm_context OK
```

### Regression test (real output)

`python3 -m pytest tests/test_stocks_insights_nonstring_fields.py -v`
```
11 passed in 0.13s
```

### No collateral damage (real output)

- `python3 -m py_compile` both changed files → `COMPILE OK (both files)`
- `python3 -m pytest tests/test_copilot_symbol_resolution.py -q` → `14 passed, 1 skipped in 0.09s`

## To finish staging verification (next step, needs the user)

Pick one:
- **Deploy the fix to staging** (staging tracks `dev`) and re-run the thematic query on
  `/research`, or
  `curl -sN -X POST https://staging.niveshcopilot.com/api/chat/stream -H 'Authorization: Bearer <session_token>' -H 'Content-Type: application/json' -d '{"message":"Biggest order wins this fortnight — by value, sector, and counterparty (govt/PSU/private)","agent":"stocks_insights","page":"research"}'`
  → expect a real grounded answer + `done` frame (no `error` frame), OR
- **Grant the blocked live POST** (add a Bash permission rule) so I can run the curl above
  against the deployed backend to confirm the pre-fix repro, then verify post-deploy.

## Verdict: OVERRIDE (local unit verification PASS; staging E2E blocked as stated)
