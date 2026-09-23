# 2A Signals & Alerts and 4A Paper Trading — backend gap analysis

Date: 2026-09-23
Sources read: `docs/prd/live_trading_alerts_signals_prd.md`, `docs/prd/nivesh_paper_trading_prd.md`,
`docs/charting.md` §38.19 Amendment E, and the code named by both PRD filing headers.

**Short answer:** far more is built than the "not built" label suggested, and the missing pieces are
mostly **decisions**, not code. Three of the four blockers are owner decisions that only you can
clear. One blocker I thought was real — intraday market data — is **not** a blocker; measured today.

---

## 1. What already exists

| Requirement | Where | State |
|---|---|---|
| Lifecycle states + the research-state mapping | `research/charting/states.py` (11 KB, pure fn, own tests) | **built** |
| Pattern detection, 16 NI-3 types, frozen config hash | `research/charting/patterns.py` | **built** |
| Event dataset: schema + versioning (`EVENTS_SCHEMA_VERSION = 2`) | `research/charting/events/schema.py` | **built** |
| Outcomes: entry at next open, gap fills at open, AMBIGUOUS rule | `research/charting/events/outcomes.py` | **built** |
| Stops / targets / R framework (§37.2–§37.3) | `research/charting/events/stops.py` (354 lines) | **built** |
| Cost model: statutory + broker rules, 4 slippage scenarios, liquidity bucket | `research/costs/`, `events/costs_bridge.py` | **built** |
| Control arms, context join, extraction, pipeline, writer | `research/charting/events/` (2,367 lines total) | **built** |
| Read-only chart API over a hashed snapshot | `backend/routes/research_chart.py` | **built** |
| TPD paper engine (the kernel 4A must extend) | `/api/paper-trades` → DaaS; engine on `feat/paper-trade-engine` | **built, not on this branch** |

The execution and outcome mathematics that 4A describes in §13 and §17–§21 is largely **already
written** for the research path. 4A is mostly a matter of exposing it, not deriving it.

## 2. What is missing in code

**2A Signals & Alerts**
- No signal **contract** artefact: Phase 1 (§36) asks for the signal schema, alert schema, versioning
  and **timestamp semantics** to be defined and frozen. The *states* half exists (`states.py`); the
  schema/versioning/timestamp half does not.
- No transition enforcement: `states.py` derives a state, but nothing validates a legal transition.
- No alert layer at all: no aggregation (§15), no dedupe key `symbol + timeframe + pattern + state + bar` (§16).
- **No API surface.** There is no `/api/signals` and no `/api/alerts`. `backend/services/signal_detector.py`
  is portfolio-advisory signals — a different domain — and `grafana_alerts.py` is infra alerting.
- No intraday ingestion loop, no per-bar detector run, no push channel (§30 events, §31 latency).

**4A Paper Trading**
- `backend/nidp/services/tpd_model/paper/` is not on this branch (it lives on `feat/paper-trade-engine`).
- No charting-side paper API; `/api/paper-trades` today is the Ten-Percent-Days model, behind the
  `move_odds` allowlist, and proxies DaaS.
- Signal-only mode (§7.3) — "what would have happened if this signal had been traded" — is the piece
  that ships first per the amendment. It is close to what `events/` already computes.

## 3. The four gates — three are yours, not mine

1. **Study plan v2 has not reported.** `docs/ai_research/CHARTING_PREREGISTRATION_V2.md` reads
   **"Status: DRAFT — awaiting owner approval."** No v2 results file exists. Amendment E gates
   signals Phases 2–6 *and all of paper trading* on "after study plan v2 reports". This is the
   binding one: it blocks both features almost entirely.
2. **SEBI RA/IA (NI-1a) is unanswered.** Until it is, entry / stop / targets / quantity / capital at
   risk are **owner-allowlist only**, and the PRDs' "future advisor/MFD users" are out of scope.
3. **The 0–100 headline score is removed** by Amendment E position 2. §12 of the alerts PRD and
   §16/§23/§28 of the paper PRD still describe it. Components only; any composite must be
   pre-registered as a research object, tested, then shown. **The PRD text and the amendment differ
   here and the amendment governs** — worth correcting in the PRDs so nobody builds the number.
4. **Live push infrastructure does not exist.** §30 WebSocket/SSE events and §31 latency targets need
   a per-bar detector loop and a push channel. This is real engineering, gated on track F and track K.

## 4. Intraday data is NOT a blocker — measured today

I had this listed as a hard blocker. Using the token you supplied, measured on RELIANCE:

```
15minute  requested 200d ->  3338 bars | first 2026-03-09 09:15 | last 2026-09-23 15:00 IST
60minute  requested 400d ->  1854 bars | first 2025-08-20 09:15 | last 2026-09-23 14:15 IST
5minute   requested 100d ->  5139 bars | first 2026-06-16 09:15 | last 2026-09-23 15:10 IST
day       requested 400d ->   272 bars
```

So the §17 timeframes (15-minute, 1-hour, daily) are **all obtainable**, with 6–13 months of history —
enough to run the detector per-bar over history and to backtest the whole lifecycle on intraday bars.

Captured today for all 50 snapshot symbols, since the token expires ~06:00 IST tomorrow:
`research/kite_history/intraday_20260923/` — **166,974** 15-minute bars and **92,774** 60-minute bars,
50/50 symbols, zero failures, 15 MB, with a `MANIFEST.json`.

**What intraday data does not solve:** a genuinely *live* engine still needs a token that renews every
morning. Kite access tokens expire ~06:00 IST and the login requires a manual owner step — headless
login / OTP capture is against Zerodha's terms (this is already recorded as a project constraint). So
"live" means "batch replay on intraday bars, refreshed when you log in", not "always-on", until that
ops problem is solved separately.

This matches Amendment E, which already says: *"The first live version is end-of-day daily signals
from the batch replay."*

## 5. What I can build without you clearing any gate

Amendment E, position 1, verbatim: *"Only Phase 1 (§36: the signal contract, schema, versioning,
timestamp semantics, and the lifecycle mapping below) may be written now."*

That is a real, useful, self-contained piece of backend and it needs no market data and no v2:

- the signal schema and the alert schema, versioned, with a content hash (the same shape as
  `research/charting/indicator_catalogue.py`, which is already the pattern in this repo);
- the state-transition table, enforced, with `INVALIDATED` and `FAILED_BREAKOUT` kept distinct and
  `RETEST` / `CONTINUATION` modelled as **events on the row, not states**;
- timestamp semantics: bar time vs the time the detector could first have known vs publication time —
  the thing that stops look-ahead leaking into a live signal;
- the frozen PRD→research state mapping.

## 6. Recommended sequence

1. **Now, no gate:** Signals Phase 1 contract (above).
2. **Needs gate 1 only:** approve and run study plan v2 → unblocks signals Phases 2–5 and paper
   signal-only mode. This is the single highest-leverage decision.
3. **Needs gate 2:** answer SEBI RA/IA → lets setup values leave the owner allowlist.
4. **Needs gate 4 + ops:** the daily-token problem, then the per-bar loop and push channel.

## 7. Requirements I judge to be missing or wrong in the PRDs

- The **0–100 headline score** (alerts §12; paper §16/§23/§28) contradicts Amendment E and should be
  struck from both PRD bodies, not just overridden in the headers.
- The alerts PRD **§7 pattern list (14 types)** is superseded by the 16 NI-3 v1.0 types; it lacks
  inverse head & shoulders and the two pennants, and folds wedges and channels together.
- The paper PRD **lacks the AMBIGUOUS rule** (stop and target inside the same bar). Its own filing
  header says so: without it, paper results will not reconcile with v2 on the same events.
- Neither PRD states a **token-lifecycle requirement** for live data. Given the daily manual login,
  "live" needs defining — I read it as batch replay refreshed per login.
- Neither PRD defines what happens to an **open paper position when the snapshot is re-exported**
  (the config hash changes). Worth a rule before signal-only mode runs forward.
