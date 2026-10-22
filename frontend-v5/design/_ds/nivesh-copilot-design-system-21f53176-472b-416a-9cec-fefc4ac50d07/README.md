# Nivesh · Design System (V5)

> AI-powered wealth management for Indian retail investors & MFD advisors.
> This system captures the **V5 redesign** — a premium, dark-first fintech aesthetic — and supports
> **Nivesh Copilot**, the NIDP-grounded AI chat assistant in the *AI Copilot Chatbot* PRD.

---

## 1. Product context

**Nivesh** helps Indian investors who hold portfolios they don't fully understand. The Copilot
combines a real-time **NIDP-grounded data layer** (V3 Quality/Health/Exit/Add scores, live
portfolio, market context) with a multi-turn AI agent that **reads your portfolio and tells you
the one thing to fix first** — a ranked, ₹-impact-ordered action list, grounded in your actual
holdings, in plain language calibrated to your persona.

The signature interaction (`screens-chat.jsx`): you ask *"What's the one thing I should fix
first?"*, and the copilot answers with a **single editorial-serif synthesis sentence**, a
**portfolio score ring + six signal tiles**, and **the top 3 actions ranked by rupee impact** —
each with severity color, the move, and its ₹ effect. It is **not** a trade-execution engine, tax
filer, or SEBI-RIA; output is educational.

### Surfaces
One product, two layouts (both in the UI kit):
- **Desktop** — 240px history sidebar · NIDP status row · synthesis thread · glass composer.
- **Mobile** — full iPhone frame, notch + home bar, compact score card, action rows, pill composer.

Both ship in **dark (default)** and a **matched warm-cream light** theme.

---

## 2. Sources

Lifted from the company codebase — read the repos to go deeper:

| Source | What it gave us |
|---|---|
| **GitHub: [amitporwal107/nivesh.ai](https://github.com/amitporwal107/nivesh.ai)** (branch **`dev`**) | Primary source of truth. |
| `frontend-v5/design/nivesh-tokens.css` | **The V5 token system** — dark + matched-light surfaces, mint/amber/indigo/danger accents, Instrument Serif / Inter Tight / JetBrains Mono, shadows, radii, and the `.nv-*` primitives (card, pill, btn, glass, mark). |
| `frontend-v5/design/screens-chat.jsx` | `NVChatDesktop` + `NVChatMobile` — the canonical copilot chat screens (ported verbatim into the UI kit). |
| `frontend-v5/index.html` | The three V5 webfonts; the `न` favicon. |
| `frontend-v5/design/README.md` | The design-artifact system: 17 screens × desktop+mobile, plus retail & MVP variants. |
| `frontend-v5/design/*-tokens.css` | Variant palettes — `nivesh-retail-tokens.css` (warm light, simplified) and `nivesh-mvp-tokens.css` (white minimal, single accent). |
| `frontend-v5/src/` | Production React+TS port (charts, shared components) — reference for re-implementation. |

> Older surfaces (`frontend/` on `main`) use a different V2/V3 palette (emerald + Outfit/Figtree).
> **V5 supersedes them** — this system documents V5.

---

## 3. CONTENT FUNDAMENTALS

**Voice — a sharp, trustworthy analyst who reads your portfolio and tells you the truth, briefly.**
Editorial, confident, never hype.

- **One synthesis sentence, then the detail.** Every copilot answer opens with a single
  **serif headline** that states the verdict and names the problem — *"Your portfolio is healthy —
  but financials are eating a third of every rupee you've invested."* One accent word (usually
  mint) carries the judgment. Prose follows in ≤2 sentences, then structured data.
- **Rank by ₹ impact, always.** Actions are numbered `01 / 02 / 03` and ordered by rupee effect,
  each tagged with its severity color and its number (`+₹0.4L/yr`, `₹11,520 saved`, `-2.3 pt risk`).
- **Second person, imperative actions.** "Trim financials from 32% → 24%", "Harvest losses before
  Mar 31", "Consolidate 3 funds with 71% overlap". The agent is the `न` mark, not "I, the AI".
- **Indian money formatting:** `₹1.8L`, `₹38,400`, `₹24.8 L`, `₹14k/yr`. Tabular numerals everywhere.
- **Casing:** Editorial sentence case for synthesis + prose. **Mono UPPERCASE with wide tracking**
  for every label, pill, eyebrow, and metric caption — `NIDP CONNECTED`, `TOP 3 ACTIONS · RANKED BY
  ₹ IMPACT`, `GRADE A`, `DOWN 4 WOW`. This mono/serif tension is the brand's verbal signature.
- **Plain language by persona.** Beginner/conservative personas get jargon-free phrasing; active
  traders get RSI/MACD depth. Same data, different altitude.
- **Status is honest and quiet:** `NIDP CONNECTED` / `LIVE` mint pills with a dot; `last sync · 2m
  ago · 47 holdings` in mono. The SEBI educational disclaimer is present but never inline in a bubble.
- **No emoji.** Meaning is carried by accent color, the dot/pill system, and a few Unicode glyphs
  (`›`, `＋`, `↗`, `≡`, `●`).

---

## 4. VISUAL FOUNDATIONS

**Archetype: premium fintech — dark-first, editorial, saturated.** Near-black canvas with soft mint
& amber radial spotlights, hairline borders, an editorial serif for big numbers and synthesis, and
one confident accent (mint) for "good / primary". Think a private-bank terminal that respects your
attention. A **matched warm-cream light theme** inverts cleanly for daytime / print.

### Color
- **Surfaces (dark):** layered near-blacks `#06080F → #232B48` (`--bg-0..4`), plus a glass surface
  for floating bars. The frame paints two radial spotlights (mint top-right, amber bottom-left).
- **Surfaces (light):** warm creams `#F6F4ED → #DAD5C2`, white card.
- **Ink ramp:** `#F5F7FF → #2E3550` (dark) / `#12100A → #CFC9B5` (light) across 5 steps.
- **Accents (each with solid · soft 12% · line 28%):**
  - **mint** `#6AF0A8` — primary, "healthy/good", the score ring, primary button (dark).
  - **amber** `#FFB547` — caution / concentration.
  - **indigo** `#8E97FF` — informational / overlap / goals.
  - **danger** `#FF6B7A` — risk / exit. Plus **rose** `#FF8DC7` as a soft highlight.
  - Light theme desaturates each for AA contrast (mint `#0E8A55`, amber `#B86A12`, …).

### Type
- **Instrument Serif** (fallback Fraunces) — display: the synthesis sentence (32px), big metric
  numbers, brand wordmark, section titles. The editorial soul of the brand.
- **Inter Tight** (450–600) — body, UI, prose. Slightly condensed, `-0.005em` tracking, `ss01`/`cv11`.
- **JetBrains Mono** — every label, pill, eyebrow, metric caption, and raw number; UPPERCASE, wide
  tracking, tabular.

### Spacing, radii, layout
- Radii `6 / 10 / 14 / 20 / 28` — cards 14px, pills/glass fully or 16–999px. Generous card padding.
- Desktop thread `max-width: 980`; sidebar 240px. Mobile device 390×844 with notch + home bar.

### Surfaces, borders, shadows
- **Cards** = `--bg-1` on hairline `--line` with an **inset top highlight + deep soft drop**
  (`--shadow-card`); popovers use the heavier `--shadow-pop`.
- **Glass** = the composer / floating bars: `blur(20px) saturate(140%)` over `--bg-glass`.
- Borders are near-invisible hairlines (`rgba(255,255,255,.06–.18)`) — structure by tone, not lines.

### Motion
- Restrained. `transition: all .15s ease` on interactive elements (buttons brighten their border).
- The aesthetic favors stillness + typographic hierarchy over animation; no bounces or heavy fades.

### Imagery & iconography
- Data-first: the **score ring** (SVG, mint gradient stroke, serif number) is the hero visual; no
  photography. Status via dots/pills. Icons are **Unicode glyphs** in the design screens
  (`›ＦＦ↗≡●`); production chrome uses Lucide. See `assets/ICONS.md`.

---

## 5. ICONOGRAPHY
See `assets/ICONS.md`. Short version: **glyph-first** in the design (`न`, `›`, `＋`, `↗`, `≡`, `●`),
**Lucide** for production UI chrome, **no emoji**. The brand mark is `न` (Devanagari "na") in
Instrument Serif — **mint gradient on dark, ink gradient on light**.

---

## 6. Index — what's in this folder

| Path | What |
|---|---|
| `README.md` | This file. |
| `colors_and_type.css` | V5 tokens (dark+light) + `.nv-*` primitives + semantic type classes. |
| `SKILL.md` | Agent-Skill manifest for reuse in Claude Code. |
| `assets/` | `न` mark + wordmark (SVG), `ICONS.md`. |
| `preview/` | Design-System specimen cards (type, color, radii, components, brand). |
| `ui_kits/copilot/` | Copilot chat UI kit — `index.html` (desktop+mobile, dark/light toggles) + `screens-chat.jsx` (ported `NVChatDesktop`/`NVChatMobile`). |

---

## 7. Caveats / substitutions
- Fonts load from Google Fonts (Instrument Serif, Inter Tight, JetBrains Mono) — the exact set the
  app loads; no local TTFs needed.
- The UI kit ports the canonical `screens-chat.jsx` and adds only **theme + device toggles** as kit
  chrome — the screens themselves are unchanged from the design source.
- Variant palettes exist for **retail** (warm light, simplified) and **MVP** (white minimal). This
  system documents the **main** premium token set; ask if you want retail/MVP added as cards + kits.
