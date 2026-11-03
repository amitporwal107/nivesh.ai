# Functionality Verification Report — Homepage link to the Closing Bell market commentary

- **Branch:** feat/home-market-commentary (from origin/dev 48556220)
- **Date:** 2026-10-28
- **Author:** Claude (Design Engineer + Full-Stack Developer + QA)
- **Environment:** production build of frontend-v5 (`vite build` + `vite preview`, base `/v5/`) in the Playwright container; staging after merge
- **Changed areas:** backend routes/services: no · frontend src: yes (Homepage, Blog posts, new Blog article, public video assets)

## Summary
The owner asked for a link on the homepage where users can watch the "Closing Bell" market commentary video
(Tuesday 27 Oct 2026, 6:51, built from the Smart Trading Desk). It follows the existing video-post pattern
(Research and Copilot tour posts). It adds a blog post `/v5/blog/closing-bell-27-oct-2026` with the video,
an English caption track, a timestamped transcript, disclaimers and the music credit. It also adds a
"Market commentary" link in the homepage header that opens the latest market-commentary post. The post becomes
the first card in the homepage "From the blog" section.

## Test Cases
> Authored UP FRONT, after the UI design and before implementation.

| ID | Area | Scenario | Type | Expected | Result |
|----|------|----------|------|----------|--------|
| TC-1 | Homepage header | Desktop 1280×800: header shows a "Market commentary" link; clicking it opens the post | e2e | URL `/v5/blog/closing-bell-27-oct-2026`, `blog-article` visible, H1 mentions Closing Bell | PASS |
| TC-2 | Homepage header a11y | The link is a real anchor with an href, reachable by keyboard (Tab + Enter) | e2e / a11y | `href` ends with `/v5/blog/closing-bell-27-oct-2026`; Enter navigates | PASS |
| TC-3 | Homepage blog section | "From the blog" first card is the Closing Bell post and opens it | e2e | `blog-card-closing-bell-27-oct-2026` is the first card; click opens the article | PASS |
| TC-4 | Blog index | Post is listed on `/v5/blog` with category "Market commentary" | e2e | card visible, kicker contains "Market commentary" | PASS |
| TC-5 | Player markup | Video has poster, mp4 source, English caption track, accessible name, download fallback | e2e | poster/src/track/href match the asset names; accessible name mentions Closing Bell | PASS |
| TC-6 | Real media | The served mp4 is the real 6:51 bulletin with audio | e2e (media) | `loadedmetadata` duration 411–413 s; decoded audio bytes > 0 after a short muted play | PASS |
| TC-7 | Transcript | All 36 anchor lines and 8 section headings render, first and last line exact | e2e | 36 `li` cues; contains the opening and closing lines | PASS |
| TC-8 | Compliance text | Date and disclaimers visible: "27 October 2026", "not investment advice", ideas "for review, not recommendations", music credit | e2e | all four texts visible | PASS |
| TC-9 | Mobile 390×844 | Header link hidden by design (existing nav rule); homepage blog card opens the post; video fits, no horizontal scroll | e2e / responsive | card visible + opens post; `scrollWidth <= clientWidth`; video width ≤ viewport | PASS |
| TC-10 | Assets | Caption file is valid WebVTT and the served files are byte-identical to the produced ones | data | `WEBVTT` header, cue count > 0; sha256 of `dist/` assets = source files | PASS |
| TC-11 | Regression | Existing blog and homepage specs (`blog-research-tour`, `blog-unauth`, `homepage`) | e2e | no new failures against an untouched origin/dev build (wording changed after the run, from "all pass": 5 of these tests already fail on dev, see below) | PASS |
| TC-12 | Build | `tsc --noEmit` and `vite build` are clean | build | exit 0 | PASS |

## API / Endpoint Tests (staging)
Not applicable: no backend change. The blog is static frontend content.

## UI / Playwright Tests
Run in `mcr.microsoft.com/playwright:v1.47.0-jammy`, `@playwright/test` 1.60, against the PRODUCTION build
(`VITE_USE_MOCK_API=false VITE_BASE=/v5/ npx vite build` then `vite preview --port 5174`), `--network none`.
Before the tests ran, a check confirmed the branch build was the one being served: `served check: vtt 200`.
(A first attempt was discarded because a stale preview of the dev build was still on the port.)

- **Typecheck / build (TC-12):** `npx tsc --noEmit -p tsconfig.json` → `tsc exit 0`; `npx vite build` → `vite build exit 0`, `✓ built in 34.62s`.
- **Spec:** `frontend-v5/e2e/tests/homepage-market-commentary.spec.ts` (new) + `blog-unauth.spec.ts` + `homepage.spec.ts`
  - Command: `npx playwright test e2e/tests/homepage-market-commentary.spec.ts e2e/tests/blog-unauth.spec.ts e2e/tests/homepage.spec.ts --project=unauthenticated --reporter=list`
  - Output (new spec, real lines):
    ```
    ✓  21 › homepage-market-commentary.spec.ts:24:3 › TC-1 header 'Market commentary' link opens the Closing Bell post (3.5s)
    ✓  22 › homepage-market-commentary.spec.ts:35:3 › TC-2 the link is a real anchor, reachable by keyboard (3.7s)
    ✓  23 › homepage-market-commentary.spec.ts:45:3 › TC-3 'From the blog' leads with the Closing Bell card, which opens the post (3.9s)
    ✓  24 › homepage-market-commentary.spec.ts:56:3 › TC-4 the post is listed on /blog as Market commentary (2.2s)
    ✓  25 › homepage-market-commentary.spec.ts:64:3 › TC-5 player: poster, mp4 source, English captions, accessible name, download fallback (2.7s)
    ✓  26 › homepage-market-commentary.spec.ts:78:3 › TC-6 the media is the real 6:51 bulletin and carries audio (3.5s)
    ✓  27 › homepage-market-commentary.spec.ts:102:3 › TC-7 transcript: 8 sections, 36 lines, exact first and last line (2.4s)
    ✓  28 › homepage-market-commentary.spec.ts:114:3 › TC-8 date, disclaimers and music credit are visible (2.9s)
    ✓  29 › homepage-market-commentary.spec.ts:132:3 › TC-9 phone: blog card opens the post, the video fits and nothing scrolls sideways (4.3s)
    ✓  17 › blog-unauth.spec.ts:162:3 › TC-14: homepage 'From the blog' section shows the three newest posts (2.5s)
      5 failed
      35 passed (1.6m)
    ```
  - The 5 failures, identical on an untouched origin/dev build in a baseline run this session (`5 failed / 26 passed`), so they are NOT caused by this change:
    `blog-unauth` TC-1 and TC-2 (they expect `types-of-mutual-funds-india` as the newest homepage card, which has been stale since the tour posts were added);
    `homepage.spec` "renders nav bar with brand and CTA", "'Check my portfolio free' CTA navigates" and "'Watch the 90-second tour' does NOT navigate"
    (strict-mode violations: those buttons appear twice on the page).
  - `blog-unauth` TC-14 was updated on purpose. It asserted the "team of ten" flagship on the homepage, but the homepage shows the three newest posts (`POSTS.slice(0, 3)`) and the flagship is now fourth. It now asserts the three newest cards in order; TC-13 still covers the flagship on /blog.
  - Result: PASS (9/9 new, no new failures)
- **Spec:** `frontend-v5/e2e/tests/blog-research-tour.spec.ts` (`--project=desktop-chrome`) → `10 passed (20.4s)`. Result: PASS
- **Visual check:** screenshots of the production build at 1280×800 (header link, "From the blog" leading card, article with poster) and at 390×844 (article, player fits the width, shows `0:00 / 6:51`) were reviewed.

## Data Correctness
- Assets in the build are byte-identical to the produced files (sha256, first 16 hex):
  ```
  6dd42b477a7347d6 public/closing-bell-27oct2026-poster.jpg   = dist
  910089acecbbdb98 public/closing-bell-27oct2026.en.vtt       = dist
  0f1bc525db230072 public/closing-bell-27oct2026.mp4          = dist
  ```
- Captions: first line `WEBVTT`, 36 cues. These are the same 36 anchor lines as the transcript, which TC-7 checks on the page.
- Media: the browser reads duration > 411 s and < 413 s and decodes audio bytes > 0 (TC-6). The file is a 22 MB web encode (1080p, x264 CRF 31, AAC 128k, faststart) of the master bulletin.
- Bulletin figures themselves were cross-checked when the video was made: all 494 Nifty 500 one-day moves match the desk heatmap API, FII/DII from Sensibull, YoY profits from Trendlyne.

## Not verified here
- UNVERIFIED on staging: the page is only live after the PR is merged to `dev` and the frontend image rebuilds.
  After that: open `/v5/` → "Market commentary", and `/v5/blog/closing-bell-27-oct-2026`, then confirm the mp4 plays from the deployed image.

## Inputs required from user
- none for this build. Staging render needs the owner to merge the PR (a merge to `dev` deploys staging).

## Verdict: PASS
