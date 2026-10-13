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
| **`Nivesh charting · offline.html`** | Charting proposal — **4 tabs**: 1A Chart, 2A Signals & Alerts, 4A Paper Trading, 3A Field Dictionary. Self-contained; open it directly. Added 2026-09-23. |
| **`Nivesh Copilot · offline.html`** | One-screen, chat-first Copilot redesign — a single shell (threads rail, ask box, answer thread, evidence panel) with Investor / Trader / Advisor modes, desktop and mobile. Self-contained; open it directly. Unpacked sources in `nivesh-copilot/`. Added 2026-10-13. |

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

### Charting (`Nivesh charting · offline.html`)

This one is the canonical design for the V5 Charts screen (`src/pages/Research/charts/`), alongside
the written spec in `docs/charting.md` §38. §38 owns behaviour and structure; this file owns
**composition** — bar heights, what is the headline, what is a pill, how dense the panels are. The
two are complementary, and a screen built from §38 alone will drift on composition, which is exactly
what happened before this file was added to the repo (see
`test_reports/charting_design_alignment_1a.md`).

It has no sibling `.jsx`/`.css` here — it is a single self-contained artifact, so it does not follow
the `… · standalone-src.html` pattern above.

#### The four tabs

Tab order is set in the artifact itself
(`[['1a','CHART'], ['2a','SIGNALS & ALERTS'], ['4a','PAPER TRADING'], ['3a','FIELD DICTIONARY']]`):

| Tab | Headline | Built? |
|---|---|---|
| **1A · Chart** | "A trader's chart, not a settings page" — 11 numbered changes | partly; the page frame was aligned 2026-09-23, 7 gaps remain |
| **2A · Signals & Alerts** | "One chart that answers: what is forming, and has it triggered?" | no |
| **4A · Paper Trading** | "Every signal carries its simulated outcome, after costs" | no |
| **3A · Field Dictionary** | "What every field on the screen means" | no |

Only 1A corresponds to a screen that exists today. 2A and 4A are specced as PRDs under `docs/`;
3A is a reference table, not a screen, and is the cheapest of the three to honour.

### Copilot (`Nivesh Copilot · offline.html` + `nivesh-copilot/`)

The one-screen Copilot redesign, exported from the Claude Design project "Nivesh Copilot redesign"
on 2026-10-13. The offline file is the export exactly as received. `nivesh-copilot/` holds the same
design unpacked into its component files so a screen can be read without decoding the bundle; it is
a read-only copy, not something the offline file loads.

**Every number, name and date in it is sample data** (the design itself labels this "illustrative
data"). Use it for layout, wording and states, never as a source of figures.

It has no `… · standalone-src.html` sibling. The `.dc.html` files use the design tool's own template
syntax (`{{ value }}`, `<sc-if>`, `<sc-for>`, `<dc-import>`); each ends with a script block that
holds the sample data and the view logic.

| File in `nivesh-copilot/` | What it holds |
|---|---|
| `Nivesh Copilot.dc.html` | The shell: left rail (threads, tools, workspace, internal), home, ask box with suggestions, the answer thread with its tool steps, the evidence panel, and five answer layouts (portfolio performance, stock research, sector scan, statement import, backtest). |
| `NVAnswers.dc.html` | Four more answer layouts: events and filings, fund overlap and rebalance, options, and a clarifying question. |
| `NVTools.dc.html` | Tools: portfolio analysis, recommendations, stock and fund research, screener, markets. |
| `NVIndex.dc.html` | F&O analyser card for an index or stock (levels, open interest, heavyweights). |
| `NVTrader.dc.html` | Trader desk. |
| `NVOptionsLab.dc.html` | Options lab: option chain, open interest, strategy builder. Trader mode only. |
| `NVPages.dc.html` | Workspace pages: watchlist and alerts, saved, action plan, portfolio ledger, paper trades, settings. |
| `NVBrokers.dc.html` | Broker connections. |
| `NVAdvisor.dc.html` | Advisor home: client book and mandate drift. |
| `NVOnboarding.dc.html` | Five-step onboarding, with broker / CAS / CSV import. |
| `NVOps.dc.html` | Internal pages: tool registry, feed health, audit log, KPIs. |
| `NVToolBuilder.dc.html` | Internal tool builder: define a new tool per persona. |
| `colors_and_type.css` | The design's tokens and `nv-*` helper classes. It names `nivesh-tokens.css` in this folder as its source. |

The shell takes six display settings, useful when comparing states: `theme` (dark / light),
`surface` (desktop / mobile), `demoState` (none, toolFailure, staleFeed, noPortfolio, smallSample),
`startView` (home / onboarding), `responseDetail` (compact / full) and `evidencePanel` (on / off).
In the offline file these are changed from the design tool, not from the page itself.
