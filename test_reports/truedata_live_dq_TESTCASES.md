# TrueData data-quality checks: live shadow feed + nightly cross-check (PR-5) — test cases, written before the code

- **Branch:** `feat/truedata-live-dq`, from dev 0695dd7f.
- **Owner, 29 Oct 2026:** "make sure we keep data quality checks on TrueData", then "go ahead" with the two steps
  proposed:
  1. a TrueData live feed in shadow, with connection checks, per-tick checks and a comparison with Kite;
  2. the nightly TrueData-vs-NSE cross-check scheduled, with findings in the DQ tables and alerts.

TrueData never serves users in this PR. It runs beside our feeds only in `shadow` mode, and only with credentials
configured.

## Switch
| ID | Case | Expected |
|---|---|---|
| SH-1 | `shadow` + credentials, TrueData not integrated (`TRUEDATA_INTEGRATED = False`) | effective `shadow`: our feeds on, TrueData on (shadow never switches our feeds off, so it does not need the "integrated" gate) |
| SH-2 | `truedata` + credentials + licence, not integrated | effective `shadow`, reason TRUEDATA_NOT_INTEGRATED: TrueData cannot serve until integrated |
| SH-3 | `shadow` without credentials | `current`, TRUEDATA_NOT_CONFIGURED |
| SH-4 | `MARKET_DATA_SOURCE_FORCE_CURRENT=1` | `current` whatever the file says (the emergency way back is unchanged) |

## Live: message parsing (unit, synthetic messages in TrueData's documented format)
| ID | Case | Expected |
|---|---|---|
| LP-1 | Login reply: success / failure / "User Already Connected" | parsed: ok, segments, maxsymbols, subscription, validity date |
| LP-2 | `symbols added` and `touchline` arrays (Symbol, SymbolID, time, LTP, …, Ask, AskQty) | one quote per symbol; symbol ↔ id map learnt |
| LP-3 | `trade` array (id, time, LTP, LTQ, ATP, TTQ, O, H, L, prev close, OI, prev OI, turnover, tag, sequence, bid, bid qty, ask, ask qty) | quote updated for the mapped symbol, sequence kept |
| LP-4 | `bidask` array, including the `M/D/YYYY h:mm:ss AM` time format | only bid/ask of that symbol updated |
| LP-5 | Heartbeat and market-status messages | heartbeat time recorded; market status recorded |
| LP-6 | Unknown symbol id, malformed array | counted as a finding (UNMAPPED_ID / MALFORMED), never raises |

## Live: connection checks (group 1)
| ID | Case | Expected |
|---|---|---|
| LC-1 | Login failed / duplicate login | LOGIN_FAILED / DUPLICATE_LOGIN, alert; no retry storm (back-off) |
| LC-2 | Required segment (EQ, FO, IND) missing from the login reply | SEGMENT_MISSING |
| LC-3 | More symbols wanted than `maxsymbols` | only `maxsymbols` subscribed; the rest reported as SYMBOL_LIMIT (never filled in) |
| LC-4 | Login validity within 7 days | LOGIN_EXPIRING with the date |
| LC-5 | Requested symbol absent from the subscription reply | SYMBOL_NOT_SUBSCRIBED |
| LC-6 | No heartbeat for 15 s in market hours / 60 s | state `delayed` / HEARTBEAT_LOST, reconnect, alert |

## Live: per-tick checks (group 2)
| ID | Case | Expected |
|---|---|---|
| LT-1 | LTP ≤ 0 | PRICE_NONPOSITIVE; tick not used |
| LT-2 | LTP off the tick-size grid (tick size from TrueData's symbol master) | OFF_TICK |
| LT-3 | LTP outside the circuit band | CIRCUIT_BREACH |
| LT-4 | bid > ask (both > 0) | CROSSED_BOOK |
| LT-5 | high < max(open, LTP) or low > min(open, LTP) | OHLC_INCONSISTENT |
| LT-6 | day high falls / day low rises versus the previous tick | HIGH_DECREASED / LOW_INCREASED |
| LT-7 | total volume falls | VOLUME_DECREASED |
| LT-8 | OI negative; future OI 0 while the previous OI was positive or above 2,147,483,647 (known TrueData defect) | OI_NEGATIVE / OI_SUSPECT_ZERO |
| LT-9 | exchange time more than 5 s ahead of now / earlier than the previous tick | TS_FUTURE / TS_BACKWARDS |
| LT-10 | tick sequence number jumps | SEQ_GAP (counted, INFO until TrueData confirms the numbering is per symbol) |
| LT-11 | move above 10% (index) or 20% (stock without a circuit band) from the previous tick | JUMP_UNCONFIRMED |
| LT-12 | a symbol with no update for 5 s (index) / 30 s (stock, future) in market hours | STALE_SYMBOL, counted per minute |
| LT-13 | a clean tick | no finding |

## Live: comparison with Kite (group 4, live part)
| ID | Case | Expected |
|---|---|---|
| LK-1 | Same symbol, both quotes within 2 s of each other, LTP within max(1 tick, 0.05%) | counted `agree` |
| LK-2 | LTP apart beyond the tolerance | counted `disagree`, sample kept (symbol, both prices, both times) |
| LK-3 | Quotes more than 2 s apart in time | `not_comparable`, not a disagreement |
| LK-4 | previous close differs (TrueData vs Kite; both are NSE's official close) | PREV_CLOSE_MISMATCH |
| LK-5 | Kite has no quote (feed down, symbol not in its universe) | `no_kite_quote`, never a TrueData error |

## Live: runner and status endpoint
| ID | Case | Expected |
|---|---|---|
| LR-1 | `start()` at `current`, or without WebSocket credentials, or `TRUEDATA_SHADOW_ENABLED=0` | not started; returns False; no connection attempted |
| LR-2 | Two processes | one Mongo lease (`truedata_shadow`); only the holder connects (one login allows one connection) |
| LR-3 | Fake WebSocket: login → touchline → trades → heartbeats | quotes, per-minute DQ document and status document written; findings counted by code |
| LR-4 | No secret in any log line, status document or endpoint response | asserted |
| LR-5 | `GET /api/live/truedata/status` (signed in) | 200 with the state, the subscription, the last heartbeat, today's finding counts and the Kite agreement |
| LR-6 | Kite live feed | unchanged: starts as before; the TrueData shadow never writes Kite's collections or cache |

## Nightly cross-check: recording and alerts
| ID | Case | Expected |
|---|---|---|
| NR-1 | `--record`, all equal | job_log OK; validation_runs PASSED (ingester `truedata_crosscheck`) with coverage in `notes`; no alert |
| NR-2 | `--record`, mismatches or missing rows | one finding per rule (truedata.eq_mismatch / eq_missing / fo_mismatch / fo_missing) with samples; validation PARTIAL; alert |
| NR-3 | Only the known OI defect (NSE OI above 2,147,483,647, TrueData 0) | finding `truedata.fo_oi_overflow`, WARN / INFO; validation PASSED; no alert |
| NR-4 | TrueData call failed on a day NSE has rows | finding `truedata.call_failed` CRITICAL / BLOCK; job FAILED; alert |
| NR-5 | Switch at `current` | job_log SKIPPED with error_class SWITCHED_OFF; TrueData not called; no alert |
| NR-6 | No NSE rows for the date (holiday, or the files are not loaded yet) | job_log SKIPPED, NO_NSE_DATA; no alert |
| NR-7 | Cron line | weekdays 22:45 IST, after the last F&O file run (22:15), through `run_service.sh truedata_crosscheck --record` |

## Real runs (staging, read-only except the DQ rows the owner approved)
| ID | Case | Expected |
|---|---|---|
| RS-1 | Sandbox WebSocket login (50 symbols), after hours, from a scratch copy on the app VM | login ok; subscription within the limit; touchline parsed for every subscribed symbol; heartbeats about every 5 s; checks run with no false alarms on clean data |
| RS-2 | Nightly job `--record` for 28 Oct on the NIDP VM | job_log + validation rows written; the IDEA OI case recorded as `truedata.fo_oi_overflow` (not an alert) |
| RS-3 | Market hours (30 Oct, 09:15–15:30) after merge, credentials in place and the switch at `shadow` | per-minute DQ documents and Kite agreement for the whole session. UNVERIFIED until then. |
