# Test cases — Movers view inside the existing Move odds screen (v1 design)

Authored 2026-10-03, BEFORE implementation, per `.claude/VERIFICATION_PROTOCOL.md`.

**Scope.** The owner asked for the Top Movers Dashboard v1 design to land *in the existing Move odds
screen* ("update the existing odds move screen, no new dashboard"). So this is a third view on
`frontend-v5/src/pages/Research/MoveOddsScreen.tsx` — `Estimates | History | Movers` — fed by the
three `/api/movers` endpoints. No new route, no new page, no second dashboard.

**Rules inherited from the host screen** (these are test cases, not prose): the disclaimer stays
above every number (C4); D2's banned vocabulary applies outside the copilot stock card; direction is
a reading of two estimates, never a forecast, so it stays ink-coloured.

## Contract under test
- `GET /api/movers?from&to&min_abs_pct&direction&limit&include_ca`
- `GET /api/movers/{symbol}?session&range&from&to`
- `GET /api/movers/{symbol}/analysis?session&event_id`

All three now carry the screen's own gate (`require_feature("move_odds")`) **in addition to** the
session check, because they render inside a gated screen.

## Cases

| ID | Area | Case | Type | Expected |
|---|---|---|---|---|
| TC-M01 | Gate | Feature flag | api | 403 `feature_not_enabled` off the allowlist (admins included); 200 on it. The session check is unchanged and still runs. |
| TC-M02 | API | List window | api | `from`/`to` honoured; `min_abs_pct` defaults to 5.0; rows below `MIN_TURNOVER` absent; `to < from` → 400; >400-day window → 400. |
| TC-M03 | API | CA suspects withheld | api | `include_ca=false` (default) withholds suspected unadjusted splits and counts them in `withheld_ca_suspect`; `include_ca=true` returns them carrying `ca_suspect`. |
| TC-M04 | API | Badge is three-state | api | `odds.state` ∈ {CAUGHT, MISSED, NO_MODEL_RUN}. A session with no final run → NO_MODEL_RUN, never MISSED. A scored symbol below cutoff → MISSED with a score. Unscored but runs existed → MISSED + `reason: NOT_IN_SCORED_UNIVERSE`. |
| TC-M05 | API | Event lane is a lane key | api | **Regression.** Every event's `lane` ∈ {fil, ca, deal, ins, mdl} and `glyph` is non-null. (Before the fix `lane` held `_kind_of`'s prose note, e.g. "Quarterly financial results approved by the board.", so no event could be placed in a lane.) |
| TC-M06 | API | Event flags fire | api | **Regression.** An event whose `metrics.gap` is ≥ 2% in magnitude returns a `GAP UP/DN` flag; ≥2× volume returns a `VOL` flag; a reversal returns `COIN FLIP`. (Before the fix `_flags_of` was handed the bare event, whose gap/vol keys live on `metrics`, so `flags` was `[]` for every event.) |
| TC-M07 | API | Attribution identity | api | In each of BEFORE/EVENT/AFTER, `R == m_part + s_part + spec` to 1e-9 when `available`; `null` decomp when a leg is missing, never the whole move attributed to the stock. |
| TC-M08 | API | Beta honesty | api | `regression.sessions < requested_sessions` → `degraded: true` + a reason. The window ends at T−4, so the event session is never inside the sample. |
| TC-M09 | UI | Third view exists | e2e mocked | The toggle shows Estimates, History, **Movers**; `mv-view` renders the rail and the chart panel. The other two views are unchanged. |
| TC-M10 | UI | Rail → chart | e2e mocked | Clicking a rail row fetches that symbol's detail and the chart, lanes and attribution all re-render for it; the selected row is marked `aria-current`. |
| TC-M11 | UI | Range legend | e2e mocked | 1D / T7 / 1M / 3M / 1Y each refetch with that `range`; the rendered x-span changes; T7 is the default. |
| TC-M12 | UI | Lanes share the price x-scale | e2e mocked | For every event with a `bar_index`, its marker's centre x equals that bar's centre x (±1px). This is the whole point of the design — the chart and the timeline must be readable against each other. |
| TC-M13 | UI | Badge copy is distinct | e2e mocked | The three states render three different sentences. NO MODEL RUN must not read as a model failure — it is a coverage gap (the model ran on 9 of September's 21 sessions). |
| TC-M14 | UI | Attribution card | e2e mocked | Three windows, each splitting the move into market / sector / stock-specific, with the non-causal wording. A `null` decomp renders "not available" with its reason, not a zero. |
| TC-M15 | UI | Withheld notice | e2e mocked | `withheld_ca_suspect > 0` → a visible notice naming the count and a control to include them; toggling it refetches with `include_ca=true`. |
| TC-M16 | UI | Disclaimer still first | e2e mocked | In the Movers view the page disclaimer still precedes every number in the DOM (C4). |
| TC-M17 | UI | D2 vocabulary | e2e mocked | No BUY / HOLD / SELL / "recommend" anywhere in the Movers view (the copilot card is the only exemption and is not part of this view). |
| TC-M18 | UI | Degraded beta is visible | e2e mocked | When `degraded` is set, the card shows sessions used vs requested and the reason — never a silently shortened window. |
| TC-M19 | UI | Empty + error states | e2e mocked | Empty window → explicit empty state; detail 404 → "no price history" message; detail error → retry. No blank panels. |
| TC-M20 | UI | no_access | e2e mocked | A 403 on any movers call drops into the screen's existing not-enabled state and clears cached numbers. |
| TC-M21 | A11y | Keyboard + alternative | e2e mocked | Rail rows and range buttons are reachable and operable by keyboard; the chart is not colour-alone — events carry glyph + text, and a text alternative lists them. |

## testids (the contract between the view, the chart and the spec)

`mv-view`, `mv-rail`, `mv-rail-row-{SYMBOL}`, `mv-rail-empty`, `mv-withheld`, `mv-include-ca`,
`mv-badge`, `mv-badge-state`, `mv-range-{1D|T7|1M|3M|1Y}`, `mv-chart`, `mv-candle-{i}`,
`mv-session-marker`, `mv-overlay-market`, `mv-lane-{fil|ca|deal|ins|mdl}`, `mv-evt-{id}`,
`mv-evt-list`, `mv-tooltip`, `mv-attr`, `mv-attr-{BEFORE|EVENT|AFTER}`, `mv-attr-na`,
`mv-reg`, `mv-reg-degraded`, `mv-detail-error`, `mv-detail-retry`, `mv-insider-note`.
