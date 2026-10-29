"""Data Quality Score — weighted formula, confidence score, certification, publish gate.

Formula (from NIDP Data Quality Rules Summary):
  Q = 0.40·A + 0.30·C + 0.15·P + 0.10·F + 0.05·U
  K = 0.40·S + 0.30·V + 0.20·F + 0.10·G

  A  accuracy       — closeness to golden source (AMFI, NSE, BSE, SEBI, AMC fact sheets)
  C  consistency    — same value across API / dashboard / exports / DB within tolerance
  P  completeness   — filled required fields / total required fields × 100
  F  freshness      — max(0, 1 − age / allowed_staleness) × 100
  U  auditability   — fields with full lineage / total fields × 100
  S  source_reliability   — weight of sources that passed their own validation
  V  validation_pass_rate — pct of ingester rules that passed for this date
  G  cross_source_agreement — pct of cross-source checks that agreed

Certification:
  ≥ 99.5  → PLATINUM
  98–99.49→ GOLD
  95–97.99→ SILVER
  < 95    → REVIEW

Publish gate:
  BLOCK finding present → REJECT
  Q < 95              → REJECT
  Q ∈ [95, 98)        → HOLD
  K < 90              → MANUAL_REVIEW
  Q ≥ 98 and K ≥ 90  → AUTO_PUBLISH
"""
from __future__ import annotations

import datetime as _dt
from dataclasses import dataclass, field
from datetime import date
from typing import Optional

import asyncpg

# ── Which ingesters belong to a domain ───────────────────────────────────────
# The score and the gate used `ingester LIKE '<domain>%'`, but no ingester is named that way ('bhavcopy', 'amfi_nav',
# …), so accuracy was always 100 and equity BLOCK findings never reached the gate. These are the ingester names as
# they are written to nidp.validation_runs. Feeds that run all evening (corporate_announcements_*) are left out on
# purpose: they are not the day's market data and their late runs made freshness look stale.
#
# SCOPE (owner, 29 Oct 2026: fix data quality for the data the trading product needs, "not for all the feeds"): the
# corrected scoring applies only to the domains listed here. Any other domain (mf, all) keeps the earlier scoring
# exactly (`_legacy` paths below), so this change cannot move a mutual-fund certification.
DOMAIN_INGESTERS: dict[str, tuple[str, ...]] = {
    "equity": ("bhavcopy", "delivery", "index_close", "corporate_actions", "nse_equity_master",
               "nse_shareholding", "bulk_deals", "block_deals"),
}


def is_scored_domain(domain: str) -> bool:
    """True for a domain the corrected scoring covers; False keeps the earlier behaviour unchanged."""
    return domain in DOMAIN_INGESTERS


def domain_ingesters(domain: str) -> list[str]:
    """The ingesters of a scored domain ([] for any other)."""
    return list(DOMAIN_INGESTERS.get(domain, ()))


# ── When each feed's data for day D is due (IST) ─────────────────────────────
# (days after D, hour, minute). A feed is on time when its FIRST successful validation run for D started by then; a
# later re-run or backfill does not make an on-time day late. Delivery for D is published the next morning.
INGESTER_SLA_IST: dict[str, tuple[int, int, int]] = {
    "bhavcopy": (0, 20, 0),
    "index_close": (0, 20, 0),
    "bulk_deals": (0, 20, 30),
    "block_deals": (0, 20, 30),
    "corporate_actions": (0, 21, 0),
    "nse_shareholding": (0, 22, 0),
    "nse_equity_master": (0, 22, 0),
    "delivery": (1, 11, 30),
    "amfi_nav": (0, 21, 0),
    "mf_holdings": (0, 22, 0),
    "mf_disclosure_snapshot": (0, 22, 0),
}
DEFAULT_SLA_IST = (0, 22, 0)
ALLOWED_LATENESS_HOURS = 6.0
_IST = _dt.timezone(_dt.timedelta(hours=5, minutes=30))


def sla_deadline(ingester: str, target_date: date) -> _dt.datetime:
    days, hour, minute = INGESTER_SLA_IST.get(ingester, DEFAULT_SLA_IST)
    return _dt.datetime.combine(target_date + _dt.timedelta(days=days), _dt.time(hour, minute), tzinfo=_IST)


def freshness_from_first_runs(first_runs: dict[str, _dt.datetime], target_date: date) -> float:
    """100 when every feed that reported for the day first arrived by its deadline, decaying to 0 over
    ALLOWED_LATENESS_HOURS for the LATEST feed. No feed at all → 0 (nothing arrived)."""
    if not first_runs:
        return 0.0
    worst = 100.0
    for ingester, started_at in first_runs.items():
        at = started_at if started_at.tzinfo else started_at.replace(tzinfo=_dt.timezone.utc)
        late_h = (at - sla_deadline(ingester, target_date)).total_seconds() / 3600.0
        worst = min(worst, max(0.0, 1.0 - max(0.0, late_h) / ALLOWED_LATENESS_HOURS) * 100.0)
    return worst


# ── Consistency, weighted by how serious each failed rule is ─────────────────
# Each rule that fired costs its worst finding's weight, out of the number of rules run. Before, every fired rule cost
# a full point whatever its severity, so one WARN price flag on one symbol cost as much as a CRITICAL integrity break.
SEVERITY_WEIGHT: dict[str, float] = {"CRITICAL": 1.0, "ERROR": 0.5, "WARN": 0.1, "INFO": 0.0}
_SEVERITY_RANK = {"INFO": 0, "WARN": 1, "ERROR": 2, "CRITICAL": 3}


@dataclass
class ConsistencyInput:
    """One consistency run, as the score needs it: rules run, the worst severity per rule that fired, and how many
    rules crashed (counted as failed, never as passed)."""
    rules_run: int
    fired: dict[str, str] = field(default_factory=dict)   # rule_name -> worst severity
    crashed: int = 0

    @classmethod
    def from_findings(cls, rules_run: int, findings, crashed: int = 0) -> "ConsistencyInput":
        fired: dict[str, str] = {}
        for f in findings:
            sev = f.severity.value if hasattr(f.severity, "value") else str(f.severity)
            worst = fired.get(f.rule_name)
            if worst is None or _SEVERITY_RANK.get(sev, 3) > _SEVERITY_RANK.get(worst, 3):
                fired[f.rule_name] = sev
        return cls(rules_run=rules_run, fired=fired, crashed=crashed)


def consistency_score(inp: ConsistencyInput) -> float:
    if inp.rules_run <= 0:
        return 95.0
    penalty = sum(SEVERITY_WEIGHT.get(sev, 1.0) for sev in inp.fired.values()) + 1.0 * max(0, inp.crashed)
    return max(0.0, 100.0 * (1.0 - penalty / inp.rules_run))


@dataclass
class QualityScore:
    target_date:   date
    domain:        str
    # Five weighted dimensions (0–100 each)
    accuracy:      float
    consistency:   float
    completeness:  float
    freshness:     float
    auditability:  float
    # Confidence sub-components (optional — populated when enough data exists)
    source_reliability:     Optional[float] = None
    validation_pass_rate:   Optional[float] = None
    cross_source_agreement: Optional[float] = None
    # Metadata
    notes: Optional[str] = None

    @property
    def overall(self) -> float:
        return round(
            0.40 * self.accuracy
            + 0.30 * self.consistency
            + 0.15 * self.completeness
            + 0.10 * self.freshness
            + 0.05 * self.auditability,
            3,
        )

    @property
    def confidence(self) -> Optional[float]:
        if any(v is None for v in [self.source_reliability, self.validation_pass_rate, self.cross_source_agreement]):
            return None
        return round(
            0.40 * self.source_reliability       # type: ignore[operator]
            + 0.30 * self.validation_pass_rate   # type: ignore[operator]
            + 0.20 * self.freshness
            + 0.10 * self.cross_source_agreement,# type: ignore[operator]
            3,
        )

    @property
    def certification(self) -> str:
        q = self.overall
        if q >= 99.5:
            return "PLATINUM"
        if q >= 98.0:
            return "GOLD"
        if q >= 95.0:
            return "SILVER"
        return "REVIEW"

    @property
    def publish_decision(self) -> str:
        q = self.overall
        k = self.confidence
        if q < 95.0:
            return "REJECT"
        if k is not None and k < 90.0:
            return "MANUAL_REVIEW"
        if q < 98.0:
            return "HOLD"
        return "AUTO_PUBLISH"

    def as_dict(self) -> dict:
        return {
            "target_date":             self.target_date.isoformat(),
            "domain":                  self.domain,
            "accuracy":                self.accuracy,
            "consistency":             self.consistency,
            "completeness":            self.completeness,
            "freshness":               self.freshness,
            "auditability":            self.auditability,
            "overall_score":           self.overall,
            "confidence_score":        self.confidence,
            "source_reliability":      self.source_reliability,
            "validation_pass_rate":    self.validation_pass_rate,
            "cross_source_agreement":  self.cross_source_agreement,
            "certification":           self.certification,
            "publish_decision":        self.publish_decision,
            "notes":                   self.notes,
        }


async def compute_quality_score(
    conn: asyncpg.Connection,
    target_date: date,
    domain: str,
    *,
    replay_mode: bool = False,
    consistency_input: Optional[ConsistencyInput] = None,
) -> QualityScore:
    """Derive all five quality dimensions from data already in the warehouse.

    Strategy per dimension:
      Accuracy     — pct of validation rules tagged accuracy that PASSED
      Consistency  — pct of consistency_findings that did NOT fire for this date+domain
      Completeness — pct of non-null values across known required fields
      Freshness    — whether data arrived within SLA (latest ingested_at vs EOD cutoff)
      Auditability — pct of persisted rows that carry source_run_id + ingested_at

    `replay_mode=True` switches the freshness check to counterfactual
    semantics: "did data ever arrive for this date?" — yes → 100, no → 0.
    This is the right backtest question because the wall-clock-vs-SLA
    arithmetic always penalises backfilled historical dates (their
    ingestion timestamp is "today", not the historical date).

    `consistency_input` (a dry run) scores consistency from findings computed in memory instead of the latest stored
    consistency run; everything else is still read from the warehouse, and nothing is written either way.
    """
    scored = is_scored_domain(domain)
    ingesters = domain_ingesters(domain)

    # ── Accuracy: validation rules pass rate (proxy for closeness to golden source)
    if scored:
        acc_row = await conn.fetchrow("""
            SELECT
                count(*) FILTER (WHERE status = 'PASSED') AS passed,
                count(*)                                   AS total
            FROM nidp.v_latest_validation
            WHERE target_date = $1
              AND ingester = ANY($2::text[])
        """, target_date, ingesters)
    else:   # earlier behaviour, kept for domains outside the corrected scope
        acc_row = await conn.fetchrow("""
            SELECT
                count(*) FILTER (WHERE status = 'PASSED') AS passed,
                count(*)                                   AS total
            FROM nidp.v_latest_validation
            WHERE target_date = $1
              AND ($2 = 'all'
                   OR ingester LIKE $3)
        """, target_date, domain, f"{domain}%")
    total_rules = int(acc_row["total"] or 0)
    passed_rules = int(acc_row["passed"] or 0)
    accuracy = (100.0 * passed_rules / total_rules) if total_rules > 0 else 100.0
    validation_pass_rate = accuracy

    # ── Consistency: rules that fired, each weighted by its worst severity
    if consistency_input is None:
        cons_row = await conn.fetchrow("""
            SELECT run_id, rules_run, rules_failed
            FROM nidp.consistency_runs
            WHERE target_date = $1
              AND domain      = $2
            ORDER BY started_at DESC
            LIMIT 1
        """, target_date, domain)
        if cons_row and (cons_row["rules_run"] or 0) > 0:
            sev_rows = await conn.fetch("""
                SELECT rule_name, severity FROM nidp.consistency_findings WHERE run_id = $1
            """, cons_row["run_id"])
            fired: dict[str, str] = {}
            for r in sev_rows:
                worst = fired.get(r["rule_name"])
                if worst is None or _SEVERITY_RANK.get(r["severity"], 3) > _SEVERITY_RANK.get(worst, 3):
                    fired[r["rule_name"]] = r["severity"]
            # A rule counted as failed with no finding row crashed: it costs a full point (unknown is not a pass).
            crashed = max(0, int(cons_row["rules_failed"] or 0) - len(fired))
            consistency_input = ConsistencyInput(rules_run=int(cons_row["rules_run"]), fired=fired, crashed=crashed)

    if consistency_input is not None and consistency_input.rules_run > 0:
        if scored:
            consistency = consistency_score(consistency_input)
        else:   # earlier behaviour: every rule that fired or crashed costs a full point
            failed = len(consistency_input.fired) + max(0, consistency_input.crashed)
            consistency = 100.0 * (consistency_input.rules_run - failed) / consistency_input.rules_run
        cross_source_agreement = consistency
    else:
        # No consistency run yet — be conservative but not zero
        consistency = 95.0
        cross_source_agreement = None

    # ── Completeness: sample critical MF + equity required fields
    if domain in ("mf", "all"):
        mf_comp = await conn.fetchrow("""
            SELECT
                count(*)                                           AS total,
                count(*) FILTER (WHERE nav IS NOT NULL
                                   AND scheme_code IS NOT NULL)    AS filled
            FROM nidp.mf_nav_daily
            WHERE nav_date = $1
        """, target_date)
        mf_total  = int(mf_comp["total"]  or 0)
        mf_filled = int(mf_comp["filled"] or 0)
    else:
        mf_total = mf_filled = 0

    if domain in ("equity", "all"):
        eq_comp = await conn.fetchrow("""
            SELECT
                count(*)                                          AS total,
                count(*) FILTER (WHERE close_price IS NOT NULL
                                   AND symbol IS NOT NULL
                                   AND open_price  IS NOT NULL)   AS filled
            FROM nidp.prices_eod
            WHERE as_of_date = $1
              AND series IN ('EQ','BE','BZ','SM')
        """, target_date)
        eq_total  = int(eq_comp["total"]  or 0)
        eq_filled = int(eq_comp["filled"] or 0)
    else:
        eq_total = eq_filled = 0

    grand_total  = mf_total  + eq_total
    grand_filled = mf_filled + eq_filled
    completeness = (100.0 * grand_filled / grand_total) if grand_total > 0 else 100.0

    # ── Freshness: did each of the domain's feeds FIRST arrive by its own deadline (INGESTER_SLA_IST)?
    # Before, the newest run of ANY ingester for the date was compared with 22:00 IST, so an evening announcements
    # poll or a next-day backfill made an on-time day look late, and next-morning delivery could never be on time.
    if scored:
        fresh_rows = await conn.fetch("""
            SELECT ingester, min(started_at) AS first_ok
            FROM nidp.validation_runs
            WHERE target_date = $1
              AND status IN ('PASSED','PARTIAL')
              AND ingester = ANY($2::text[])
            GROUP BY ingester
        """, target_date, ingesters)
        first_runs = {r["ingester"]: r["first_ok"] for r in fresh_rows if r["first_ok"] is not None}
        if not first_runs:
            freshness = 0.0
        elif replay_mode:
            # Counterfactual: data exists for this historical date → treat as fresh.
            # The original ingestion timestamps don't reflect "real-time arrival"
            # for backfilled rows, so wall-clock SLA math is meaningless here.
            freshness = 100.0
        else:
            freshness = freshness_from_first_runs(first_runs, target_date)
    else:   # earlier behaviour: newest run of any ingester for the date vs 22:00 IST
        fresh_row = await conn.fetchrow("""
            SELECT max(started_at) AS latest
            FROM nidp.validation_runs
            WHERE target_date = $1
              AND status IN ('PASSED','PARTIAL')
        """, target_date)
        latest_at = fresh_row["latest"] if fresh_row else None
        if latest_at is None:
            freshness = 0.0
        elif replay_mode:
            freshness = 100.0
        else:
            sla_cutoff = _dt.datetime.combine(target_date, _dt.time(16, 30), tzinfo=_dt.timezone.utc)
            age_hours = (latest_at.replace(tzinfo=_dt.timezone.utc) - sla_cutoff).total_seconds() / 3600
            freshness = max(0.0, 1.0 - max(0.0, age_hours) / 6.0) * 100.0

    # ── Auditability: pct of rows with source_run_id set (proxy for lineage)
    aud_mf = await conn.fetchrow("""
        SELECT count(*) AS total,
               count(*) FILTER (WHERE source_run_id IS NOT NULL) AS with_lineage
        FROM nidp.mf_nav_daily WHERE nav_date = $1
    """, target_date) if domain in ("mf", "all") else None

    aud_eq = await conn.fetchrow("""
        SELECT count(*) AS total,
               count(*) FILTER (WHERE source_run_id IS NOT NULL) AS with_lineage
        FROM nidp.prices_eod WHERE as_of_date = $1 AND series IN ('EQ','BE','BZ','SM')
    """, target_date) if domain in ("equity", "all") else None

    aud_total   = (int((aud_mf["total"]        if aud_mf else 0) or 0)
                 + int((aud_eq["total"]        if aud_eq else 0) or 0))
    aud_lineage = (int((aud_mf["with_lineage"] if aud_mf else 0) or 0)
                 + int((aud_eq["with_lineage"] if aud_eq else 0) or 0))
    auditability = (100.0 * aud_lineage / aud_total) if aud_total > 0 else 100.0

    # ── Source reliability: pass rate of critical BLOCK-class rules
    src_row = await conn.fetchrow("""
        SELECT
            count(*) FILTER (WHERE failure_class = 'BLOCK') AS block_findings,
            count(*) FILTER (WHERE status = 'PASSED')       AS passed_runs,
            count(*)                                         AS total_runs
        FROM nidp.validation_runs vr
        LEFT JOIN nidp.validation_findings vf
               ON vf.job_run_id = vr.job_run_id
        WHERE vr.target_date = $1
    """, target_date)
    block_findings = int(src_row["block_findings"] or 0)
    total_runs_src = int(src_row["total_runs"]     or 0)
    passed_runs    = int(src_row["passed_runs"]    or 0)
    if total_runs_src > 0:
        source_reliability = 100.0 * passed_runs / total_runs_src
        if block_findings > 0:
            source_reliability = min(source_reliability, 80.0)
    else:
        source_reliability = None

    notes_parts: list[str] = []
    if total_rules == 0:
        notes_parts.append("no validation runs found")
    if grand_total == 0:
        notes_parts.append("no rows found for completeness check")

    return QualityScore(
        target_date=target_date,
        domain=domain,
        accuracy=round(min(accuracy, 100.0), 3),
        consistency=round(min(consistency, 100.0), 3),
        completeness=round(min(completeness, 100.0), 3),
        freshness=round(min(freshness, 100.0), 3),
        auditability=round(min(auditability, 100.0), 3),
        source_reliability=round(source_reliability, 3) if source_reliability is not None else None,
        validation_pass_rate=round(validation_pass_rate, 3),
        cross_source_agreement=round(cross_source_agreement, 3) if cross_source_agreement is not None else None,
        notes="; ".join(notes_parts) or None,
    )


async def persist_quality_score(
    conn: asyncpg.Connection,
    qs: QualityScore,
) -> None:
    """Upsert the quality score into nidp.quality_scores."""
    await conn.execute(
        """
        INSERT INTO nidp.quality_scores
            (target_date, domain,
             accuracy, consistency, completeness, freshness, auditability,
             overall_score,
             source_reliability, validation_pass_rate, cross_source_agreement,
             confidence_score,
             certification, publish_decision, notes)
        VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12, $13, $14, $15)
        """,
        qs.target_date, qs.domain,
        qs.accuracy, qs.consistency, qs.completeness, qs.freshness, qs.auditability,
        qs.overall,
        qs.source_reliability, qs.validation_pass_rate, qs.cross_source_agreement,
        qs.confidence,
        qs.certification, qs.publish_decision, qs.notes,
    )
