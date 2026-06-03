# Design artifacts

Static HTML / JSX / CSS design deliverables. Not part of the production app — these are reference prototypes used during the design phase. Each `.html` file is a self-contained artifact that loads its sibling JSX/CSS via plain `<script>` tags (no build step required).

## Index

| File | What it is |
|---|---|
| **`Nivesh redesign.html`** | Full design canvas — all 17 screens × desktop + mobile = 34 artboards. Pan, zoom, focus-mode. |
| **`Nivesh prototype.html`** | Interactive walkthrough of the 17 screens with keyboard nav, persona toggle, platform/theme toggles. |
| **`Nivesh retail.html`** | 6 simplified screens for the retail-investor variant — warm light theme, plain language, customizable. |
| **`Nivesh MVP.html`** | 5-screen MVP per the spec — white minimal, single accent, Keep/Reduce/Add recommendations. |
| **`Nivesh MVP-print.html`** | Print-to-PDF sheet of the MVP screens (A4 landscape, 10 pages). |

## Offline / standalone variants

Each artifact has two extra files:

- `… · offline.html` — single self-contained file, all dependencies inlined. Works without a server.
- `… · standalone-src.html` — pre-bundling source used by the inliner (with `<template id="__bundler_thumbnail">`).

The `… · offline.html` is the version to share for review (no install, no internet).

## Source files

JSX and CSS imported by the HTML artifacts. Loaded as plain `<script type="text/babel">` — Babel-standalone compiles in-browser.

- `screens-*.jsx` — the screen components, grouped by area
- `nivesh-*-tokens.css` — design tokens per variant (main / MVP / retail)
- `*-canvas.jsx` — the design-canvas mount per variant
- `design-canvas.jsx`, `tweaks-panel.jsx` — starter components (canvas frame, tweaks UI)
- `prototype-app.jsx`, `mvp-print.jsx` — special hosts (interactive walkthrough, print sheet)

## Relationship to the production code

The production app under `frontend-v5/src/` is a port of these designs to a real React + TypeScript + Tailwind codebase with backend integration. The design files here remain useful for:

- Reviewing visual intent without touching the code
- Sharing with stakeholders (each `… · offline.html` is one-file)
- Reference when re-implementing a screen
- A/B comparing the production output against the canonical design

Do not edit these to change the production app — they're reference, not source. Production source lives under `frontend-v5/src/`.
