# Functionality Verification Report — Webinar page: pass preview + Zoom registration hand-off

- **Branch:** chore/webinar-registration-page (pushed to `dev`)
- **Date:** 2026-08-15
- **Author:** Claude (FULL_STACK_DEVELOPER + DESIGN_ENGINEER + QA_ENGINEER)
- **Environment:** local Playwright harness (mocked, `VITE_BASE=/v5/`)
- **Changed areas:** backend routes/services: **no** · frontend src: **yes**

## Summary

Third iteration on `/v5/webinar`. The user supplied a reference registration page
(theforumhouse.in — "The House of Family Office 2026") and asked for the same treatment.
That page's distinguishing features are a **digital pass preview** and a **branded
registration form** collecting name, designation, company, corporate email and phone.

Decision taken with the user: registration is handled by **Zoom**, not by us. Zoom collects
the fields, issues each registrant a unique join link, sends reminders, and keeps the
attendee list — none of which a self-hosted form provides without extra work, and it avoids
a net-new PII store on a stack with documented open security gaps.

Consequence for the page, and the key design call here: **it renders the pass preview and
the pitch but deliberately no input controls.** Reproducing the reference's form visually
while having no endpoint behind it would be a form that posts nowhere. The Contact page
already set this precedent by using mailto rather than a fake form. TC-10 now enforces it
as a permanent contract so a later change cannot quietly add inputs with no backend.

The page adapts automatically when the Zoom link changes type: `IS_ZOOM_REGISTRATION`
detects a `/meeting/register/` URL and switches the copy from "Join the webinar / Join on
Zoom" to "Claim your pass / Register on Zoom" and reveals the field preview. Today's link
is still a direct **join** link, so the join wording is what ships.

## Test Cases

`frontend-v5/e2e/tests/webinar-unauth.spec.ts` — TC-1..TC-8 pre-existing, TC-9..TC-11 new
and authored before this iteration's implementation.

| ID | Area | Scenario | Type | Expected | Result |
|----|------|----------|------|----------|--------|
| TC-1 | Routing | `/v5/webinar` unauthenticated | e2e | Renders, no `/login` redirect | PASS |
| TC-2 | Content | Talk is named | e2e | `<h1>` contains "Claude" | PASS |
| TC-3 | Content | Agenda | e2e | 6 agenda items | PASS |
| TC-4 | Contract | CTA never dead | edge | Every CTA anchor href truthy and ≠ `#` | PASS |
| TC-5 | Contract | Configured CTA branch | e2e | External anchor, `target=_blank`, `rel~=noopener` | PASS |
| TC-6 | Layout | Marketing shell | e2e | Nav/frame + brand | PASS |
| TC-7 | Edge | 390 px viewport | edge | Overflow ≤ 1 px | PASS |
| TC-8 | Failure | Unknown sub-path | failure | Resolves to a real page | PASS |
| TC-9 | Content | **Pass preview** | e2e | Tier + format visible; "When" not a placeholder | **PASS (new)** |
| TC-10 | Contract | **No fake form** | edge | 0 `form`, 0 `input`, 0 `textarea`, 0 submit buttons | **PASS (new)** |
| TC-11 | Contract | **Field preview matches link type** | edge | Join link → no field list + "Join"; registration URL → field list + "Register" | **PASS (new)** |

## API / Endpoint Tests (staging)

**N/A — no backend routes or services changed.** No endpoint was added; that is the point of
the Zoom hand-off. Nothing on this page reads or writes application data.

## Playwright (frontend)

```
$ npx playwright test webinar-unauth --project=unauthenticated --reporter=list

Running 11 tests using 2 workers

  ✓   2 [unauthenticated] › e2e/tests/webinar-unauth.spec.ts:30:3 › Webinar landing page › TC-1 renders unauthenticated without redirecting to login (6.6s)
  ✓   1 [unauthenticated] › e2e/tests/webinar-unauth.spec.ts:37:3 › Webinar landing page › TC-2 shows the webinar title (6.9s)
  ✓   3 [unauthenticated] › e2e/tests/webinar-unauth.spec.ts:43:3 › Webinar landing page › TC-3 lists the three live demos in the agenda (3.2s)
  ✓   4 [unauthenticated] › e2e/tests/webinar-unauth.spec.ts:54:3 › Webinar landing page › TC-4 registration CTA is never a dead link (3.0s)
  ✓   5 [unauthenticated] › e2e/tests/webinar-unauth.spec.ts:71:3 › Webinar landing page › TC-5 unconfigured registration says so and offers a real channel (3.2s)
  ✓   6 [unauthenticated] › e2e/tests/webinar-unauth.spec.ts:90:3 › Webinar landing page › TC-6 renders the marketing shell (3.2s)
  ✓   7 [unauthenticated] › e2e/tests/webinar-unauth.spec.ts:97:3 › Webinar landing page › TC-7 does not scroll sideways on a 390px viewport (3.1s)
  ✓   8 [unauthenticated] › e2e/tests/webinar-unauth.spec.ts:108:3 › Webinar landing page › TC-8 unknown route still resolves to a real page (3.8s)
  ✓   9 [unauthenticated] › e2e/tests/webinar-unauth.spec.ts:114:3 › Webinar landing page › TC-9 shows the pass preview with event, date and format (3.1s)
  ✓  10 [unauthenticated] › e2e/tests/webinar-unauth.spec.ts:128:3 › Webinar landing page › TC-10 renders no input controls, since it collects nothing (2.9s)
  ✓  11 [unauthenticated] › e2e/tests/webinar-unauth.spec.ts:138:3 › Webinar landing page › TC-11 field preview matches the registration mode (1.9s)

  11 passed (24.7s)
```

Result: **11/11 PASS**

## Typecheck

```
$ npx tsc --noEmit -p tsconfig.json
(no output — exit 0)
```

CSS classes used by the new pass card were checked against the stylesheet rather than
assumed:

```
  nv-pill        defs=5 OK
  nv-pill-mint   defs=1 OK
```

Result: **PASS**

## Data test

**N/A by design.** The page reads and writes no data. Recorded explicitly rather than
omitted, so the absence is a stated finding and not a skipped step.

## Notes / findings — open with the user

1. **The Zoom link is still a JOIN link, not a registration link.** Until "Registration
   required" is enabled on the meeting and the resulting `/meeting/register/…` URL is
   supplied, there is no registration, no attendee list and no reminders — the page
   correctly says "Join on Zoom" rather than claiming otherwise. `IS_ZOOM_REGISTRATION`
   flips the whole CTA once the URL is swapped; TC-11 covers both modes.
2. **40-minute risk unresolved.** `us05web` + a default meeting topic is characteristic of a
   Zoom Basic account (40-minute cap) against a 60-minute published run of show. Raised
   previously; still unanswered.
3. **Public link + embedded passcode.** `pwd=` grants entry. Enabling registration also
   fixes this, since each registrant then gets an individual link.

## Deferred / UNVERIFIED

- **UNVERIFIED: this commit on deployed staging** at the time of writing. Confirm by
  grepping the deployed bundle for `Attendee pass`.
- **UNVERIFIED: the `IS_ZOOM_REGISTRATION` true-branch against a real Zoom registration
  URL.** TC-11 exercises the branch logic, but no genuine `/meeting/register/` URL has been
  tested end to end because none exists yet.
- **UNVERIFIED: production.** Page is on `dev`/staging only; a public post needs a `main` PR.

## Verdict: PASS
