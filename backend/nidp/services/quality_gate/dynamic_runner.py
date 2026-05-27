"""Dynamic Expectations Runner — evaluates active rules from
`dq.expectations_active` against the warehouse.

Complements `great_expectations_runner.py` (which runs Python-side
hardcoded suites) by executing AI-promoted SQL boolean expressions
directly against the DB. Findings are persisted to
`nidp.validation_findings` with the rule's severity, so they flow
into the same quality-score / certification pipeline.

Wiring:
  - Called from `quality_gate/__main__.py` after the GE runner.
  - Idempotent — safe to run multiple times for the same target_date.

Each active rule is one row in dq.expectations_active:
    {dataset_name, name, expression, severity, active=TRUE, ...}

Where `expression` is a SQL boolean fragment like:
    high_price >= low_price
    close_price BETWEEN low_price AND high_price

The runner converts that into:
    SELECT count(*) FILTER (WHERE NOT (<expression>)) AS bad,
           count(*)                                    AS total
      FROM <table_for_dataset>
     WHERE <date_column> = <target_date>::date

Anything that fails to compile (unknown columns, syntax errors) is
caught and recorded with severity=WARN so a single bad rule never
bricks the daily run.
"""
from __future__ import annotations

import json
import logging
import os
import uuid
from dataclasses import dataclass
from datetime import date
from typing import Any, Dict, List, Optional, Tuple

import asyncpg

logger = logging.getLogger(__name__)


PG_DSN = (
    os.environ.get("NIDP_PG_DSN")
    or os.environ.get("NIDP_POSTGRES_URL")
    or os.environ.get("POSTGRES_URL")
    or "postgresql://postgres:postgres@localhost:5433/nidp"
)


# Map dataset_name (as stored in dq.expectations_active) → (table, date_column).
# When a dataset isn't here, the runner falls back to information_schema
# discovery (table_name = dataset_name and prefer `as_of_date`/`target_date`/
# `nav_date`/`observation_date` if present).
_DATASET_MAP: Dict[str, Tuple[str, str]] = {
    "amfi_nav":                   ("nidp.amfi_nav",            "as_of_date"),
    "fii_dii":                    ("nidp.fii_dii_flows",       "as_of_date"),
    "fii_dii_flows":              ("nidp.fii_dii_flows",       "as_of_date"),
    "bhavcopy":                   ("nidp.prices_eod",          "as_of_date"),
    "prices_eod":                 ("nidp.prices_eod",          "as_of_date"),
    "prices_eod_adjusted":        ("nidp.prices_eod_adjusted", "as_of_date"),
    "delivery":                   ("nidp.delivery_data",       "as_of_date"),
    "delivery_data":              ("nidp.delivery_data",       "as_of_date"),
    "index_close":                ("nidp.index_eod",           "as_of_date"),
    "index_eod":                  ("nidp.index_eod",           "as_of_date"),
    "fno_bhavcopy":               ("nidp.fno_bhavcopy",        "as_of_date"),
    "bulk_deals":                 ("nidp.bulk_deals",          "as_of_date"),
    "block_deals":                ("nidp.block_deals",         "as_of_date"),
    "rbi_yields":                 ("nidp.rbi_yields",          "as_of_date"),
    "fred_macro":                 ("nidp.fred_macro",          "observation_date"),
    "mf_nav_daily":               ("nidp.mf_nav_daily",        "nav_date"),
    "amfi_nav_history":           ("nidp.mf_nav_daily",        "nav_date"),
    "mf_holdings":                ("nidp.mf_holdings",         "snapshot_date"),
    "mf_disclosure_snapshot":     ("nidp.mf_scheme_disclosure_snapshot", "snapshot_date"),
}

_DATE_COL_CANDIDATES = (
    "as_of_date", "target_date", "nav_date", "observation_date",
    "snapshot_date", "ex_date", "trade_date", "holiday_date",
)


@dataclass
class DynamicRuleResult:
    rule_id:        str
    dataset_name:   str
    name:           str
    severity:       str
    expression:     str
    success:        bool
    total_rows:     int
    failed_rows:    int
    failed_pct:     float
    error:          Optional[str] = None

    def as_dict(self) -> dict:
        return {
            "rule_id":      self.rule_id,
            "dataset_name": self.dataset_name,
            "name":         self.name,
            "severity":     self.severity,
            "success":      self.success,
            "total_rows":   self.total_rows,
            "failed_rows":  self.failed_rows,
            "failed_pct":   round(self.failed_pct, 3),
            "error":        self.error,
        }


async def _resolve_table(
    conn: asyncpg.Connection, dataset_name: str,
) -> Optional[Tuple[str, Optional[str]]]:
    """Return (qualified_table, date_column) for a dataset_name."""
    if dataset_name in _DATASET_MAP:
        return _DATASET_MAP[dataset_name]

    # Fallback: look in nidp schema for an exact table-name match and
    # pick a sensible date column.
    try:
        row = await conn.fetchrow(
            """
            SELECT table_schema, table_name
              FROM information_schema.tables
             WHERE table_name = $1
               AND table_schema IN ('nidp','dq','public','features','analytics','events','graph','ref')
             ORDER BY CASE table_schema
                        WHEN 'nidp' THEN 1
                        WHEN 'dq'   THEN 2
                        ELSE 3
                      END
             LIMIT 1
            """,
            dataset_name,
        )
        if not row:
            return None
        qualified = f"{row['table_schema']}.{row['table_name']}"

        cols = await conn.fetch(
            """
            SELECT column_name
              FROM information_schema.columns
             WHERE table_schema = $1 AND table_name = $2
            """,
            row["table_schema"], row["table_name"],
        )
        col_names = {c["column_name"] for c in cols}
        date_col = next((c for c in _DATE_COL_CANDIDATES if c in col_names), None)
        return qualified, date_col
    except Exception as e:                                                # noqa: BLE001
        logger.warning("dynamic_rules: schema lookup failed for %s: %s", dataset_name, e)
        return None


async def _evaluate_rule(
    conn: asyncpg.Connection,
    rule: Dict[str, Any],
    target_date: Optional[date],
) -> DynamicRuleResult:
    """Run one expression against the target table+date."""
    dataset = rule["dataset_name"]
    name    = rule["name"]
    expr    = rule["expression"]
    rid     = str(rule["rule_id"])

    resolved = await _resolve_table(conn, dataset)
    if resolved is None:
        return DynamicRuleResult(
            rule_id=rid, dataset_name=dataset, name=name,
            severity=rule.get("severity", "WARN"), expression=expr,
            success=False, total_rows=0, failed_rows=0, failed_pct=0.0,
            error=f"dataset '{dataset}' not found in information_schema",
        )
    table, date_col = resolved

    where, params = "", []
    if target_date and date_col:
        where = f" WHERE {date_col} = $1::date"
        params = [target_date]

    sql = f"""
        SELECT count(*) FILTER (WHERE NOT ({expr})) AS bad,
               count(*) AS total
          FROM {table}
         {where}
    """
    try:
        row = await conn.fetchrow(sql, *params)
    except Exception as e:                                                # noqa: BLE001
        return DynamicRuleResult(
            rule_id=rid, dataset_name=dataset, name=name,
            severity=rule.get("severity", "WARN"), expression=expr,
            success=False, total_rows=0, failed_rows=0, failed_pct=0.0,
            error=f"{type(e).__name__}: {str(e)[:200]}",
        )

    total = int(row["total"] or 0)
    bad   = int(row["bad"]   or 0)
    pct   = (100.0 * bad / total) if total > 0 else 0.0
    return DynamicRuleResult(
        rule_id=rid, dataset_name=dataset, name=name,
        severity=rule["severity"], expression=expr,
        success=(bad == 0 and total > 0),
        total_rows=total, failed_rows=bad, failed_pct=pct,
    )


async def _persist_finding(
    conn: asyncpg.Connection,
    run_id: uuid.UUID,
    target_date: Optional[date],
    result: DynamicRuleResult,
) -> None:
    """Write one failing dynamic-rule result into nidp.validation_findings.
    Successful rules are not persisted (parity with GE runner)."""
    if result.success or result.error is None and result.failed_rows == 0:
        return

    # Severity escalation: a CRITICAL rule with > 5% failure rate stays
    # CRITICAL; otherwise we honour the rule's stored severity.
    sev = result.severity
    if sev not in ("INFO", "WARN", "ERROR", "CRITICAL"):
        sev = "WARN"

    payload = {
        "rule_id":     result.rule_id,
        "expression":  result.expression,
        "failed_rows": result.failed_rows,
        "total_rows":  result.total_rows,
        "failed_pct":  round(result.failed_pct, 3),
        "source":      "dq.expectations_active",
    }
    if result.error:
        payload["error"] = result.error

    try:
        # Map severity → failure_class for the gate to consume:
        #   CRITICAL → BLOCK (gate fails)
        #   ERROR    → BLOCK
        #   WARN     → FIX (visible but non-blocking)
        #   INFO     → INFO
        failure_class = {
            "CRITICAL": "BLOCK",
            "ERROR":    "BLOCK",
            "WARN":     "FIX",
            "INFO":     "INFO",
        }.get(sev, "FIX")

        await conn.execute(
            """
            INSERT INTO nidp.validation_findings
              (finding_id, validation_id, job_run_id, ingester, target_date,
               rule_name, severity, failure_class, message,
               expected, actual, sample_rows)
            VALUES (gen_random_uuid(), gen_random_uuid(), $1, $2, $3::date, $4, $5, $6, $7, $8, $9, $10::jsonb)
            """,
            run_id, result.dataset_name, target_date, result.name, sev,
            failure_class,
            (result.error or f"{result.failed_rows}/{result.total_rows} rows violate {result.name}")[:500],
            result.expression[:1000],
            str(result.failed_rows),
            json.dumps(payload, default=str),
        )
    except Exception as e:                                                # noqa: BLE001
        logger.warning(
            "dynamic_rules: could not persist finding for %s/%s: %s",
            result.dataset_name, result.name, e,
        )


async def run_active_rules(
    target_date: Optional[date] = None,
    *,
    dataset_filter: Optional[str] = None,
    persist: bool = True,
) -> Dict[str, Any]:
    """Walk every active rule in dq.expectations_active and evaluate it.

    Returns a structured report compatible with great_expectations_runner.run_all
    so it can be merged into the same quality_gate summary.
    """
    conn = await asyncpg.connect(PG_DSN)
    try:
        # Bail early if the schema isn't there yet (migration 043
        # not applied) — equivalent to "no rules registered".
        try:
            rows = await conn.fetch(
                """
                SELECT rule_id, dataset_name, name, expression,
                       severity, active, rationale, business_impact
                  FROM dq.expectations_active
                 WHERE active = TRUE
                   AND ($1::text IS NULL OR dataset_name = $1)
                 ORDER BY dataset_name, name
                """,
                dataset_filter,
            )
        except asyncpg.UndefinedTableError:
            logger.info("dynamic_rules: dq.expectations_active not present — migration 043 not applied. Skipping.")
            return {
                "target_date":        target_date.isoformat() if target_date else None,
                "rules_total":        0,
                "rules_pass":         0,
                "rules_fail":         0,
                "rules_error":        0,
                "datasets":           {},
                "skipped":            True,
                "skipped_reason":     "dq.expectations_active table not present",
            }

        rules = [dict(r) for r in rows]
        if not rules:
            return {
                "target_date": target_date.isoformat() if target_date else None,
                "rules_total": 0, "rules_pass": 0, "rules_fail": 0, "rules_error": 0,
                "datasets":    {}, "skipped": False,
            }

        run_id = uuid.uuid4()
        results: List[DynamicRuleResult] = []
        for rule in rules:
            r = await _evaluate_rule(conn, rule, target_date)
            results.append(r)
            if persist and (not r.success):
                await _persist_finding(conn, run_id, target_date, r)

        # Aggregate per-dataset
        datasets: Dict[str, Dict[str, Any]] = {}
        for r in results:
            d = datasets.setdefault(r.dataset_name, {
                "total": 0, "pass": 0, "fail": 0, "error": 0, "results": [],
            })
            d["total"] += 1
            if r.error is not None:
                d["error"] += 1
            elif r.success:
                d["pass"] += 1
            else:
                d["fail"] += 1
            d["results"].append(r.as_dict())

        n_pass = sum(1 for r in results if r.success and r.error is None)
        n_fail = sum(1 for r in results if not r.success and r.error is None)
        n_err  = sum(1 for r in results if r.error is not None)

        logger.info(
            "dynamic_rules · target_date=%s · rules=%d · pass=%d · fail=%d · error=%d (datasets=%d)",
            target_date, len(rules), n_pass, n_fail, n_err, len(datasets),
        )

        return {
            "target_date":   target_date.isoformat() if target_date else None,
            "validation_run_id": str(run_id),
            "rules_total":   len(rules),
            "rules_pass":    n_pass,
            "rules_fail":    n_fail,
            "rules_error":   n_err,
            "datasets":      datasets,
            "skipped":       False,
        }
    finally:
        await conn.close()
