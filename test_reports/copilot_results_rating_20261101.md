# Functionality Verification Report — results rated Below / Meets / Above expectation, and the five-line AI commentary of an event

- **Branch:** fix/results-rating-labels (from dev 8fd54bfd = after #432), 1 commit
- **Date:** 2026-11-01
- **Author:** Claude (FULL_STACK_DEVELOPER + QA_ENGINEER)
- **Environment:** unit tests in `nivesh/backend:staging` (`--network none`, CI env vars); read-only in-process run inside `nivesh-staging-app-backend` over staging's real data; Playwright on a production build with mocked APIs. Not deployed.
- **Changed areas:** backend services (copilot_visual: events_builders, payload): yes · frontend src (Briefs card, schema): yes
- **Owner asks covered (31 Oct – 1 Nov 2026):** "We need to rate the results as Below/Meet/Above expectation"; "We need to provide a five line AI commentary: what looks extremely positive, moderately positive and neutral and negative", and the pasted format (What happened / Why it matters / Market impact / What to watch / AI take, with a 🟢🔴🟡⚪ signal, an impact level and a confidence).

## Summary
1. **Rating.** A declared result's badge is now `Above / Meets / Below expectation` (`Well above` / `Well below` for the desk's outstanding / well-below intensities), else `Not rated` with the reason in plain words (`Not rated: baseline too uncertain`, `no reliable baseline`). The desk already rated each result against the company's own baseline built from its past quarters; this is that rating in your words. No analyst consensus is held, so the counts strip says so: *expectation = each company's own baseline from its past quarters, not analyst consensus*. The filing's sentiment is no longer passed off as a rating (the old "Filing read: …" fallback badge is gone; the sentiment is in the commentary).
2. **Five-line commentary** on every analysed result card and every analysed feed event (orders, M&A, ownership, …): signal chip (positive / negative / mixed / informational, impact High-Medium-Low, confidence %) and five lines. Each line is assembled from the STORED AI read only: summary's first sentence, the stored positives or negatives (or both for a mixed read), the stored open questions, the band, the materiality score and the confidence. Nothing is generated again; a line the stored read does not support says "Not stated in the stored AI read." (the feed classifier stores no factors or open questions, so its cards show that on lines 2 and 4).
3. **Interpretation note.** I first read your "extremely positive / moderately positive / neutral / negative" as a grouped summary of a week's results and wrote tests for it; your pasted format made clear it is a per-event commentary with a signal, so I dropped the grouped summary. Say if you also want the grouped one.

## Test Cases
> Authored before the builder change; run failing first (the new tests failed against the old wording: `_verdict_badge` failures and the CM cases).

| ID | Area | Scenario | Type | Expected | Result |
|----|------|----------|------|----------|--------|
| EX-1 | rating | above (outstanding) / in line / below (well below) / none | unit | Above / Well above / Meets / Below / Well below expectation, else Not rated; a filing's sentiment never becomes a rating | PASS |
| EX-2 | rating | an unrated card | unit | `Not rated: baseline too uncertain` in the card's sub; the filing read stays in the body note | PASS |
| EX-3 | rating | counts strip and block note | unit | label `Above · meets · below`; "expectation", "own baseline", "not analyst consensus"; no "historical trend" | PASS |
| CM-1 | commentary | an analysed result with positives and open questions | unit | five labelled lines in order; line 1 = the stored text, first sentence, verbatim; line 2 = the stored positives; line 3 = Bullish + the band + the rating; line 4 = the stored questions; line 5 = signal, impact, confidence + "not a recommendation" | PASS |
| CM-2 | commentary | seven bands (extremely positive … strongly negative, none) | unit | tone up/warn/down/neutral, label, and Bullish / Mixed / Bearish / Neutral | PASS |
| CM-3 | commentary | why it matters | unit | positives for a positive read, negatives for a negative one, "For: … Against: …" for mixed | PASS |
| CM-4 | commentary | a stored read with no factors, no questions, no materiality, no confidence | unit | "Not stated in the stored AI read." and no invented impact or confidence | PASS |
| CM-5 | commentary | materiality 90 / 70 / 69.9 / 45 / 44.9 / 0 | unit | High / High / Medium / Medium / Low / Low | PASS |
| CM-6 | commentary | a result with no stored AI read | unit | no `commentary` at all, "Not analysed yet" | PASS |
| CM-7 | commentary | a feed event (orders) | unit | five lines from the one-liner, sentiment and impact; lines 2 and 4 "Not stated"; confidence null | PASS |
| CM-8 | contract | the validator | unit | accepts the commentary; rejects fewer than five lines and an unknown signal tone | PASS |
| EA-13…16 | UI | rating wording and counts strip · the commentary box with its chip and five lines · "Not stated" lines on an order card · phone width (no sideways scroll) | e2e | each value computed from the payload | PASS (16/16 in the events spec) |
| REG | regression | events-answers, visual-answer (the real capture, now with the new results_calendar and event_intelligence payloads), fno-detail, risk-profile, fno-board, sector-rotation, app, desk, decision cards, positions, daily-trader, copilot window, risk phase 1, risk desk, smart-money | e2e | no new failure | PASS |
| CI | regression | the full backend CI allowlist, baseline vs this tree | unit | no new failure | PASS |

## API / Endpoint Tests
No new HTTP endpoint; the change is in the builders `POST /api/chat/stream`'s visual pre-step calls.
- `tests/test_copilot_events.py` (CI env, full worktree mounted so the fixture drift check runs): **`177 passed`**. With the visual, chat, prompts, trade-idea and suggestions suites on the sparse mount: `507 passed, 2 skipped`.
- **Full CI allowlist** (the file list of the CI workflow as it stood at 25c61610; tree = origin/dev research/data/docs/scripts/tests + this worktree's backend and fixtures): **`13 failed, 7682 passed, 34 skipped`**. FAILED names compared with the origin/dev baseline list (`comm -13` and `comm -23`): **both empty — identical**. `test_copilot_events.py` (added to the CI list by #432) was run on the same tree separately: 177 passed.

## UI / Playwright Tests
Production build (`BUILD_EXIT=0`), `pw.copilot-app.config.ts`, `--network none`; `tsc --noEmit` → `TSC_EXIT=0`.
- events-answers (16) + the regression set above: **`242 passed, 5 skipped`** (the 5 skips are the opt-in screenshot tests).
- The screenshot of the results card was read by eye: badge `▲ Above expectation`, then the signal chip `● MODERATELY POSITIVE · MEDIUM IMPACT · CONFIDENCE 70%`, then five lines with bold labels, then the stored summary.
- **What the runs found (fixed, not hidden):** (1) my own first probe passed `request=None`, which the filings feed reader needs (`'NoneType' object has no attribute 'cookies'`); a harness slip, not a product defect (the real chat passes a request). (2) The probe's package-level `build` stayed bound to the deployed builders: I used `builders.build` from the overlay. (3) The fixture drift check failed after the change, as designed, and was regenerated from the real builder.

## Data Correctness (staging, read-only, in-process)
Overlay of this branch's `services/copilot_visual` inside `nivesh-staging-app-backend` (dev f30c7019 + #432 merged), auth stubbed, nothing written; overlay removed afterwards (checked).

**BEFORE (the deployed code, real output of the same question for last week):**
```
strip: [('Companies', '166'), ('Declared', '165'), ('Figures awaited', '1'), ('F&O names', '37'), ('Above · in line · below', '2 · 51 · 3')]
cards 8 | badges: {'Filing read: slightly negative': 1, 'Filing read: strongly positive': 2, 'In line with historical trend': 1, 'Filing read: moderately positive': 4} | with commentary: 0
```
**AFTER (this branch), unedited output:**
```
events_builders: /tmp/ov_b4/copilot_visual/events_builders.py
validate [] | as_of 2026-11-01 | stale False | missing 0
strip: [('Companies', '166'), ('Declared', '165'), ('Figures awaited', '1'), ('F&O names', '37'), ('Above · meets · below', '2 · 51 · 3')]
strip sub: 109 not rated · expectation = each company's own baseline from its past quarters, not analyst consensus
cards 8 | badges: {'Not rated': 7, 'Meets expectation': 1} | with commentary: 8
lines the stored read could not fill: {}
--- Hindustan Petroleum Corporation Limited | Not rated | Declared 22 Oct · Q2 FY27 (Jul–Sep 2026) · F&O · Not rated: baseline too uncertain
   chip: {'label': 'Slightly negative', 'tone': 'down', 'impact': 'High', 'confidence': 78}
   What happened: HPCL reported Q2 FY27 standalone net profit of ₹3,483 crore (versus ₹3,830 crore in Q2 FY26) on revenue of ₹1,39,140 crore, while H1 FY27 standalone shows a net loss of ₹8,044 crore against a ₹8,201…
   Why it matters: H1 FY27 standalone net loss of ₹8,044 crore versus ₹8,201 crore profit in H1 FY26. Q2 profit lower than ₹3,830 crore a year ago despite much higher GRM, suggesting pressure elsewhere, likely marketing.
   Market impact: Bearish — a slightly negative read of the results filing.
   What to watch: Cause and size of the Q1 loss are not given; Segment-wise profit for refining and marketing is not given
   AI take: Slightly negative · High impact · confidence 78% — an analysis of the filing, not a recommendation.
--- Hindustan Zinc Limited | Not rated | Declared 19 Oct · Q2 FY27 (Jul–Sep 2026) · F&O · Not rated: no reliable baseline
   chip: {'label': 'Strongly positive', 'tone': 'up', 'impact': 'High', 'confidence': 88}
   What happened: Hindustan Zinc reported Q2 FY27 revenue of ₹15,093 crore (up 77% YoY), EBITDA of ₹9,285 crore (up 108%) and net profit of ₹6,412 crore (up 142%).
   Why it matters: Record quarterly net profit and EBITDA, up 142% and 108% YoY, with margin up about 900 bps to 62%. Zinc cost of production down 29% YoY to $703/t on better grades, higher output and renewable power.
   Market impact: Bullish — a strongly positive read of the results filing.
   What to watch: How much of the profit growth depends on metal prices and exchange rates rather than lasting operating gains; Forward guidance on production, costs and capex
   AI take: Strongly positive · High impact · confidence 88% — an analysis of the filing, not a recommendation.
=== orders: cards 8 | with commentary 8 | validate []
--- Gayatri Projects Limited | Positive · high impact
   chip: {'label': 'Positive', 'tone': 'up', 'impact': 'High', 'confidence': None}
   What happened: Gayatri Projects has been awarded a contract by B-RIDE, under a joint venture, for design and construction of civil works from Bennigenahalli to Jakkur on Corridor-4 of the Bengaluru Suburban…
   Why it matters: Not stated in the stored AI read.
   Market impact: Bullish — a positive reading by the filing classifier.
   What to watch: Not stated in the stored AI read.
   AI take: Positive · High impact — an analysis of the filing, not a recommendation.
```
Real findings: of last week's 165 declared results the desk can rate 56 against their own baseline (2 above, 51 meet, 3 below); the other 109 are not rated (baseline too uncertain or no reliable baseline). The five lines were filled from the stored positives, negatives and open questions on every one of the 8 shown result cards and on all 8 orders cards (whose lines 2 and 4 are "Not stated" by design).

## UNVERIFIED
- **No analyst consensus is held**, so "expectation" is the company's own baseline: a result can "meet expectation" while missing what the street expected. If you want the street's expectation, a consensus feed and its licence are needed (the earnings tracker's P3).
- **Coverage is a third of the week:** 109 of 165 declared results (66%) cannot be rated at all, and only the results with a stored AI read get a commentary (this week the desk had read 113 of 494; call and guidance filings are almost all unanalysed). Extending that means running the event-AI analysis on more filings (cost and the shared login's limit), which this change does not do.
- Category-specific templates (promoter pledge, FII/DII, guidance credibility versus delivery, M&A fit and valuation) need data the stored reads do not carry; the lines are the same five for every category, and a line with no stored support says so.
- Not seen in a real browser on staging; the chat LLM's written explanation of these answers was not run; BSE/SEBI cards on real data (as in #432).
- Not deployed; the backend needs a process restart after a merge.

## Decisions for the owner
1. Is "expectation = the company's own baseline" acceptable as the meaning of Below / Meets / Above, until a consensus feed exists?
2. Should the analysis pipeline write the five lines itself for every filing (richer lines 2 and 4 for orders, deals and ownership, at the cost of LLM runs), instead of assembling them from the fields it stores today?
3. 66% unrated: run the analysis on more results first, or accept "Not rated" with the reason?

## Verdict: PASS
Scope: the backend (the allowlist has the same 13 failures as origin/dev), the card and the answers against MOCK payloads built by the real builders and the REAL staging capture, and the read-only staging run on real data. The real browser walk is open (as for #432).
