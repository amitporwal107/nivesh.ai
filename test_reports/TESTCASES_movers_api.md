# Test cases — Top Movers Dashboard API (authored before implementation)

Derived strictly from the design (`frontend-v5/design/mover-dashboard/`). Each case names
the design element it backs, so a missing case means a dead control in the UI.

Target: staging `https://staging.niveshcopilot.com`. Auth: session cookie.

| # | Design element | Endpoint / case | Expected |
|---|---|---|---|
| TC-01 | Left rail list | `GET /api/movers` | `period`, `caught`, `total`, `movers[]` ranked by abs return |
| TC-02 | Filter ALL/UP/DOWN/MISSED | `?filter=UP` | every row `period_return > 0` |
| TC-03 | " | `?filter=DOWN` | every row `period_return < 0` |
| TC-04 | " | `?filter=MISSED` | every row `model.flagged == false` |
| TC-05 | Badge (3-state) | any row | `model.flagged` true, or false with `reason` in {BELOW_CUTOFF, NO_MODEL_RUN} |
| TC-06 | Chart + T marker | `GET /api/movers/{sym}?range=T7` | `bars[]` span T±7; `bars[move_index].t == move_date` |
| TC-07 | Range pills | `range=1D,1M,3M,1Y` | session count increases monotonically |
| TC-08 | Custom range | `range=custom&from&to` | window honours from/to |
| TC-09 | Event lanes | any event | has `lane`, `kind`, `offset`, `reaction`, `gap`, `vol_pre`, `vol_post`, `flip` |
| TC-10 | Insider / SAST lane | `lanes.ins` | `available:false`, `reason:NO_SOURCE_TABLE` — NOT an empty event list |
| TC-11 | Lane routing | events | announcements→fil, corporate_actions→ca, bulk/block→deal (dealB/dealS by side) |
| TC-12 | Odds-model lane | `model` | flagged: `tier`,`lead`,`p`,`flag_date`,`price_at_flag`,`flag_to_t1`; else `peak_score`,`cutoff` |
| TC-13 | AI card | `GET /api/movers/{sym}/analysis` | `attribution` sums to 1.0 ±0.01; `signals[4]`; `stats[4]`; `narrative` |
| TC-14 | Trade signals | analysis | gap≥2%/3%, vol≥2×/3× pre+post, coin-flip flags match design thresholds |
| TC-15 | Error handling | unknown symbol | 404 |
| TC-16 | " | `range=bogus` | 400 |
| TC-17 | Auth | no cookie | 401/403, never data |
| TC-18 | **Data test** | sampled bar vs `nidp.prices_eod` | OHLCV identical to DB for same symbol+date |
| TC-19 | **Data test** | sampled deal vs `nidp.bulk_deals` | client/qty/price identical to DB |

## DONE-GATE
All of TC-01..TC-19 executed against staging with real output pasted, OR a loud
`test_reports/OVERRIDE_*.md` with a REASON. TC-18/TC-19 are the mandatory data tests
(CONTEXT.md §1 "App AND data testing") — a 200 response is not proof the data is right.
