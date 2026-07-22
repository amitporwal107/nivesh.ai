# Functionality Verification Report — Filings Home API (step 1: feed + signals)

- **Branch:** fix/articles-nulls-last (off origin/dev)
- **Date:** 2026-07-17
- **Author:** Claude (Full-Stack Developer + QA)
- **Environment:** staging (staging.niveshcopilot.com / nidp_staging)
- **Changed areas:** backend routes/services: **yes** (app `routes/markets.py` + DaaS
  `market_pulse.py`) · frontend src: no

## Summary

Step 1 of `docs/FILINGS_HOME_SPEC.md`: give Design B's feed the two things it needs that don't
exist — a **`total`** (for `{{ count }}` + pagination) and a **`sort=material|latest`** toggle.

**Spec deviation, deliberate:** the spec proposed a new `GET /api/filings/feed`. I did NOT build
that. `_daas_first`'s docstring states that on **staging the app's own Postgres carries the nidp.*
schema but no rows**, so any new endpoint must be threaded through DaaS (DaaS router + daas_client
method + app route = 3 files, 2 deploy pipelines) — while `/api/markets/articles` already IS this
feed, with that plumbing proven and now un-broken (NULLS LAST, shipped earlier this session).
Extending it is the smaller change and serves both consumers. `topSignals` needs no endpoint at
all: it is `?days=1&limit=3` against the same feed.

Both `total` and `sort` are **additive** — omitting `sort` preserves today's exact behaviour, so
the existing `/markets/articles` page cannot regress.

## Test Cases
> Authored UP FRONT — after the API design (§3 of the spec), before implementation.

| ID | Area | Scenario | Type | Expected | Result |
|----|------|----------|------|----------|--------|
| TC-1 | `total` exists | `GET /api/markets/articles?days=7` | api | response has integer `total` | PASS/FAIL |
| TC-2 | `total` is a real count | same, `limit=10` | api | `total` > `len(rows)` — proves it isn't `len(articles)` | PASS/FAIL |
| TC-3 | `total` respects filters | `?days=7&category=orders` | api | `total` == the `orders` facet count | PASS/FAIL |
| TC-4 | sort=material | `?days=7&sort=material` | api | high-impact rows first; no unclassified on page 1 | PASS/FAIL |
| TC-5 | sort=latest | `?days=7&sort=latest` | api | strictly `filed_at` DESC (monotonic non-increasing) | PASS/FAIL |
| TC-6 | sort default | `?days=7` (no sort) | api | identical row order to `sort=material` — no regression | PASS/FAIL |
| TC-7 | sort validation | `?sort=bogus` | api/failure | 400 (not a silent fallback to a different order) | PASS/FAIL |
| TC-8 | pagination | `?days=7&limit=10&offset=10` | api | 10 rows, `total` unchanged, rows disjoint from offset=0 | PASS/FAIL |
| TC-9 | topSignals | `?days=1&limit=3&sort=material` | api | ≤3 rows, all with real category+impact | PASS/FAIL |
| TC-10 | honesty | any row | api | no fabricated `one`/`metric` keys present (deferred to step 3) | PASS/FAIL |

## ⚠️ Finding for the product owner — `sort=latest` surfaces the unclassified backlog

Verified on real data. `sort=latest` (pure recency) returns:
```
 ticker_symbol | impact |    filed
 ESSARSHPNG    | -      | 17 Jul 18:26
 BANKINDIA     | -      | 17 Jul 18:25
 HEXAGON       | -      | 17 Jul 18:25
 HERITGFOOD    | -      | 17 Jul 18:25
```
All unclassified. This is CORRECT behaviour and correct data — the classifier runs on a lag, so
the newest filings are always the least classified. But it means B's `LATEST` toggle renders rows
as category "Markets" with no impact, i.e. it will look broken while being honest.

`MATERIAL` is unaffected (NULLS LAST) and leads with `PTCIL/WEWORK/MANGALAM` high-impact.

Options — **product decision, not shipped either way**:
  (a) leave as-is: LATEST = true recency, unclassified rows visible (current);
  (b) drop `event_category IS NULL OR` from the feed's WHERE → both sorts show only classified
      rows. Cleaner, but hides genuinely-new filings until the classifier catches up, and changes
      the existing /markets/articles page's behaviour more than additively.
Not guessed. Raised for a decision.

## API / Endpoint Tests (staging)
_pending — run after deploy_

## Data Correctness (staging)

Pre-deploy verification of the new SQL against the real staging DB (real output):
```
=== TC-2/TC-3: total is a REAL count, not len(rows) ===
 total_all_material : 1388      (vs limit 60 → proves it is not len(articles))
 total_orders       :   59      (== the `orders` facet count → filters respected)

=== TC-4: sort=material leads with high impact ===
 PTCIL    high  17 Jul 12:20      WEWORK   high  16 Jul 20:29
 MANGALAM high  16 Jul 18:09      VALUEIND high  16 Jul 16:56

=== TC-5: sort=latest is strictly filed_at DESC ===
 ESSARSHPNG 17 Jul 18:26 · BANKINDIA 18:25 · HEXAGON 18:25 · HERITGFOOD 18:25
```
Result: **PASS** at SQL level. NOTE — this is the same class of evidence that proved insufficient
earlier today (right SQL, wrong code path). It is therefore NOT treated as sufficient here: TC-1..
TC-10 must pass through the DEPLOYED endpoint before this report reaches PASS.

## Inputs required from user
- staging `session_token` — supplied earlier this session.
- deploy consent for `dev` — granted; scoped to single fast-forward commits.

## Verdict: BLOCKED
