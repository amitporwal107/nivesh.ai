# Nivesh — 90-second Investor Promo · Voice-over Transcript

**Pairs with:** `nivesh-investor-promo-90s.mp4` (silent, 1920×1080) and `.webm`
**Audience:** seed-stage investors · **Total runtime:** 90s
**Pacing:** ~205 words ≈ 137 words/min — a relaxed, confident read. Adjust TTS speed so each block lands inside its scene window (timestamps below match the on-screen scene changes, which are visually obvious cut points).

> **Honesty note (read before recording):** This script contains **no traction numbers**, on purpose. Every figure in the internal pitch deck (`/nivesh-pitch.md`) is flagged as a placeholder. Do **not** voice an invented metric — it ends deals in diligence. If you have *real* traction, splice the one optional line marked below into Scene 7.

---

## Timed narration (the part to convert to voice)

**[0:00 — Scene 1 · Hook]**
India has over four hundred million mutual-fund folios — and almost none of those investors can answer one simple question: *is my portfolio actually right for me?*

**[0:11 — Scene 2 · The problem]**
The reason? Advice is sold, not given. Holdings are scattered across CAS, demat, and a dozen fund houses. And every app stops at a number going up and down.

**[0:23 — Scene 3 · The product]**
Nivesh is an AI copilot — not a dashboard. Connect your real portfolio, and just talk to it. Ask *"am I too concentrated?"* and get an honest, personalised answer — with a clear action plan.

**[0:36 — Scene 4 · The moat]**
Anyone can wrap GPT around a portfolio. That's a demo. We built the layer underneath: NIDP — our data platform, with fifteen live market feeds and validated time-series. Proprietary scoring engines. A decision engine. And seventeen persona-aware recommendation engines.

**[0:52 — Scene 5 · Four front doors]**
One moat, four front doors. The same engine serves DIY investors, distributors, wealth managers, and traders — built once, monetised four ways.

**[1:04 — Scene 6 · Honest + the flywheel]**
It's honest by design: when we don't have the data, we say so. And broker-connect closes the loop — every accepted recommendation makes the engine smarter, while staying fully explainable.

**[1:15 — Scene 7 · Live in production]**
This isn't a slide deck. It's live in production today at niveshcopilot.com — the hard part, built end to end.
<!-- OPTIONAL, only if REAL: append one line here, e.g. "...with [REAL number] portfolios already connected and analysed." -->

**[1:24 — Scene 8 · The close]**
We're raising our seed round. Come build the intelligence layer for Indian markets with us. Nivesh.

---

## Plain transcript (no timestamps, for pasting into a TTS tool)

India has over four hundred million mutual-fund folios — and almost none of those investors can answer one simple question: is my portfolio actually right for me? The reason? Advice is sold, not given. Holdings are scattered across CAS, demat, and a dozen fund houses. And every app stops at a number going up and down. Nivesh is an AI copilot — not a dashboard. Connect your real portfolio, and just talk to it. Ask "am I too concentrated?" and get an honest, personalised answer — with a clear action plan. Anyone can wrap GPT around a portfolio. That's a demo. We built the layer underneath: NIDP — our data platform, with fifteen live market feeds and validated time-series. Proprietary scoring engines. A decision engine. And seventeen persona-aware recommendation engines. One moat, four front doors. The same engine serves DIY investors, distributors, wealth managers, and traders — built once, monetised four ways. It's honest by design: when we don't have the data, we say so. And broker-connect closes the loop — every accepted recommendation makes the engine smarter, while staying fully explainable. This isn't a slide deck. It's live in production today at niveshcopilot.com — the hard part, built end to end. We're raising our seed round. Come build the intelligence layer for Indian markets with us. Nivesh.

---

## Production notes

- **Voice:** a measured, warm Indian-English narrator works best for this audience. ElevenLabs / Play.ht / Azure Neural ("en-IN") all handle this script well. Keep delivery calm and declarative — the content is confident, the tone shouldn't oversell.
- **Pronunciation hints:** "Nivesh" = *ni-VESH*. "NIDP" = spell it out, *N-I-D-P*. "CAS" = spell it, *C-A-S*. "GPT" = *G-P-T*.
- **Music (optional):** a low, minimal ambient/electronic bed at ~-22 LUFS under the voice keeps it premium without competing.
- **Muxing voice onto the silent video** (once you have `voiceover.mp3`):
  ```bash
  ffmpeg -i nivesh-investor-promo-90s.mp4 -i voiceover.mp3 \
    -c:v copy -c:a aac -b:a 192k -shortest nivesh-investor-promo-90s-voiced.mp4
  ```
- **Sync:** the timestamps above line up with the on-screen scene cuts. If your VO drifts, nudge each block to start on its scene change — the cuts are clean and easy to spot.
