# Functionality Verification Report — Blog post: Research tab 2-minute tour (+ EN/Hindi transcript)

- **Branch:** feat/research-qa-exercise
- **Date:** 2026-07-21
- **Author:** Claude (Design Engineer + Full-Stack Developer)
- **Environment:** local mocked/static Vite (Playwright) — the blog is frontend-only, no backend
- **Changed areas:** backend routes/services: no · frontend src: yes

## Summary
Adds a public blog post — **"Watch: a 2-minute tour of the Research tab"** — at
`/blog/research-tab-2-minute-tour`, registered in the static `POSTS` registry and rendered by a
new `ResearchTourArticle` body. It embeds the **real** recorded tour video (`research-tab-tour.webm`
+ `.mp4` + poster, already in `/public`) and provides a **transcript in English and हिंदी** — both
as caption `<track>`s (`research-tab-tour.en.vtt` / `.hi.vtt`) on the player and as an on-page
transcript printed below, driven by one shared `CUES` source. The recording is silent, so the
language toggle is honestly labelled "Transcript", not "Audio".

## Test Cases
> Authored UP FRONT — after design, before implementation.

| ID | Area | Scenario | Type | Expected | Result |
|----|------|----------|------|----------|--------|
| TC-1 | Blog list | `/blog` shows the new post card (`blog-card-research-tab-2-minute-tour`) | e2e | card + title visible | **PASS** |
| TC-2 | Routing | `/blog/research-tab-2-minute-tour` renders the article | e2e | `blog-article` + title | **PASS** |
| TC-3 | Video | Player has webm + mp4 `<source>`, poster, caption `<track>` | e2e | sources + track present | **PASS** |
| TC-4 | Transcript | Default English — on-page transcript shows English text; `lang-en` pressed | e2e | EN text + aria-pressed | **PASS** |
| TC-5 | Transcript | हिंदी toggle switches transcript to Hindi + track srcLang=hi | e2e | Hindi text visible | **PASS** |
| TC-6 | Content | "What you'll see" stops + all 12 transcript cues render | e2e | counts match | **PASS** |
| TC-7 | Video | Download fallback anchor (video fallback content) points to the real mp4 | e2e | href ends mp4 | **PASS** |
| TC-8 | a11y | Language buttons expose `aria-pressed`; video has an accessible name | e2e | attributes present | **PASS** |

## API / Endpoint Tests (staging)
> N/A — the blog is static frontend content; no backend routes/services changed.

## UI / Playwright Tests
- **Spec:** `frontend-v5/e2e/tests/blog-research-tour.spec.ts`
  - Command: `npx playwright test blog-research-tour --project=desktop-chrome`
  - Output (real, unedited):
    ```
      ✓ TC-1 the post is listed on /blog (3.6s)
      ✓ TC-2 the card opens the article (4.0s)
      ✓ TC-3 the player has webm+mp4 sources, a poster, and a caption track (3.1s)
      ✓ TC-4 default is English — transcript + track are English (3.1s)
      ✓ TC-5 हिंदी toggle switches the transcript and the caption track (3.6s)
      ✓ TC-6 the six stops and all twelve transcript cues render (3.1s)
      ✓ TC-7 the download fallback points to the real mp4 (3.2s)
      ✓ TC-8 language buttons + video expose correct a11y (3.1s)
      9 passed (18.9s)
    ```
  - Result: **PASS** — 9 passed (8 cases + auth-setup). `tsc --noEmit`: 0 errors.
  - Visual: screenshots captured — English article (full page, video + transcript + CTA) and the
    हिंदी transcript rendering correctly in Devanagari with timestamps.

## Data Correctness
> The "data" is the video + VTT assets. Verified present + resolvable (served by Vite from
> /public) and that the on-page transcript is one source (`CUES`) with the VTT cue text.

- Assets present: `public/research-tab-tour.{webm,mp4}`, `-poster.jpg`,
  `research-tab-tour.en.vtt`, `research-tab-tour.hi.vtt`.
- TC-3 confirms the player resolves webm+mp4+poster+track; TC-4/TC-5 confirm the EN and हिंदी
  transcript text renders and the `<track>` swaps `.en.vtt` ⇄ `.hi.vtt`. **PASS**

## Inputs required from user
- none (video already recorded in the prior step; transcript authored from the tour content).

## Verdict: PASS
