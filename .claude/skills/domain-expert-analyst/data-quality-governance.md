# Pillar 4 — Market Data, Feeds & Data-Quality / Governance

This is what separates a real analyst from a plausible one: **before any number leaves your
mouth, you know where it came from and whether that source is currently trustworthy.** Every
analysis in the other pillars gates on this one.

## Know the feeds (the catalog is code, not memory)
- **Single source of truth:** `backend/nidp/shared/feed_registry.py` — `FEEDS` list with
  `cadence`, `monitored`, `slo_hours`, `severity`, `recoverable`. To answer "what feeds exist /
  what's the SLA / is it critical", read this, don't recall.
- **Source URLs & fetch policy:** `backend/nidp/shared/config.py`; NSE fetch/guards in
  `backend/nidp/shared/sources/`. **Wire schemas:** `backend/nidp/contracts/*.avsc`.
- **User-facing catalog (DB):** `nidp.feeds` (`032_nidp_feeds_subscriptions.sql`); readable
  catalogue `docs/NIDP_FEEDS/`, `NIDP_Feeds_Catalogue_Staging.pdf`.
- Feed families: equity market (bhavcopy, delivery, F&O, index constituents/close, corporate
  actions/announcements, bulk/block deals, pledge, shareholding), fundamentals (`nse_financials`),
  macro (`rbi_yields`, `fred_macro`), MF (`amfi_nav`, `amfi_nav_history`, `mf_holdings`,
  `mf_disclosure_snapshot`), international (`intl_etf_prices`).

## Data lineage — trace raw → analytic
Every analytic number has a chain: **source feed → `ingester_base` (fetch→parse→validate→write
→archive) → normalized table → engine (fundamental/technical/MF/v3) → DaaS → answer.** When a
figure looks wrong, walk the chain: is it a source problem, a parse problem, a stale feed, or a
compute bug? Provenance surface: `backend/routes/_nidp_feed_provenance.py`, `routes/feeds.py`.

## The data-quality gate — the queries you actually run
Before trusting data you compute on, run read-only checks (ask for the staging DSN if needed):

- **Feed freshness / status:** `nidp.v_feed_status` (`110_v_feed_status_dq.sql`) — is the
  feed's latest load within its `slo_hours`? A stale critical feed means the analysis is
  **UNVERIFIED**, full stop.
- **Blocking findings:** `nidp.validation_findings` (`006`) — any `severity='BLOCK'` in the last
  24h for the asset/feed you're using? If yes, the data is quarantined; say so, don't average
  over it.
- **Validation runs / DQ rollup:** `nidp.validation_runs` (`111`) — the quality verdict per run.
- **Trading calendar:** `backend/nidp/shared/trading_day.py` + `nidp.v_market_session`
  (`023`, `099`) — "no data today" may just be a market holiday, not a break. Check before
  crying wolf.

Example gate (shape only — use the real DSN/columns):
`SELECT feed_name, last_success_at, is_stale, dq_verdict FROM nidp.v_feed_status WHERE feed_name = '<feed>';`
then `SELECT count(*) FROM nidp.validation_findings WHERE severity='BLOCK' AND created_at > now() - interval '24 hours';`

## The DQ machinery (how the platform enforces quality)
- **Expectations / rules:** `backend/nidp/shared/expectations.py`,
  `backend/nidp/shared/validation/` (`runner.py`, `rules.py`, `quality_score.py`, `consistency*`,
  `consistency_rules/{equity,mf}.py`).
- **Gates:** `backend/nidp/shared/dq/` (`gate1_ingestion`, `gate3_snapshot`, `gate5_parquet`,
  per-feed YAML in `config/feeds/`, `config/gates/`); canonical runner
  `backend/nidp/services/quality_gate/` (`dq_runner.py`, `great_expectations_runner.py`,
  writes `validation_runs`); LLM-authored expectations `backend/nidp/services/dq_ai/`.
- **Resilience:** replay/failure-injection `backend/nidp/quality/replay/`
  (`engine.py`, `failure_injector.py`, `policy.py`); reconciliation/certification
  `backend/nidp/shared/{reconciliation,certification}.py`.
- **Drift guardrail:** `backend/nidp/tests/test_feed_registry_drift.py` — keeps registry ↔ cron ↔
  monitored ↔ backfill in sync; drift here is why feeds "silently" stop (see
  `HANDOFF-FEED-RELIABILITY.md`).
- **Self-healing / freshness:** `feed_health_check/` (freshness detector, `EXPECTED_FEEDS`),
  `feed_reconciler/` (heals missed trading days for recoverable feeds),
  `amc_urls_drift_check/`, `disk_monitor/`, `dlq_redrive/`; API `routes/data_health.py`.

## Governance dimensions an expert reasons about
Completeness (coverage vs universe), timeliness (within SLO), accuracy (matches golden source —
e.g. shareholding golden source `109`), consistency (cross-feed, e.g. price vs corporate action),
validity (schema/contract), uniqueness (dedup, e.g. MF holdings ISIN `113`), and lineage/
auditability. When advising on *building* an analytic, specify which of these its input feeds must
guarantee and at what SLA.

## Common failure modes (from this platform's real history)
Silent `SKIPPED` loads, dead/circular monitoring, config drift between registry and cron, no
auto-recovery, disk-full on the stack VM crashing Postgres (DaaS down → copilot tool errors).
See `HANDOFF-FEED-RELIABILITY.md` and the feed-reliability memories. If copilot tools error
platform-wide, suspect infra (disk/DB) before data.

## Definition of Done for a data-quality judgement
The exact feed(s) behind the number are named from `feed_registry.py`; `v_feed_status` freshness
and `validation_findings` BLOCK-checks were **run this turn** with output shown; a market-holiday
was ruled out; the verdict is explicit — "data trustworthy as of <load time>" or "UNVERIFIED:
feed stale/blocked because …". No analysis is presented as solid on data you didn't check.
