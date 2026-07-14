# HANDOFF — Market-Data Feed Reliability (NIDP)

**Goal:** make all market-data feeds in staging + prod *seamless* — they must not break
silently, and when they do break they must recover (or loudly page a human) on their own.

**Status of this document:** Root causes below were identified by **code + config
inspection this session**. They are **NOT yet live-verified** against the prod/staging VM or
DB (no VM/DB access this session — this needs an SSH session on `nidp-stack-vm` or an admin
session token + DaaS reachability; see [prod-daas-disk-full-failure-mode]). The findings are
consistent with the documented recurring incidents. Every claim cites `file:line` so it can
be checked and acted on.

---

## 0. TL;DR — why feeds "break silently and never recover"

The platform has a **well-built ingestion core** (failure isolation, raw+parsed archive,
DQ gates, DLQ table, idempotent/resumable backfill). The reliability failures are almost
entirely in the layers *around* it:

1. **The one alarm that pages a human is broken.** The VM freshness check queries a column
   that doesn't exist, so it errors out and **never sends a single alert**.
2. **Monitoring is circular** — every monitor reads/writes the same VM Postgres it watches,
   so the dominant outage (disk-full → Postgres crash-loop) makes the monitoring go *blind*
   at exactly the moment it's needed, and even *silences* the Grafana alarms.
3. **Nothing retries or catches up.** A failed run waits 24h for the next cron slot; a
   multi-day outage leaves permanent gaps because the (idempotent, resumable) backfill is
   manual-only, and the DLQ is write-only.
4. **Failures are mis-classified as "no work."** HTTP-200 HTML error pages and unexpected
   empty payloads become `SKIPPED`, which *resets the failure counter* — so a broken feed
   looks *healthier* than a failing one.
5. **Config has drifted** across 4+ hand-maintained feed lists, two schedulers, and a
   **staging cron that is disabled by default** (staging feeds don't run at all).

---

## 1. Root causes (grouped, with evidence)

### Theme A — The recurring infra outage is neither prevented nor detected
| # | Root cause | Evidence |
|---|---|---|
| A1 | Root disk is ~49–50 G and runs ~98 % full from real data; **no growth automation, no capacity headroom.** | [prod-daas-disk-full-failure-mode] incident notes |
| A2 | Docker log caps (`max-size:50m`) not honored by long-lived containers created before the config; crash-loop logs reached ~910 M and finished the disk. | same |
| A3 | **No disk-space monitor or alert anywhere.** `container_health_collector.py` collects CPU%/mem only; `service_health_collector.py` does HTTP/`pg_isready` probes only; no `df`/`node_filesystem` metric, no GCP disk alert. | `backend/nidp/deploy/vm/container_health_collector.py:207-208`; `.../service_health_collector.py:53-65`; only logrotate exists (`deploy/vm/bootstrap.sh:87-101`) |

### Theme B — Monitoring is architecturally circular and, in prod, effectively unwired
| # | Root cause | Evidence |
|---|---|---|
| B1 | **Circular dependency:** collectors + `health_check.sh` read/write the *same* VM Postgres they monitor, so a DB-down incident blinds the monitoring. | `service_health_collector.py:159` (writes results via asyncpg to the same PG); `health_check.sh:64-73` |
| B2 | **Prometheus + Alertmanager are not deployed in prod** (only loki/promtail/grafana), so every `severity: pager` rule (`NIDPIngesterFailed`, staleness, `NIDPDLQBacklogHigh`, Gate1 P0) is **dead config**. Cron ingesters don't even serve `/metrics`. | `deploy/vm/docker-compose.infra.yml:15-86`; `prometheus_rules.yml:97,154,168`; `run_service.sh` (no metrics server) |
| B3 | **Grafana's only notification receiver is a self-webhook** → writes a row to `monitoring.alert_events` + an in-app banner. **No email/Slack/PagerDuty.** Nobody is paged. | `grafana/.../contact_points.yaml:51-68`; `backend/routes/grafana_alerts.py:110` |
| B4 | **GCP Cloud Monitoring policies have an empty `notification_channel_ids`** (`REPLACE_ME`, no committed tfvars), and key off app JSON logs, not the VM-cron feeds. | `alerts.tf:224`; `variables.tf:13-17`; `terraform.tfvars.example:10-12` |
| B5 | During a DB-down, **Grafana rules query the down DB → `execErr` → `noDataState: OK`** — the outage actively *resolves* the alarms to healthy. | `grafana/.../alert_rules.yaml:51,98` |
| B6 | The one human-paging path (`health_check.sh` → Telegram) is **triple-broken**: (a) queries non-existent column `service` → always errors → misreports "cannot connect to postgres" and exits **before** sending; (b) gated on Telegram tokens that are blank in the env template; (c) on DB-connect failure it `exit 1` with **no** Telegram send. | `health_check.sh:64,70-73,102`; `nidp.job_log` column is `ingester` (`migrations/001_nidp_base.sql:29`); `nidp.env.example:22-23` |
| B7 | `feed_health_check.py` (the *good* detector — freshness + history-depth) is **scheduled by nothing** (0 references in `deploy/`). Its `sys.exit(1)` and ERROR logs reach no notifier. | `services/feed_health_check/__main__.py:228,249`; grep of `deploy/` = 0 |
| B8 | **DaaS `/health` returns HTTP 200 even when `db_ok:false`**, and `service_health_collector` marks up on `200<=status<500` **without inspecting the body** → records `daas-api` **UP** during a DB outage. | `services/daas_api/routers/health.py:26-32`; `service_health_collector.py:142` |

### Theme C — No automatic recovery, retry, or catch-up
| # | Root cause | Evidence |
|---|---|---|
| C1 | `BaseIngester.run()` catches → logs → **re-raises with no retry loop**; `run_service.sh` runs the module **once** and exits. A failed feed waits ~24h for its next cron slot. (Note: the *fetch* layer does retry transient HTTP 5xx/429/timeout 4× w/ backoff — that's within one download, not a failed-run retry.) | `shared/ingester_base.py:339-344`; `run_service.sh:52-63`; `shared/sources/nse_fetcher.py:195,214,221` |
| C2 | **No automatic gap catch-up** after a multi-day outage. `backfill.py` is holiday-aware and idempotent/resumable (skips `(ingester, date)` already OK) — but **manual-only**; not wired to cron/scheduler. | `backend/nidp/backfill.py:130-174`; `services/backfill/__main__.py`; grep of `deploy/` for backfill = 0 |
| C3 | **DLQ is write-only.** `dq.dlq_findings` has `replay_status` + `replayed_at`, but **no code ever flips a row to `REPLAYED`** or re-runs the feed from it. Readers only *count* PENDING (gauge / gate-block / status API). | `migrations/077_dq_gates_schema.sql:95-120`; writer `shared/dq/gate1_ingestion.py:157-191`; readers `quality_gate/__main__.py:77-86`, `gate3_snapshot.py:341-346` |
| C4 | Cron failure email disabled (`MAILTO=""`), so the runner's "cron will notice" fallback is off — leaving the broken Telegram path as the sole alarm. | `nidp.cron:15` |

### Theme D — Silent failure classification ("unsupported content" + SKIPPED conflation)
| # | Root cause | Evidence |
|---|---|---|
| D1 | **HTTP-200 HTML / "Access Denied" / CAPTCHA / maintenance pages are trusted at the fetch layer** — the fetcher returns any 200 body as success; no shared content guard. All mismatch detection is pushed down to each parser. | `shared/sources/nse_fetcher.py:180-189` |
| D2 | Parser robustness is **inconsistent**: bhavcopy/delivery/index_close/corporate_actions raise loudly on bad content (→ FAILED), but **`amfi_nav` and `rbi_yields` have no schema guard** → HTML → 0 rows → **SKIPPED** (silent), even though amfi_nav is an ERROR-severity feed. | `amfi_nav/service.py:110-116`; `rbi_yields/parser.py:246+`; vs `bhavcopy/parser.py:72`, `delivery/parser.py:52-56` |
| D3 | **`SKIPPED` conflates "holiday/no-work" with "source broke," and resets `consecutive_failures = 0`** + doesn't set `last_failure_at`. A feed stuck returning SKIPPED reads as **healthy** on `source_registry`/`v_feed_status` — *healthier than a failing feed*. | `ingester_base.py:118,145`; `shared/storage/job_log.py:127,130,133-135`; `migrations/110_v_feed_status_dq.sql:35-45` |
| D4 | Even when the freshness check eventually notices a sustained SKIPPED, **WARN-severity feeds never page** (only ERROR gaps `exit(1)`). | `feed_health_check/__main__.py:42-54,249` |
| D5 | **No source-schema contract.** An in-format column rename (NSE already did this: `ClsPric`→`ClsgPric`) makes the field `None` → rows silently dropped in `validate()` → fewer/zero rows → SKIPPED. Avro validates only the **nullable output** shape and only under Kafka (LocalLogBus skips it). | `bhavcopy/parser.py:150`, `bhavcopy/service.py:103-105`; `shared/bus.py:74-100,181-193`; `contracts/bhavcopy_v1.avsc` |
| D6 | **Content-type is guessed from the URL extension and never checked against the bytes** — a `.csv` URL returning gzip/HTML is archived as `text/csv` with no mismatch signal. | `ingester_base.py:347-355` |

### Theme E — Configuration drift / fragmentation
| # | Root cause | Evidence |
|---|---|---|
| E1 | **4+ hand-maintained feed lists disagree**: VM cron (28 svcs), admin `NIDP_INGESTERS`, `feed_health_check.EXPECTED_FEEDS`, `health_check.sh` SLO table, `source_registry` seed. Engines like `technical_indicator_engine`, `fundamental_engine`, `bank_scoring` run in cron but aren't in the admin registry → gaps in monitoring/triggering. | `nidp.cron`; `routes/admin_nidp.py:53-100`; `feed_health_check/__main__.py:35-61`; `health_check.sh:25-56` |
| E2 | **Two schedulers** (VM cron + legacy GCP Cloud Scheduler) that must be edited in both; the `schedule_cron` DB column is **inert** (display/monitoring only, nothing dispatches from it). | `nidp.cron:1-10`; `deploy/gcp/setup_schedules.sh`; `migrations/022:35` vs its only readers (feeds API, views) |
| E3 | **Staging cron is entirely disabled** ("ALL FEED ENTRIES DISABLED BY DEFAULT … no-run state") — staging feeds don't run at all unless manually enabled. So "staging feeds break" is partly "staging feeds were never scheduled." | `deploy/vm/nidp.staging.cron:2-16` |
| E4 | Target-date coupling bug (bhavcopy fail → downstream fetch stale date) **was real and is now fixed** (calendar is authoritative) — but residual: downstream still fetch a date for which bhavcopy landed 0 rows → completeness gap with nothing to re-run it. | `migrations/099_fix_market_session_circular.sql:1-32`; `shared/trading_day.py:58-110` |

---

## 2. Long-term fix (phased)

Design principles for "seamless": **(1)** failures are impossible to hide (loud, correctly
classified); **(2)** transient failures self-retry and multi-day gaps self-heal; **(3)** the
alarm path is *independent of the thing it monitors* and actually reaches a human; **(4)** the
disk failure is prevented and detected early.

### Phase 0 — Un-silence the alarms (days; low-risk, highest leverage)
1. **Fix `health_check.sh`**: `service` → `ingester`; and on DB-connect failure, **send the
   alert** (DB-down *is* the alert) instead of swallowing it. (P0-critical: this is the dead
   alarm.)
2. **Stand up an alert path that reaches a phone and configure at least one real channel**
   (Slack/PagerDuty/email in addition to Telegram). Unblock the empty
   `notification_channel_ids` and the blank Telegram tokens.
3. **Add a disk-space alarm** — the single highest-value fix. Emit `disk_free_pct` for
   `nidp-stack-vm` and alert at <15 %/<10 %. Simplest first cut: add `df` to the per-minute
   collectors *and* push to the external channel.
4. **Make DB-down HTTP-visible**: return non-200 (or add a strict `/readyz`) when
   `db_ok:false`, and make `service_health_collector` inspect the body, not just the status.
5. **Schedule exactly one freshness detector** (`feed_health_check.py`, the richer one) and
   route its output to the external channel; retire or fix `health_check.sh` so there's one.

> ⚠️ The alarm must run **off** `nidp-stack-vm` (or via GCP Cloud Monitoring), or it inherits
> the same circular-blindness. This is the core of Phase 3 #2 but the external heartbeat
> should land in Phase 0.

### Phase 1 — Automatic recovery (1–2 weeks)
1. **Bounded retry of the *retryable* failure class.** Retry transient (HTTP/network) run
   failures N× with backoff — either in `run_service.sh` or as a run-level policy — but
   **never** retry parse/validate failures (they won't fix themselves). Key off `error_class`.
2. **Self-healing catch-up job** (the big one for disk outages): a scheduled reconciler that
   diffs *expected trading days* (calendar) vs `job_log` OK rows per feed for the last K days
   and auto-invokes the **idempotent** backfill for the gaps. Safe to run daily because
   `backfill.py` already skips already-succeeded `(ingester, date)` pairs.
3. **DLQ redrive job**: scheduled reader of `dq.dlq_findings WHERE replay_status='PENDING'`
   that re-runs the feed for that `(feed, date)` and flips `REPLAYED`/`DROPPED`. Closes the
   write-only loop.

### Phase 2 — Make failures un-hideable (classification)
1. **Shared fetch-layer content guard**: after a 200, sniff for HTML/"Access Denied"/CAPTCHA/
   empty and raise a typed `UnsupportedContentError` → FAILED with `error_class='CONTENT'`.
   One place, every feed → directly kills the "feeds failed due to unsupported content"
   silent class.
2. **Split `SKIPPED` semantics**: real holiday/no-work vs *unexpected* empty/suspect. Use the
   trading calendar — 0 rows on a *trading day* is SUSPECT (counts toward staleness/paging,
   does **not** reset `consecutive_failures`); 0 rows on a holiday is fine.
3. **Source-schema contract per feed**: declared expected header/columns checked at parse
   entry → drift = FAILED (or promote the existing DQ drift findings, e.g.
   `ROW_HAS_SOME_FACTS`, header-mismatch, to BLOCK for that feed) instead of silent null-drop.
4. **Content-type/magic-byte assertion** at archive time.

### Phase 3 — Structural durability
1. **Grow the PD** (49 G is genuinely ~30 G live) to 80–100 G and **recreate long-lived
   containers** so the log cap applies; keep raw archives on MinIO/GCS with retention.
2. **Move the alert plane off the data-plane VM** (GCP Cloud Monitoring, or a cheap separate
   heartbeat host) so it stays up when the VM's Postgres is down. Resolves the circular root
   cause (B1/B5).
3. **One feed registry = one source of truth.** Generate cron + admin list + health-check +
   `source_registry` from a single manifest (or make `schedule_cron` authoritative with a
   small dispatcher). Kill the drift (E1).
4. **Pick one scheduler** — finish decommissioning Cloud Scheduler or fully move to it; stop
   maintaining both (E2).
5. **Enable staging feeds** (or explicitly document staging as on-demand and make that the
   contract) so staging reflects prod behavior (E3).

---

## 3. How each fix gets verified (app + data)

Per the repo's verify-before-complete gate, each change ships with a test that exercises the
real behavior:

- **Dead-alarm fix:** run `health_check.sh` against staging DB → show it evaluates staleness
  and (with a test token) POSTs; inject a stale feed and confirm the alert text.
- **Disk alarm:** simulate <15 % free (or assert on a real reading) → confirm the external
  channel receives it.
- **Content guard:** feed a saved NSE "Access Denied" HTML page to the ingester → assert
  `job_log.status='FAILED'`, `error_class='CONTENT'` (not SKIPPED).
- **SKIPPED split:** run a feed for a known trading day with 0 rows → assert SUSPECT +
  `consecutive_failures` **not** reset; run for a holiday → assert benign SKIPPED.
- **Catch-up:** delete a day's OK row (staging), run the reconciler → assert the day is
  re-ingested and `job_log` shows the backfilled OK row.
- **DB-down HTTP:** stop staging PG (or point at a dead DB) → assert `/readyz` returns non-200
  and the collector marks daas-api **down**.

---

## 4. Open questions / needs from you
- Which environment first, and how does code reach the VM (the app deploys via `origin/dev`,
  but feeds run from the VM repo checkout + cron — confirm the deploy path for
  `backend/nidp/**`). See [app-staging-shares-dev-branch].
- Do you have (or can grant) `nidp-stack-vm` SSH + the GSM/terraform perms to wire notification
  channels and grow the PD? (Some Phase 0/3 items are ops changes I can't apply/verify without
  it — noted in [prod-daas-disk-full-failure-mode].)
- Preferred alert channel(s): Telegram (already coded), Slack, PagerDuty, email?

## 5. Also noticed (out of scope, flagging honestly)
- **Secret in source:** a hardcoded static admin key `niv3sh-reset-2026` gates
  `POST /api/admin/nidp/run-job` (`backend/routes/admin_nidp.py:1052,1071`). Not part of the
  feed work, but it's a real credential in the repo — worth rotating to a secret + env var.
