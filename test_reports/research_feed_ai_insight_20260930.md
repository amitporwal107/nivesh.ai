# Functionality Verification Report — Research feed insights on Claude (no gpt-4o-mini)

- **Branch:** feat/claude-insights-framework
- **Date:** 2026-10-01
- **Author:** Claude (full-stack developer + QA)
- **Environment:** staging (staging.niveshcopilot.com / nidp_staging PG / nivesh_staging Mongo)
- **Changed areas:** backend routes/services: yes · frontend src: yes · staging data + cron: yes

## Summary
The owner asked to move the Research page's AI insights to the new architecture, with no dependency on gpt-4o-mini.
Before this change:
- The "Read for you" cards showed "Material filing — open for the AI insight." and an empty drawer.
- The insight generator (stage 7, gpt-4o-mini) had written 71 insights on 2026-09-18 and 1 since.
- The classifier (OpenAI/Groq) had scored 0 filings since 2026-09-24. So "ranked by materiality" was really newest
  first, and routine shareholder-meeting notices led the cards.

Now:
- **Insights:** `routes/filings._insights_for` reads the Claude corporate-event analysis first
  (`services/event_ai_insight.py`, Mongo `event_ai_analysis`, claude-sonnet-5, tools off). Insights stage 7 already
  stored are only read as a fallback; nothing calls gpt-4o-mini.
- **Materiality (owner choice 2026-10-01: "Claude filter score"):** `research/event_direction/ai_analysis/to_pg_scores.py`
  writes `event_category` / `impact_score` / `sentiment` into `nidp.corporate_announcements` with
  `classifier_version = 'claude-sonnet-5:filter_v1'`. It runs after the filter step and again at the end of
  `pipeline.sh` (every 2 h).
- **Cron:** the `announcement_classifier` and `filing_insights` lines in `/etc/cron.d/nidp-staging` are commented out
  (backup in `/root/nidp-staging.cron.bak.20261001`).
- **Card fallback:** a card without an insight shows the filing's own exchange label ("Shareholders meeting · no AI
  insight yet") instead of promising an insight.

## Test Cases
| ID | Area | Scenario | Type | Expected | Result |
|----|------|----------|------|----------|--------|
| TC-R1 | service | full analysis -> insight with summary, metric, Sentiment and Risks tabs | unit | shaped like a stage-7 insight | PASS |
| TC-R2 | service | NOT_ISOLATED analysis | unit | ignored | PASS |
| TC-R3 | service | two analyses of one filing | unit | latest wins | PASS |
| TC-R4 | service | kept by filter, not yet analysed | unit | title plus "full analysis pending" | PASS |
| TC-R5 | service | dropped by filter | unit | "Assessed as routine (importance N/100)", neutral | PASS |
| TC-R6 | service | second opinion keeps after a first-pass drop | unit | kept insight | PASS |
| TC-R7 | service | research input text | unit | never returned | PASS |
| TC-R8 | service | Mongo query isolated + projection; Mongo down | unit | {} not an error | PASS |
| TC-R9 | route | Claude first, legacy stage 7 only for uncovered ids | unit | legacy asked for the rest only | PASS |
| TC-R10 | ui | card without insight | e2e | exchange label + "no AI insight yet"; old promise gone | PASS |
| TC-R11 | data | Claude scores written to staging PG | data | rows tagged claude-sonnet-5:filter_v1 | PASS |
| TC-R12 | staging | /api/filings/signals and /insights after deploy | api (staging) | Claude one-liners on top cards | NOT RUN |

## API / Endpoint Tests
- `pytest tests/test_event_ai_insight.py tests/test_move_odds_filing_analysis.py tests/test_move_odds_routes.py -q`
  -> `34 passed in 0.83s`
- `MONGO_URL=mongodb://127.0.0.1:1 DB_NAME=test pytest tests/test_deterministic_insights.py -q` -> `5 passed in 0.86s`
  (the file needs `MONGO_URL` set before import; it does not connect)
- **TC-R12 staging:** NOT RUN. The routes reach staging only after this PR is merged to dev, and the endpoints need a
  logged-in `session_token`. UNVERIFIED on staging.

## UI / Playwright Tests
- `npx playwright test filings-intelligence research-move-odds --reporter=line` -> `66 passed (2.5m)` (TC-R10 included;
  signal fixtures labelled MOCK)
- `npx tsc --noEmit -p .` -> no errors

## Data Correctness (staging, real)
- Rollback file written before the update: `research/event_direction/ai_analysis/rollback_classifier_before_20261001.csv`
  (4,867 lines = header + 4,866 rows).
  - Previous labels: NULL 1,761 · claude-code-pattern-v1 1,656 · openaigptoss120b 725 · gpt4omini 724.
- `python3 to_pg_scores.py` output:
  - `verdicts: 4866 impact: {'low': 3069, 'medium': 1196, 'high': 601} sentiment: {'neutral': 2700, 'negative': 493, 'positive': 1673}`
  - `psql: CREATE TABLE COPY 4866 UPDATE 4866`
- PG check, high-materiality filings per day:

  | Day | high | scored | total |
  |---|---|---|---|
  | 2026-09-28 | 28 | 189 | 3,677 |
  | 2026-09-29 | 23 | 224 | 3,185 |
  | 2026-09-30 | 47 | 285 | 4,279 |

  Before the update, all of these were `0|0`.
- Mongo coverage, running the new module inside the staging backend container:
  `filings last 3 days: 7325 with an AI insight: 473 {'routine': 408, 'full': 65}`.
  Coverage grows as the 2-hourly pipeline works through the 30-day window.
- Known limit: filings outside the pipeline's candidate categories (for example AGM or shareholder-meeting notices)
  keep NULL scores and have no insight. The material sort ranks them last; their card shows the exchange label.

## Inputs required from user
- Merge the PR to dev (live staging deploy; app-vm had 3.9 GB free on 2026-09-30 16:16).
- After the deploy: a staging `session_token` for TC-R12.

## Verdict: BLOCKED
