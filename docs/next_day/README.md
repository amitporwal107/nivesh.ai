# Next-Day Conviction Engine — first run (research, shadow only)

PRD: `docs/prd/NEXT_DAY_CONVICTION_ENGINE.prd.md`. Nothing here is shown to users or is advice.

## Owner rules applied (7 Nov 2026)
- Every feature window is **10 sessions**; no input older than **one month** (21 sessions, 8 Oct – 6 Nov 2026).
  20-day averages became 10-session ones; RS20 → RS10; EMA20/EMA50 → SMA5/SMA10; 20-day high → 10-session high;
  ATR14 → ATR10. All thresholds and points are otherwise rubric v0 (PRD §7.2).
- **Sunday 8 Nov 2026 special (Muhurat) session is the next session** after Friday 6 Nov. Monday 9 Nov is also measured.

## Files
- `engine_v0_10s.py` — the exact code that produced the prediction (stdlib Python; reads CSV exports of the staging
  NIDP warehouse: `prices_eod` + `prices_eod_adjusted` EQ, `index_eod` Nifty 50, `fno_bhavcopy` STF/STO, `event_calendar`,
  `security_reference_daily`). `python3 -I engine_v0_10s.py <folder with e1..e7.csv>`.
- `summarize_lookback.py` — the 10-session look-back statistics.
- `predictions/2026-11-08_from_2026-11-06.json` — the frozen prediction, committed before the session opened; the
  engine's SHA-256 is inside.

## Look-back: the 10 sessions 23 Oct – 5 Nov, each scored with the next session known
Open → close of the next session, equal-weight list minus the equal-weight eligible universe.

| List | Days with names | Names | Up in the idea's direction | Mean excess / day | 95 % CI | After cost |
|---|---|---|---|---|---|---|
| F&O bullish | 9 | 36 | 20 (56 %) | −0.14 % | −1.01 … +0.73 | −0.34 % (futures 0.204 %) |
| F&O bearish (short side) | 6 | 15 | 6 (40 %) | +0.28 % | −0.68 … +1.25 | +0.08 % |
| Cash bullish (non-F&O) | 10 | 36 | 20 (56 %) | +0.06 % | −1.08 … +1.19 | −0.31 % (delivery 0.37 %) |
| Momentum only (top 5 RS10, F&O) | 10 | 50 | — | −0.10 % | — | — |

**Read:** no evidence of an edge, and none against one. Ten sessions cannot tell (the interval is about ±0.9 %).
The whole window is one regime: Nifty 50 rose from 22,524 (26 Oct open) to 25,030 (6 Nov close), and the universe
gained on most days. The rubric was written before these sessions were scored. The only changes made after the first
run were the bug fixes below, made before any outcome was printed.

## Traps found on this run
- `event_calendar.event_type` for results is **`quarterly_results`** (1,779 of 1,844 rows in the window), not "results".
- Results filed on a weekend or holiday must count for the next session: the rule is "dated after d, up to and including
  the next session".
- **Sunday sessions are never ingested:** `bhavcopy`, `delivery` and `index_close` cron `* * 1-5`, and `prices_eod` has
  no weekend rows at all. Sunday 8 Nov needs a manual ingest (a write to the shared warehouse, owner approval) or Kite
  quotes to be scored. After it, Monday's NSE `prev_close` is Sunday's close while our calendar skips Sunday.
- `fno_bhavcopy` lands at 22:15 IST; a nightly run must start after it.
