# Functionality Verification Report — Research Watchlist (public staging page)

- **Branch:** dev
- **Date:** 2026-10-06
- **Author:** Claude (full-stack-developer)
- **Environment:** staging (staging.niveshcopilot.com / nivesh_staging Mongo)
- **Changed areas:** backend routes/services: yes · frontend src: yes

## Summary
Publishes the 41-company "Inflection Watchlist" research (built earlier this session as a private
Claude Artifact) as a real, no-auth page on staging: a new Mongo collection
(`research_watchlist_picks`), a public FastAPI route (`/api/public/research-watchlist`), a
standalone React page (`/watchlist`, outside every `RequireAuth`/`RequireAdmin` wrapper per the
user's explicit choice), a one-off seed script, and a daily cron (`docker exec` into the running
backend container) that refreshes each symbol's current price via the existing DaaS price client
and recomputes `change_since_published_pct`.

## Test Cases
> Authored UP FRONT — after API + UI design, before implementation. One row per case.

| ID | Area | Scenario | Type | Expected | Result |
|----|------|----------|------|----------|--------|
| TC-1 | API | `GET /api/public/research-watchlist`, no Authorization/cookie header | api | HTTP 200, JSON `{meta, items}`, `items.length == 41` | PASS/FAIL |
| TC-2 | API | Each item has symbol/company_name/tier/published_price/published_date/change_since_published_pct | api | All present; `change_since_published_pct` is `null` or a finite number, never NaN/undefined | PASS/FAIL |
| TC-3 | Data | Seed script run once against staging Mongo | api/data | `research_watchlist_picks` has exactly 41 docs, `published_price`/`published_date` set from a real live DaaS price fetch at seed time | PASS/FAIL |
| TC-4 | Data | Cron script (`scripts.refresh_research_watchlist_prices`) run manually against staging | api/data | `current_price`/`current_price_date`/`price_updated_at` updated for every resolvable symbol; `change_since_published_pct` recomputed; symbols DaaS can't resolve are left with `current_price=null`, not a fabricated 0 | PASS/FAIL |
| TC-5 | E2E | Open `https://staging.niveshcopilot.com/watchlist` with a cold browser context (no session cookie) | e2e | Page loads (HTTP 200), no redirect to `/login`, 41 ticker cards render | PASS/FAIL |
| TC-6 | E2E | Tier filter chips (High/Caveat/Speculative) on the watchlist page | e2e | Clicking a chip changes the visible card count accordingly | PASS/FAIL |
| TC-7 | Edge | A symbol DaaS has no price for (if any) | edge | Card shows "price unavailable", not a crash or a fabricated change% | PASS/FAIL |

## API / Endpoint Tests (staging)
*(filled in after implementation — see below)*

## UI / Playwright Tests
*(filled in after implementation — see below)*

## Data Correctness (staging)
*(filled in after implementation — see below)*

## Inputs required from user
- none

## Verdict: BLOCKED
