# Functionality Verification Report — Blog post: Research tab 2-minute tour (voiceover + EN/Hindi transcript)

- **Branch:** feat/research-tour-blog (PR #114 → dev)
- **Date:** 2026-07-21
- **Author:** Claude (Design Engineer + Full-Stack Developer)
- **Environment:** local mocked/static Vite (Playwright) — the blog is frontend-only, no backend
- **Changed areas:** backend routes/services: no · frontend src: yes

## Summary
Public blog post — **"Watch: a 2-minute tour of the Research tab"** — at
`/blog/research-tab-2-minute-tour`. It embeds the **real** recorded tour video, now with an
**Indian neural voiceover** in **English and हिंदी**, plus the matching transcript (on-page and
as caption `<track>`s). The English/हिंदी toggle switches the whole cut — voiceover video,
captions, and printed transcript — following the Copilot tour's `-hi` naming convention
(`research-tab-tour.mp4` = English, `research-tab-tour-hi.mp4` = Hindi).

Voiceovers are produced by a committed, reproducible tool — `e2e/tools/narrate-research-tour.py`
— which reads the `.vtt` cues (single source of truth), synthesises each line with edge-tts
(`en-IN-NeerjaNeural` / `hi-IN-SwaraNeural`), lays each clip at its cue timestamp, and muxes onto
the silent master (`research-tab-tour.webm`), freezing the final frame so the closing line lands.

## Test Cases
| ID | Area | Scenario | Type | Expected | Result |
|----|------|----------|------|----------|--------|
| TC-1 | Blog list | `/blog` shows the new post card | e2e | card + title visible | **PASS** |
| TC-2 | Routing | `/blog/research-tab-2-minute-tour` renders the article | e2e | `blog-article` + title | **PASS** |
| TC-3 | Video | Default player = English voiceover mp4 + poster + caption track | e2e | `research-tab-tour.mp4` + en.vtt | **PASS** |
| TC-4 | Transcript | Default English — on-page transcript + track are English | e2e | EN text + aria-pressed | **PASS** |
| TC-5 | Toggle | हिंदी switches source→`-hi.mp4`, track→`.hi.vtt`, transcript→Hindi | e2e | all three swap | **PASS** |
| TC-6 | Content | "What you'll see" stops + all 12 transcript cues render | e2e | counts match | **PASS** |
| TC-7 | Video | Download fallback points to the real mp4 | e2e | href ends mp4 | **PASS** |
| TC-8 | a11y | Language buttons `aria-pressed`; video accessible name | e2e | attributes present | **PASS** |
| TC-9 | Audio | The video carries a real audio track (voiceover), not silence | e2e | decoded audio bytes > 0 | **PASS** |

## UI / Playwright Tests
- **Spec:** `frontend-v5/e2e/tests/blog-research-tour.spec.ts`
  - Command: `npx playwright test blog-research-tour --project=desktop-chrome`
  - Output (real, unedited):
    ```
      ✓ TC-1 the post is listed on /blog (4.7s)
      ✓ TC-2 the card opens the article (5.5s)
      ✓ TC-3 default player is the English voiceover mp4 + poster + caption track (4.0s)
      ✓ TC-4 default is English — transcript + track are English (3.3s)
      ✓ TC-5 हिंदी toggle switches the transcript and the caption track (3.5s)
      ✓ TC-6 the six stops and all twelve transcript cues render (3.3s)
      ✓ TC-7 the download fallback points to the real mp4 (3.2s)
      ✓ TC-8 language buttons + video expose correct a11y (2.9s)
      ✓ TC-9 the video actually carries an audio track (voiceover) (1.9s)
      10 passed (24.1s)
    ```
  - Result: **PASS** — 10 passed. `tsc --noEmit` → 0 errors.

## Audio / Data Correctness
> The audio must be real speech, not silence — verified two ways.
- Playwright TC-9: muted playback decodes `webkitAudioDecodedByteCount > 0`. **PASS**
- `ffmpeg volumedetect` on the published mp4s:
  - `research-tab-tour.mp4` (EN): mean −22.7 dB, max −4.4 dB; speech at 0:05 / 0:50 / closing (100–103s). **PASS**
  - `research-tab-tour-hi.mp4` (HI): mean −21.8 dB, max −3.8 dB. **PASS**
  - Both: H.264 video + AAC audio, ~104s (silent master 101s + 3s frozen tail so the closing VO lands).
- Voice: `en-IN-NeerjaNeural` (Indian English) / `hi-IN-SwaraNeural` (Hindi) — **neural TTS, not a human read.**

## Assets
`public/research-tab-tour.mp4` (EN VO), `research-tab-tour-hi.mp4` (HI VO), `research-tab-tour.webm`
(silent master), `-poster.jpg`, `research-tab-tour.en.vtt`, `research-tab-tour.hi.vtt`.

## Inputs required from user
- none. **Note:** the Hindi voiceover + transcript are machine-generated (neural TTS + my own
  translation) — a native review is advised before this is merged/published.

## Verdict: PASS
