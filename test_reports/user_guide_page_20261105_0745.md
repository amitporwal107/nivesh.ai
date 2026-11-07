# Functionality Verification Report — User Guide page + homepage links (5 languages)

- **Branch:** feat/user-guide-page (from origin/dev 93cfb9b6)
- **Date:** 2026-11-05
- **Author:** Claude (full-stack developer + design engineer + QA)
- **Environment:** local production build (`vite build`, VITE_BASE=/v5/) served by `vite preview`; media files checked live on staging
- **Changed areas:** backend routes/services: no · frontend src: yes

## Summary
Owner asks (5 Nov 2026): "Please provide the links in the homepage. A complete User Guide" and "Where user can choose the
preferred language and the video link changes". Added a public `/user-guide` page (marketing shell, no backend): the 16:43
guided-tour video in English, हिंदी, தமிழ், मराठी and ગુજરાતી with language buttons that switch the video, its captions, the
direct video link and the share link (`?lang=` in the URL; the playback position carries over a switch), five chapters and
the complete written guide (43 sections, in the chosen language, each with a play-from time and "Open in the app ›").
Homepage: a "User guide" header link and a "Complete user guide" section whose five language buttons change its Watch link
(`/user-guide?lang=<code>`) and its direct video link. Videos stay on the staging host (`/downloads/promo/nivesh-copilot-da8691abbb/`);
the written guide is `frontend-v5/public/user-guide/<lang>.json`, generated from the video's script, timeline and translations.

## Test Cases
Authored before implementation: `test_reports/user_guide_page_TESTCASES.md`.

| ID | Area | Scenario | Type | Expected | Result |
|----|------|----------|------|----------|--------|
| TC-1 | Homepage | Header "User guide" link | e2e | anchor `/v5/user-guide`, Enter opens it | PASS |
| TC-2 | Homepage | Section default | e2e | English pressed; Watch `/v5/user-guide`; direct `…-en.mp4` | PASS |
| TC-3 | Homepage | Choose hi/ta/mr/gu | e2e | Watch `?lang=<code>`, direct `…-<code>.mp4` | PASS |
| TC-4 | Homepage → page | Tamil, Watch | e2e | page `?lang=ta`, Tamil video | PASS |
| TC-5 | Page | Default English | e2e | en video, en captions, poster | PASS |
| TC-6 | Page | Switch to Marathi | e2e | URL, video, captions, links, guide text in Devanagari | PASS |
| TC-7 | Page | `?lang=gu`; `?lang=xx` | edge | Gujarati; English fallback | PASS |
| TC-8 | Page | Chapters + section seek | e2e | 5 chapters; seek to 0:42 → currentTime > 41.5 | PASS |
| TC-9 | Page | Position kept on switch | e2e | at 20 s, switch to Hindi → new video > 19 s | PASS |
| TC-10 | Page | Complete written guide | e2e | 43 sections; "P&L"/"F&O"; app links | PASS |
| TC-11 | Page | Copy link | e2e | clipboard = page URL with `?lang=hi` | PASS |
| TC-12 | Page | Disclaimer per language | e2e | required phrases in all five | PASS |
| TC-13 | Page | Guide JSON fails | failure | notice; video + language switch still work | PASS |
| TC-14 | Both | 390 px phone | e2e | no horizontal scroll; section works | PASS |
| TC-15 | Page | Compliance copy | e2e | no SEBI-status claim; no buy/sell/stop loss/target words | PASS |
| TC-16 | Staging files | videos, captions, poster | data (curl) | 206 video/mp4 · 200 text/vtt · 200 image/jpeg | PASS |
| TC-17 | Regression | homepage + market-commentary + SEBI-claims specs | e2e | same failures as origin/dev | PASS (3 pre-existing failures, identical on dev) |
| TC-18 | Build | tsc + vite build | build | clean | PASS |

## API / Endpoint Tests (staging)
No backend change. The page reads only static files; TC-16 below checks them live.

## UI / Playwright Tests
- **Spec:** `frontend-v5/e2e/tests/homepage-user-guide.spec.ts` (project `unauthenticated`), against the branch build
  - Command: `npx playwright test --config playwright.config.ts --project=unauthenticated e2e/tests/homepage-user-guide.spec.ts`
  - Output (real, final run):
    ```
    Running 15 tests using 2 workers
      ✓   1 … TC-2 the guide section defaults to English: Watch and the direct video link (1.7s)
      ✓   2 … TC-1 header 'User guide' link is a real anchor that opens the guide (2.2s)
      ✓   3 … TC-3 choosing a language changes the Watch link and the video link (2.1s)
      ✓   4 … TC-4 Tamil chosen on the homepage opens the Tamil guide (2.2s)
      ✓   5 … TC-5 opens in English with the English video, captions and poster (1.6s)
      ✓   6 … TC-6 switching to Marathi changes the URL, video, captions, links and the written guide (2.0s)
      ✓   7 … TC-7 deep link opens Gujarati; an unknown code falls back to English (1.8s)
      ✓   8 … TC-8 chapters list with times, and a section's time seeks the video (1.4s)
      ✓  10 … TC-10 the complete written guide: all 43 sections, English uses P&L and F&O (1.4s)
      ✓   9 … TC-9 the playback position carries over a language switch (2.5s)
      ✓  11 … TC-11 Copy link puts the language's page URL on the clipboard (1.5s)
      ✓  12 … TC-12 the disclaimer is in the chosen language (3.3s)
      ✓  13 … TC-13 when the written guide fails to load, the video and languages still work (3.3s)
      ✓  14 … TC-15 compliance: no SEBI-status claim, and no trading-call words in our own copy (1.3s)
      ✓  15 … TC-14 the guide page and the homepage section fit a phone (1.7s)
      15 passed (17.6s)
    ```
  - Earlier runs, for the record: run 1 failed TC-8/TC-9 because the test's media mock answered without byte ranges
    (a media element cannot seek then; staging nginx does serve ranges, TC-16). Run 2 failed TC-8 on my own expectation
    (0:41 is the scene start; the section time is where its narration starts, 0:42). Both were test fixes, not page fixes.
  - Result: PASS
- **Regression (TC-17):** `homepage.spec.ts`, `homepage-market-commentary{,-daily,-opening}.spec.ts`, `unauth-no-sebi-claims.spec.ts`
  - origin/dev build: `4 failed · 2 skipped · 43 passed`; branch build: `3 failed · 2 skipped · 44 passed`.
  - Branch failures (all three also fail on origin/dev): `homepage.spec.ts:19 renders nav bar with brand and CTA`
    (`getByText('Nivesh', { exact: true })` not visible), `:53 'Check my portfolio free'` and `:69 'Watch the 90-second tour'`
    (strict mode: 2 elements). The baseline's 4th failure (`homepage-market-commentary.spec.ts:79 TC-6 the media is the real
    6:51 bulletin`) is an artefact of my baseline copy, which left out `public/*.mp4` to save disk; it passes on the branch.
  - Result: PASS (no new failure)
- **Build (TC-18):** `npx tsc --noEmit -p tsconfig.json` → `tsc exit 0`; `vite build` → `✓ built in 26.93s` (exit 0).
- **Visual check:** screenshots at 1440 px and 390 px of the homepage section (Hindi chosen) and the page (Hindi, Tamil,
  written guide) reviewed by eye: buttons wrap on the phone, the chosen language is highlighted, no overflow.

## Data Correctness (staging)
- **TC-16** — the files the page links to, fetched live (real output):
  ```
  nivesh-copilot-en.mp4  HTTP 206 video/mp4 (range 0-1023)
  nivesh-copilot-en.vtt  HTTP 200 text/vtt
  nivesh-copilot-hi.mp4  HTTP 206 video/mp4 (range 0-1023)
  nivesh-copilot-hi.vtt  HTTP 200 text/vtt
  nivesh-copilot-ta.mp4  HTTP 206 video/mp4 (range 0-1023)
  nivesh-copilot-ta.vtt  HTTP 200 text/vtt
  nivesh-copilot-mr.mp4  HTTP 206 video/mp4 (range 0-1023)
  nivesh-copilot-mr.vtt  HTTP 200 text/vtt
  nivesh-copilot-gu.mp4  HTTP 206 video/mp4 (range 0-1023)
  nivesh-copilot-gu.vtt  HTTP 200 text/vtt
  poster.jpg  HTTP 200 image/jpeg
  staging api healthz HTTP 200
  ```
- The written guide's section times come from the video build's `timeline.json`; the guide disclaimers were compared
  byte for byte with the narration's closing line in each language (5/5 MATCH).

## UNVERIFIED
- The page on staging itself: it goes live only when this PR is merged to dev (frontend image rebuild). After the merge:
  open `https://staging.niveshcopilot.com/v5/user-guide?lang=hi` and play a video.
- Disk: the app VM had 6.6 GB free during this work; the frontend deploy needs 6 GB. Check `df -h /` before merging.
- Production (niveshcopilot.com) is not touched: main is far behind dev, and the videos exist only on the staging host.
- The Hindi, Tamil, Marathi and Gujarati texts have not had a native-speaker review.

## Verdict: PASS
