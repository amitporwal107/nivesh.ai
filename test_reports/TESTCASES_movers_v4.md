# Test cases — Top Movers **v4** in the Move odds screen

Authored 2026-10-03, BEFORE implementation. Owner picked v4 directly (AskUserQuestion) because v4 is
"fixes from review 3" and already carries every v2/v3 addition; building v2 then v3 would be thrown away.

## The honesty problem v4 brings, and the decision taken

v4's `LIFT` table is **hardcoded sample constants** (`{key:'gap2', un:2.1, in:1.3}`, …) and `liftAt()` adds a
deterministic sine-hash jitter to fake per-decile variation. Its own README says *"Flag lift constants remain
sample values; all data is synthetic."* The same applies to the mirror set and the calibration bars.

Shipping those numbers into a product screen would be presenting mock data as real, which this repo forbids
outright. **Decision: every v4 number is computed from `nidp` or it is not shown.** Where the data cannot
support a panel, the panel says so by name — the v1 pattern (degraded beta, empty insider lane).

## Formulas, taken verbatim from `Top Movers Dashboard v4.dc.html`

```
COST = 0.00628                                   # friction; matches this repo's measured 0.628%
execOf(bars, i, H):                              # H ∈ {3, 20}, chosen on screen
  if i+1 > N:            → out = PENDING
  nb = bars[i+1]; o = nb.o; end = min(N, i+H)
  gap   = nb.o / bars[i].c   - 1                 # overnight gap
  intra = nb.c / nb.o        - 1                 # open-to-close: the tradeable one
  re    = nb.c / bars[i-1].c - 1                 # close-to-close: kept, greyed, for reference
  net   = intra - COST                           # the number that matters
  up = any bars[k].h >= o*1.05 for k in i+1..end
  dn = any bars[k].l <= o*0.95
  out = BOTH if up and dn; UP if up; DOWN if dn; else PENDING if i+H > N else NONE
```
`NONE` is its own state and is **never** rendered as 0%.

Calibration: bands `BK` of width 0.05 from 0.40 (top band open-ended above 0.84). Over one population — every
session × name in the window = one flag-day. `pred = lo + 0.025`; `real = count(out != NONE) / n`.
**PENDING counts in the denominator of the population but is excluded from calibration.**

Mirror list ("flagged · no move"): names the model flagged, kept only where `execOf(...).out == NONE`, with
`PENDING` appended after them. Names that reach ±5% leave the list. Re-derived whenever H changes.

## Cases

| ID | Area | Case | Type | Expected |
|---|---|---|---|---|
| TC-V01 | API | `execOf` identity | api/unit | For a bar with a next session: `gap`, `intra`, `re`, `net` match the formulas above to 1e-12, and `net == intra - 0.00628`. |
| TC-V02 | API | Outcome states | api/unit | All five of UP / DOWN / BOTH / NONE / PENDING are reachable and correct against hand-built bars. `i+H > N` → PENDING, never NONE. |
| TC-V03 | API | Horizon switch | api | `H=3` and `H=20` give different outcomes for a name that moves on day 8; both are served and labelled. |
| TC-V04 | API | NONE is not zero | api | A `NONE` outcome carries no return masquerading as 0; the four return figures are still present and real. |
| TC-V05 | API | Mirror list | api | `GET /api/movers/flagged` returns only names whose outcome is NONE, then PENDING; a name that reached ±5% is absent; the count matches the switch label. |
| TC-V06 | API | Calibration population | api | One population: every session × name in the window. PENDING in the denominator, excluded from the bands. Bands are 0.05 wide from 0.40, top band open. |
| TC-V07 | API | Over-prediction ratio | api | Reported as predicted/realised over the population, computed — not the design's 2.8 constant. If the population is too small, it is withheld with a reason. |
| TC-V08 | API | Flag lift is real or absent | api | Each flag's unconditional lift and its within-volatility-decile lift are computed from nidp. **No value from v4's LIFT table is ever served.** A flag whose lift cannot be computed is returned with `available: false` and a reason. |
| TC-V09 | API | Verdict thresholds | api | SURVIVES / WEAK / DECORATION follow the design's cut-offs applied to the **computed** within-decile lift, not the sample one. |
| TC-V10 | API | New flags | api | `leak` (pre-event drift in the move's direction), `dealD1` (bulk/block deal on D-1) and `insNear` (insider activity ±3 sessions) each fire on real rows and are absent when the source is missing. |
| TC-V11 | API | Before/after beta ±1 SE | api | 20 sessions each side, each with a standard error; the row is **omitted** unless both sides exist. |
| TC-V12 | API | Benchmark label | api | The market leg is labelled by what it actually is. `index_eod` is thin, so if a Nifty-tracking ETF stands in, it is named as such and not called "Nifty 50". |
| TC-V13 | API | Sector coverage | api | An unmapped symbol returns the coverage pair (mapped / total) and no misleading sector number — never a fabricated 0. |
| TC-V14 | UI | Four returns per event | e2e | Close-to-close greyed and labelled "for reference", then gap, open-to-close, and **net in bold**. |
| TC-V15 | UI | Outcome pill | e2e | Every event shows UP/DOWN/NONE/BOTH/PENDING with distinct copy; NONE reads as "reached neither", not as a zero return. |
| TC-V16 | UI | Mirror switch | e2e | The sidebar switch flips between movers and flagged-no-move; the header shows how the flags turned out; the label counts the list actually shown. |
| TC-V17 | UI | Horizon switch | e2e | 3 sessions / 20 sits beside the range buttons and re-derives both the mirror list and the outcomes. |
| TC-V18 | UI | Calibration chart | e2e | Predicted (dashed outline) vs realised (filled) per band, the current stock's band highlighted, and the computed over-prediction ratio. |
| TC-V19 | UI | Flag lift card | e2e | Each flag shows unconditional lift struck through beside the within-decile lift and its verdict; DECORATION flags are dimmed on events. |
| TC-V20 | UI | No synthetic numbers | e2e | **Regression against v4's sample data.** No value from v4's LIFT table (2.1/1.3, 2.6/1.4, 2.4/1.05, 2.9/1.1, 1.2/0.95, 2.2/1.8, 4.4/4.0, 1.6/1.15) appears unless the computed value genuinely equals it. |
| TC-V21 | UI | Costs are stated | e2e | The 0.628% is named on screen wherever `net` is shown, so no one reads net as gross. |
| TC-V22 | UI | D2 + disclaimer hold | e2e | The v1 rules still pass across the new panels. |
