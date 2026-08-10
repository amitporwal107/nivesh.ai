# Functionality Verification Report — announcement_classifier → Groq

- **Branch:** feat/research-qa-exercise
- **Date:** 2026-08-10
- **Author:** Claude (Full-Stack Developer + QA Engineer)
- **Environment:** nidp-stack-vm (`nidp_staging` DB — the DB prod DaaS reads)
- **Changed areas:** backend routes/services: yes (`backend/nidp/`) · frontend src: no

## Summary

`/v5/research` corporate events went stale because `announcement_classifier` stopped
writing `event_category` / `impact_score` / `sentiment`. Last successful classification:
**2026-07-25 15:11 IST**. Since **2026-07-30T21:22Z** every LLM call fails with OpenAI
`429 credit_balance_exhausted`. Backlog in the 30-day window: **4,808 unclassified vs
3,801 classified**.

Per user decision, this change routes the classifier off OpenAI onto Groq's free
OpenAI-wire-compatible endpoint (`openai/gpt-oss-120b`), reusing the provider-selection
pattern already shipped for `ai_engine` text paths and the NIDP copilot.

**Scope verified here:** provider/model/tool-spec selection and response parsing.
Live Groq classification + backlog drain are gated on `GROQ_API_KEY` reaching
`/opt/nidp/nidp.env` (see "Inputs required from user").

## Test Cases
> Authored UP FRONT — before implementation.

| ID | Area | Scenario | Type | Expected | Result |
|----|------|----------|------|----------|--------|
| TC-1 | provider | No GROQ key, no override | unit | provider=openai, model=gpt-4o-mini, no base_url | **PASS** |
| TC-2 | provider | GROQ_API_KEY resolves | unit | provider=groq, model=openai/gpt-oss-120b, base_url=https://api.groq.com/openai/v1 | **PASS** |
| TC-3 | provider | Explicit `ANNOUNCEMENT_CLASSIFIER_PROVIDER=openai` with GROQ key present | unit | explicit wins → openai | **PASS** |
| TC-4 | provider | Stale OpenAI model pin (`ANNOUNCEMENT_CLASSIFIER_MODEL`) must not leak to Groq | unit | Groq model unaffected by the OpenAI pin | **PASS** |
| TC-5 | wire | Tool spec per provider | unit | `strict` present on OpenAI, ABSENT on Groq | **PASS** |
| TC-6 | parse | Forced tool_call parsed into Classification | unit | fields + classifier_version populated | **PASS** |
| TC-7 | parse | Response with no tool_call | unit (failure) | raises RuntimeError, does not write | **PASS** |
| TC-7b | parse | Out-of-taxonomy value (no `strict` on Groq) | unit (edge) | raises; junk never reaches the facet key | **PASS** (3 params) |
| TC-8 | version | classifier_version stable per (model, prompt), differs across providers | unit | deterministic, provider-distinct | **PASS** |
| TC-9 | live | Real Groq call, real classifier code path | api | valid enum classification returned | **PASS** |
| TC-10 | data | Real classifier run against `nidp_staging` | data | unclassified count drops; rows get category/impact/sentiment | **BLOCKED** — needs GROQ_API_KEY on VM |
| TC-11 | ui | `/v5/research` shows today's filings with real categories + non-empty signals | e2e | facets populated, signals non-empty | **BLOCKED** — needs TC-10 + session token |

## Unit Tests

```
$ cd /app/backend && python3 -m pytest nidp/tests/services/test_announcement_classifier_provider.py -q
..............                                                           [100%]
14 passed in 0.62s
```

Regression check on the rest of the nidp suite (4 modules excluded — they import
`fastapi`, which is not installed in this container; unrelated to this change):

```
$ python3 -m pytest nidp/tests -q --ignore=...test_daas_api.py --ignore=...test_failing_feeds_golden.py \
    --ignore=...test_pipeline_freshness.py --ignore=...test_pipeline_stages_endpoint.py
3 failed, 284 passed, 6 skipped in 5.11s
```

The 3 failures are **pre-existing**, proven by re-running them with my change stashed:

```
$ git stash push -q backend/nidp/services/announcement_classifier/classifier.py
$ python3 -m pytest nidp/tests/services/test_mf_amc_robustness.py nidp/tests/test_feed_registry_drift.py -q
FAILED nidp/tests/services/test_mf_amc_robustness.py::test_discover_xlsx_link_returns_none_when_only_old_months
FAILED nidp/tests/services/test_mf_amc_robustness.py::test_try_listing_page_walks_candidates
FAILED nidp/tests/test_feed_registry_drift.py::test_every_recoverable_daily_feed_is_scheduled
3 failed, 10 passed in 0.82s
```

Import smoke test in the deployed shape (no helpers/GSM present — the container reality):

```
$ python3 -c "from nidp.services.announcement_classifier import classifier as C; ..."
GSM client unavailable — secrets sourced from GSM will be None. (No module named 'google')
provider (no keys here): openai
openai model: gpt-4o-mini
groq model  : openai/gpt-oss-120b
groq base   : https://api.groq.com/openai/v1
version(groq): openaigptoss120b-0216a46c04
strict on groq tool: False
```

## TC-9 — live Groq function-calling (the one genuine unknown)

User supplied a `GROQ_API_KEY`. Ran the REAL classifier code path against Groq
(`scratchpad/groq_compat_test.py`, 4 representative announcements):

```
provider=groq  model=openai/gpt-oss-120b
  OK  t1   1.07s  earnings    medium positive  | Quarterly audited results showing double-digit revenue and profit grow
  OK  t2   0.72s  other       low    neutral   | The announcement is merely a newspaper advertisement of unaudited resu
  OK  t3   0.87s  orders      medium positive  | L&T announced a large new order (₹5-10 bn) for its Power Transmission
  OK  t4   0.83s  rating      high   negative  | CRISIL downgraded the company's long-term rating by one notch, indicat

4/4 classified; version=openaigptoss120b-0216a46c04
```

**Groq DOES support the forced `tool_choice` + enum schema without `strict`.** All four
returned in-taxonomy values. Judgment spot-check against the prompt's own rules:
t2 newspaper publication → `other/low` (correct, prompt calls this out explicitly);
t3 ₹5–10k cr order at L&T ≈ 2–4% of revenue → `medium`, not `high` (correct, the "high"
rule is ≥10% of revenue); t4 one-notch downgrade → `high/negative` (correct). Latency
~0.9s/row, so the 4,808-row backlog is ~70 min of wall-clock at 1 row/call.

## Evidence for the diagnosis (real, this session)

Prod DaaS reads the staging DB — so the cron classifier and the DaaS agree on one DB:

```
$ gcloud compute ssh nidp-stack-vm ... --command='systemctl show nidp-daas-api -p ExecStart; grep NIDP_POSTGRES_URL /opt/nidp/nidp.env'
ExecStart={ ... uvicorn nidp.services.daas_api.app:app --host 127.0.0.1 --port 8083 ... }
NIDP_POSTGRES_URL=postgresql://***:***@localhost:5434/nidp_staging
```

`run_service.sh:36` sources `/opt/nidp/nidp.env`, so the cron ingesters/classifier write to
that same `:5434/nidp_staging`. Backlog and freshness:

```
 unclassified | classified | total |          newest
--------------+------------+-------+---------------------------
         4808 |       3801 |  8609 | 2026-08-10 09:44:42+05:30

         last_classified
----------------------------------
 2026-07-25 15:11:53.000197+05:30

     d      | unclassified | classified
------------+--------------+------------
 2026-08-10 |            8 |          0
 2026-08-07 |         1268 |          0
 2026-08-06 |         1142 |          0
 2026-07-31 |          969 |          0
 2026-07-30 |          890 |          0
```

Ingestion is healthy (newest row is today); classification is 100% dead since Jul 25.

## Data Correctness (staging)

**NOT YET RUN — blocked on TC-9/TC-10.** No claim of a fixed feed is made in this report.

## Out of scope / still broken after this change

- **`document_parser` cannot follow the classifier to Groq.** Its OpenAI calls are
  (a) chunk **embeddings** — Groq has no embeddings API, and (b) **vision transcription**
  of scanned filings (`vision: OpenAI transcription failed ... credit_balance_exhausted`,
  still firing 2026-08-10T04:46Z). These continue to fail until OpenAI credits are restored.
  A dormant no-quota local backend exists (`nidp/shared/embeddings.py`: set
  `NIDP_EMBED_MODEL=bge-base-en-v1.5`) but it is 768-dim vs 1536-dim and would require
  re-embedding the whole corpus — a separate, large decision.
- **Silent failure is unfixed.** `announcement_classifier` logged `status=OK, fetched=0,
  inserted=0` on every 30-min tick for 16 days while 100% of calls failed, so
  `nidp.v_feed_status` stayed green and nothing alarmed. Flagged, not changed — it is
  outside the requested diff.
- **Separate ingestion gap.** No announcements at all on Jul 27–29 and Aug 3–5 (Mon–Wed
  both weeks) while Thu/Fri ingested normally. Not caused by the classifier. Needs its own
  investigation.

## Verdict: IN PROGRESS

## Inputs required from user

- **`GROQ_API_KEY` must be present in `/opt/nidp/nidp.env` on nidp-stack-vm.** It exists in
  GSM, but the NIDP venv cannot read GSM (`google-cloud-secret-manager` is not installed —
  `cannot import name 'secretmanager' from 'google.cloud'`), so every NIDP key resolves from
  that env file only. Reading the secret from GSM was blocked by the auto-mode classifier, so
  this step needs the user's approval or hand.
