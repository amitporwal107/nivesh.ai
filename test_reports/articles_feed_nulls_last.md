# Functionality Verification Report — /api/markets/articles: material filings were invisible

- **Branch:** fix/articles-nulls-last (off origin/dev @ 9e239447)
- **Date:** 2026-07-17
- **Author:** Claude (Full-Stack Developer + QA)
- **Environment:** staging (staging.niveshcopilot.com / nidp_staging)
- **Changed areas:** backend routes/services: **yes** (`backend/routes/markets.py`) · frontend src: no

## Summary

`GET /api/markets/articles` was returning a feed of **100% unclassified noise**: 60/60 rows with
`event_category` NULL (rendered to the client as category `"Markets"`, `impact: null`), while the
same response's own facet counts reported **610 material filings** in the identical 7-day window.
Every material filing — orders, results, M&A, litigation — was invisible on page 1. This affects
the live `/markets/articles` page ("Stock Market News & Analysis").

One-clause fix: `ORDER BY (impact_score='high') DESC` → `... DESC NULLS LAST`.

## Root cause (proven, not inferred)

Postgres `DESC` defaults to **NULLS FIRST**, and `impact_score='high'` evaluates to NULL for an
unclassified row:
```
SELECT x, (x='high') FROM (VALUES ('high'),('low'),(NULL)) v(x) ORDER BY (x='high') DESC;
  x   | expr
------+------
      |        <- NULL sorts FIRST
 high | t
 low  | f
```
`_articles`' WHERE deliberately admits unclassified rows (`event_category IS NULL OR ...`), so the
un-triaged backlog sorted above every classified row and filled the `LIMIT`.

Why the backlog is so large — and why this was guaranteed to bite: the classifier's queue has a
30-day floor (`announcement_classifier/db.py`: `WHERE event_category IS NULL AND filed_at >=
NOW() - INTERVAL '30 days'`). Live: **126,994 of 146,102** announcements are permanently
unclassified ("unreachable" in `/pipeline/stages`). Any window reaching past 30 days is mostly
NULL.

## Test Cases

| ID | Area | Scenario | Type | Expected | Result |
|----|------|----------|------|----------|--------|
| TC-1 | Regression (the bug) | `GET /api/markets/articles?days=7` on staging BEFORE fix | api | Reproduce: rows dominated by category "Markets"/impact null | **PASS (bug reproduced: 60/60)** |
| TC-2 | Root cause | Postgres NULL ordering under `DESC` | api/db | NULL sorts first → unclassified wins the LIMIT | **PASS** |
| TC-3 | Fix · SQL | Endpoint's exact `list_sql` + `NULLS LAST`, real staging data | db | 0 unclassified rows in the returned page | **PASS (60/60 → 0)** |
| TC-4 | Fix · content | Same query, inspect rows | db | Page led by real category+impact rows | **PASS** |
| TC-5 | Compile | `py_compile routes/markets.py` | unit | compiles | **PASS** |
| TC-6 | Fix · live endpoint | `GET /api/markets/articles?days=7` AFTER deploy | api | majority carry a real `event_category`; ≥1 non-null `impact` | **BLOCKED — needs this commit deployed** |
| TC-7 | No regression | `?category=orders` still filters | api | only `orders` rows | **BLOCKED — needs deploy** |

## API / Endpoint Tests (staging)

**TC-1 — the bug, reproduced live (token supplied by user):**
```
curl -sk -A '<browser UA>' -H 'Cookie: session_token=…' \
  'https://staging.niveshcopilot.com/api/markets/articles?days=7'
HTTP 200  bytes=30682

category mix of the 60 rows returned :  Markets  60
'Markets' (= event_category NULL)    :  60/60
rows with impact == None             :  60/60
rows with impact == 'high'           :   0/60
facet counts, same window            : {management:202, dividend:66, earnings:66, mna:60,
                                        orders:59, rating:57, qip:51, litigation:28,
                                        capex:20, buyback:1}   = 610 material filings
```

**TC-2 — root cause at DB level:** see the VALUES query above. NULL sorts first. **PASS**

**TC-3 / TC-4 — fix verified against real staging data** (endpoint's exact `list_sql`, `NULLS LAST` added):
```
 event_category | impact_score | count        top of the list:
----------------+--------------+-------       PTCIL    orders     high  17 Jul 12:20
 litigation     | high         |    11        WEWORK   earnings   high  16 Jul 20:29
 orders         | medium       |     8        MANGALAM litigation high  16 Jul 18:09
 orders         | high         |     6        VALUEIND litigation high  16 Jul 16:56
 dividend       | low          |     6        DPSCLTD  litigation high  16 Jul 15:43
 mna            | medium       |     5        JNKINDIA orders     high  16 Jul 15:29
 ... 15 real category/impact groups total
```
Unclassified rows in the returned page: **60/60 → 0**. **PASS**

**TC-5 — compile:**
```
python3 -m py_compile routes/markets.py   → PY_COMPILE: OK
```

## Data Correctness (staging)

- Query: `SELECT count(*) FILTER (WHERE event_category IS NULL AND filed_at < NOW()-'30 days')` on
  `nidp.corporate_announcements` → **126,994 unreachable / 146,102 total**.
- Result: **PASS** — confirms the NULL population is structural (classifier 30-day floor), not a
  transient backlog, so NULLS FIRST was guaranteed to bury material filings. Product decision
  (user, this session): leave the floor as-is — the feed is a "today/this week" surface.

## Inputs required from user

- staging `session_token` — **supplied**, used for TC-1.
- Deploy consent for `dev` — **granted** ("yes please push to origin/dev"), scoped by me to this
  single commit rather than the 41-commit / 230-behind feature branch, which would have been a
  destructive force-push over `dev`.

## Verdict: BLOCKED
<!-- TC-1..TC-5 PASS with real evidence. TC-6/TC-7 verify the fix THROUGH the deployed endpoint
     and cannot pass until this commit is on dev/staging. Will be re-run and this flipped to PASS
     once deployed. Not claiming done before then. -->
