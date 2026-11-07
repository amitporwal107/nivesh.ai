# Functionality Verification Report — homepage "Closing Bell" card was invisible

- **Branch:** fix/home-closing-bell-card-visible (from origin/dev 0695dd7f)
- **Date:** 2026-10-29
- **Author:** Claude (Full-Stack Developer + QA)
- **Changed areas:** backend: no · frontend src: yes (`pages/Homepage/index.tsx`, one effect)

## Summary
The first edition was published on staging on 29 Oct at 21:21 IST: 27 Oct, in five languages. A live check of
https://staging.niveshcopilot.com/v5/ then showed the "Closing Bell, every evening" section with an empty space
where its card should be.

The cause is the homepage's reveal-on-scroll effect. It observed `.rv` elements once, at mount. The card renders
after `/downloads/closing-bell/index.json` loads, so the observer never saw it and the card stayed at
`opacity: 0`. The fix re-runs the effect when the latest edition arrives, and only observes elements that have not
been revealed yet. The PR #395 tests missed it because Playwright's `toBeVisible()` treats opacity 0 as visible.
The tests now assert the computed opacity.

## Test Cases
| ID | Scenario | Type | Expected | Result |
|----|----------|------|----------|--------|
| TC-1 | Card fades in on desktop after scrolling to it | e2e | computed opacity "1" | PASS |
| TC-2 | Same on a 390 px phone (the only entry point there) | e2e | computed opacity "1" | PASS |
| TC-3 | The new assertion fails on the unfixed origin/dev build (reproduces the bug) | e2e | Received "0" | PASS (fails as expected) |
| TC-4 | Regression: market-commentary specs, homepage, blog | e2e | no new failures vs dev | PASS |
| TC-5 | tsc | build | exit 0 | PASS |

## Evidence (real output)
- **Unfixed origin/dev build, with the new assertion:**
```
Expected: "1"
Received: "0"
> 117 | await expect.poll(() => card.evaluate((el) => getComputedStyle(el).opacity), { timeout: 5000 }).toBe("1");
> 209 | (phone test, same assertion)
```
- **Fixed build** (`serving assets/index-0c_Jq4Xs.js`):
```
✓ TC-16 homepage: header link goes to the page; Closing Bell card opens the latest edition (5.8s)
✓ TC-16 homepage hides the Closing Bell card when nothing is published (1.1s)
✓ TC-16 phone: the homepage card is the way in; page fits without sideways scroll (2.5s)
  5 failed  50 passed
```
  The 5 failures are the pre-existing dev ones: blog-unauth TC-1 and TC-2, and three homepage.spec duplicate-button tests.
- **Typecheck:** `tsc exit 0`.

## Live staging (before this fix; data side already working)
- Edition list: `/downloads/closing-bell/index.json` reports latest 2026-10-27 with languages `['en','hi','ta','mr','gu']`.
- Chrome on the live page: each language plays its own mp4 with audio (duration 400 s) and shows its own transcript.
  The Hindi captions load 34 cues.
- The homepage card's link is `/v5/market-commentary/2026-10-27`, but the card renders invisible. This PR fixes that.

## Verdict: PASS
