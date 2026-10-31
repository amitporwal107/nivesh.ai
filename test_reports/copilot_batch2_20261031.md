# Functionality Verification Report — Copilot answer fixes, batch 2: risk-profile answer, usage-limit message, F&O detail popup

- **Branch:** fix/copilot-batch2, stacked on fix/copilot-answers-batch (PR #430); 3 commits of its own
- **Date:** 2026-10-31
- **Author:** Claude (FULL_STACK_DEVELOPER + QA_ENGINEER)
- **Environment:** unit tests in `nivesh/backend:staging` (`--network none`, CI env vars); read-only in-process runs inside `nivesh-staging-app-backend` over staging's real code and data; Playwright on a production build with mocked APIs. Not deployed.
- **Changed areas:** backend routes/services (routes/chat.py, services/chat_errors.py, services/copilot_visual): yes · frontend src: yes
- **Owner asks covered (31 Oct 2026):** "How much should I risk?" showed the defaults as a stale "date unknown" profile (capture the profile when none exists);
  "Please fix this runtime error" ("trouble connecting"); "an option to show the OI chain and the futures build-up for the stocks, a popup, and open the chart analysis to create a paper trade".

## Summary
1. **Risk answer.** A risk profile is the user's own saved setting, not market data: it is never "stale" (it was always flagged "unknown date, older than the previous session"). With none saved the
   answer says so ("You have no saved risk profile; these are the platform's default limits"), titles the figures "Default risk limits", and offers **Set up your risk profile** (the Risk Desk's limits and profile).
2. **Usage-limit message.** The chat's "trouble connecting" was the assistant's own 5-hour usage limit (the staging model gateway shares the development login). The error now says that, with the reset time in IST, and that the figures and charts are unaffected; any other error keeps the generic text.
3. **F&O detail popup.** On the build-up chart and table (and the strongest-buildup list) a point or row opens that stock's option chain (the desk's own OI table and range bar) and futures build-up, with **Open in Chart Analysis ›** (Trade Desk › Chart Analysis for the symbol, where a paper trade can be created).

## Test Cases
> Authored before the implementation of each part; run failing first (PS: `3 failed` of the new ones; CE-5 failed until the route used the classifier; FD/RP written against the spec before the UI existed).

| ID | Area | Scenario | Type | Expected | Result |
|----|------|----------|------|----------|--------|
| PS-1 | risk answer | no saved profile | unit | no stale warning; notice with the set-up action before the figures; "Default risk limits"; headline says so; source row fresh, note "no profile saved" | PASS |
| PS-2 | risk answer | saved profile set 15 Jul | unit | never stale; "Your risk limits", "set 15 Jul 2026"; no ask | PASS |
| PS-3/4 | contract / failure | new action in the contract check; unreadable profile | unit | accepted / rejected; an unreadable profile is missing, never "no profile" | PASS |
| CE-1…4 | chat error | usage-limit text, reset time read only in IST, any other error generic, raw error never shown | unit | as stated | PASS |
| CE-5/6 | chat route | the stream fails with the gateway's real error / any other error | route (fake engine) | one error frame with the limit text and "10:50 AM IST"; the dashboard sent before it is kept; saved text = shown text; other errors generic | PASS |
| BD-1 | build-up | smart_money's quadrant and strongest list | unit | `detail: fno`; every row names its stock; no other block opens it | PASS |
| RP-1…4 | risk UI | no profile / the action opens Risk Desk limits / saved profile / the usage-limit banner | e2e | each value computed from the payload | PASS (4/4) |
| FD-1…9 | detail UI | payload flags · row Details › · chart point from the keyboard · futures and chain tabs · Esc, click outside, focus back · Open in Chart Analysis URL · ranked Details › · no F&O rows and phone sheet · screenshots (opt-in) | e2e | as stated | PASS (8/8; FD-9 opt-in) |
| REG | regression | fno-detail, risk-profile, fno-board, sector-rotation, visual-answer, app, desk, decision cards, positions, daily-trader, copilot window, risk-phase1, risk-desk, smart-money | e2e | no new failure | PASS |
| CI | regression | the full backend CI allowlist, baseline vs branch | unit | no new failure | PASS |

## API / Endpoint Tests
No new HTTP endpoint. `POST /api/chat/stream`'s error frame changed text only; it is exercised by CE-5/6 against the real route code with a fake engine.
- `pytest` copilot suites (full layout, CI env): see below with the allowlist.
- **Full CI allowlist, baseline on a clean `git archive origin/dev` with the same layout:**
  - origin/dev: `13 failed, 7619 passed, 34 skipped in 273.46s`
  - this branch (incl. #430): `13 failed, 7672 passed, 34 skipped in 255.16s`
  - FAILED names compared (`comm -13` and `comm -23` on the sorted lists): **both empty — identical lists**. +53 passed = the new tests of #430 and this batch.

## UI / Playwright Tests
Production build (`BUILD_EXIT=0`), `pw.copilot-app.config.ts`, `--network none`; `tsc --noEmit -p tsconfig.json` → `TSC_EXIT=0`.
- fno-detail, risk-profile, fno-board, sector-rotation, visual-answer, app, desk, desk-decision-cards, positions, daily-trader, desk-copilot-window, desk-risk-phase1, desk-risk-desk, desk-smart-money: **`223 passed, 4 skipped`** (the 4 skips are the opt-in screenshot tests VA-19, FE-9, SE-6, FD-9).
- **What the runs found (fixed, not hidden):** (1) the `UnderlineTabs` idPrefix I passed made its tab buttons share my `va-fno-chain` test id (strict-mode clash): renamed. (2) `useOptionChain` returns an object whose `.state` is the `ChainState`; `tsc` caught my misuse. (3) A route-level test first failed on my own undefined constant, which the route turned into the generic text — which also confirmed the fallback path.

## Data Correctness (staging, read-only, in-process)
Overlay of this branch's `services/copilot_visual` and `chat_errors` over the deployed tree inside `nivesh-staging-app-backend`, for a probe user id with no saved profile; nothing written; overlay removed afterwards (checked).

**Risk answer — BEFORE (deployed code), the owner's screenshot reproduced from real code:**
```
validate: [] | stale: True | as_of: 2026-10-31
headline: Your risk budget and today's usage.
notice: Your risk profile (risk_profiles) is from an unknown date, older than the previous session (30 Oct 2026): shown with its date, not as today's. | actions: []
kpis: limits | Your risk limits | owner-default-2026-10-27 profile (owner default: no profile saved yet)
sources: [('Your risk profile (risk_profiles)', None, 'stale', None), ("Your paper account's risk book (equity, ", '2026-10-31', 'fresh', None)]
```
**AFTER (this branch), unedited output** (also the classifier on the real gateway error text taken from the staging log):
```
builder file: /tmp/ov_b2/copilot_visual/builders.py
validate: [] | stale: False | as_of: 2026-10-31
headline: You have no saved risk profile; these are the platform's default limits.
notice: You have not set a risk profile yet. Your paper trades are checked against the platform's default limits below until you set your own. | actions: ['set_risk_profile']
kpis: limits | Default risk limits | Platform defaults, not saved by you: they apply to your paper trades until you set your own profile.
kpis: usage | Today's usage | 
sources: [('Your risk profile (risk_profiles)', None, 'fresh', 'no profile saved: platform defaults'), ("Your paper account's risk book (equity, ", '2026-10-31', 'fresh', None)]
classifier on the real text: The AI assistant has reached its usage limit, so it cannot write an explanation right now; it should be back around 10:50 AM IST. The figures and charts on your screen are not affected. Please try again later.
```
**Build-up detail flags on the real smart_money answer** (staging data of 30 Oct, 40 points): `blocks: [('kpis','flows',None), ('bars','fii',None), ('bars','dii',None), ('heatmap','rotation',None), ('quadrant','buildup','fno'), ('ranked','strongest','fno'), ('list','index_futures',None)]`, `validate: []`, `stale False`. That capture is now in `contract-visual-answer.json`.

## UNVERIFIED
- The popup was exercised in a browser only against the desk's F&O routes **mocked** from `fno-nifty.json` (synthetic, not market data). The routes and hooks are the desk's existing ones (unchanged); the real-data check of the build-up payload is above. Not seen against staging in a real browser session.
- "Open in Chart Analysis" is verified as the URL it opens (`?tab=trade&view=chart&sym=SYMBOL`); the desk's own handling of `sym` is existing behaviour, not re-tested here.
- The usage-limit text is verified on the gateway's real error text and a fake engine; it has not been produced by a real limit hit after deploy.
- Not deployed; the backend needs a process restart after a merge (staging-deploy-timing-trap). Disk was 6.9 GB free against the 6 GB a deploy needs.

## Decisions for the owner
1. **LLM capacity** (unchanged from #430): a dedicated API key or a separate login for `/opt/claude-gateway`, so development sessions stop exhausting the chat's limit.
2. The saved-profile note shows the date the profile was set; the full risk-profile capture (questionnaire, presets, admin policy) is the planned Risk Management work, not this change.

## Not built yet
Open trades from the broker book (5-second refresh), broker trades in the daily review, "Plan a bearish trade for X", the results and event-intelligence answers (AI summary, management commentary, source PDF), and the strategy builder and back-test in chat; and the plans for Risk Management and Screener/Watchlist.

## Cleanup
Containers `docker run --rm`; the staging overlays were removed (checked). Scratch under the session scratchpad.

## Verdict: PASS
Scope: the backend (the allowlist has the same 13 failures as origin/dev), the screens against MOCK payloads built by the real builder and the REAL staging capture, and the read-only staging runs on real code and data. The popup against real F&O routes in a browser is open and covered by `OVERRIDE_copilot_fno_detail_live_walk.md`.
