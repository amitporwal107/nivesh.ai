"""Staging or production? — the gate that keeps TrueData data on STAGING only.

Owner, 3 Nov 2026 (answering the TrueData licence question): "keep on staging.. on prod please use our snapshot data".
So every job that loads TrueData data into the warehouse (truedata_history, truedata_macro, ...) asks this gate first,
in addition to the market-data switch (market_data_source.py): on production it calls nothing and writes no data.

How the environment is told apart — the repo's own split, not a new flag:
  * the database being written to: staging NIDP is `nidp_staging` (deploy/cloudpe/nidp: docker-compose.cloudpe.yml,
    bootstrap.sh; checked read-only on 3 Nov: current_database() = nidp_staging), production NIDP is `nidp`
    (deploy/cloudpe-prod: NIDP_PG_DB defaults to nidp; its README notes that tools hardcoding nidp_staging do not work
    on prod). This is the deciding signal: it is WHERE the rows would land.
  * production signals that always refuse: NIDP_HOME=/opt/nidp (prod run_service.sh and the prod cron, which
    deploy-nidp.sh generates by rewriting /opt/nidp-staging → /opt/nidp), NIDP_ENV or APP_ENV = prod / production.
NIDP_ENV=staging alone is NOT trusted to allow: prod's nidp.env was generated from staging's.

Fail closed: anything not positively staging (unknown database, NIDP_HOME set to something else, conflicting signals)
is refused. Callers record a SKIPPED run (error_class NOT_STAGING) and touch nothing else. Rollbacks do not ask: they
are the way back.
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import Mapping, Optional, Tuple

STAGING = "staging"
PRODUCTION = "production"
UNKNOWN = "unknown"

STAGING_DATABASES = frozenset({"nidp_staging"})
PRODUCTION_DATABASES = frozenset({"nidp"})
STAGING_HOMES = frozenset({"/opt/nidp-staging"})
PRODUCTION_HOMES = frozenset({"/opt/nidp"})
_PRODUCTION_NAMES = frozenset({"prod", "production"})

NOT_STAGING = "NOT_STAGING"            # job_log error_class of a refused run


@dataclass(frozen=True)
class EnvVerdict:
    environment: str                   # staging | production | unknown
    allowed: bool                      # may this process load TrueData data?
    reason: str
    signals: Tuple[Tuple[str, Optional[str]], ...] = field(default_factory=tuple)

    def as_dict(self) -> dict:
        return {"environment": self.environment, "allowed": self.allowed, "reason": self.reason,
                "signals": dict(self.signals)}


def classify(database: Optional[str], env: Optional[Mapping[str, str]] = None) -> EnvVerdict:
    """The environment from the database name and the process environment (see the module docstring)."""
    env = os.environ if env is None else env
    db = (database or "").strip()
    home = (env.get("NIDP_HOME") or "").strip().rstrip("/")
    names = {k: (env.get(k) or "").strip().lower() for k in ("NIDP_ENV", "APP_ENV")}
    signals = (("database", db or None), ("NIDP_HOME", home or None),
               ("NIDP_ENV", names["NIDP_ENV"] or None), ("APP_ENV", names["APP_ENV"] or None))

    prod = []
    if db in PRODUCTION_DATABASES:
        prod.append(f"database {db}")
    if home in PRODUCTION_HOMES:
        prod.append(f"NIDP_HOME={home}")
    prod += [f"{k}={v}" for k, v in names.items() if v in _PRODUCTION_NAMES]
    if prod:
        return EnvVerdict(PRODUCTION, False, "production (" + ", ".join(prod) + "): TrueData data is loaded on "
                          "staging only; production keeps our own snapshot data (owner, 3 Nov 2026)", signals)
    if db in STAGING_DATABASES and (not home or home in STAGING_HOMES):
        return EnvVerdict(STAGING, True, f"staging (database {db}"
                          + (f", NIDP_HOME={home}" if home else "") + ")", signals)
    return EnvVerdict(UNKNOWN, False, f"unknown environment (database {db or 'unknown'!s}, NIDP_HOME "
                      f"{home or 'unset'}): refused, fail closed; TrueData data is loaded on staging only", signals)


async def truedata_load_gate(conn, env: Optional[Mapping[str, str]] = None) -> EnvVerdict:
    """Ask the database it would write to. A failing query is UNKNOWN (refused), never an exception path that loads."""
    try:
        db = await conn.fetchval("SELECT current_database()")
    except Exception as exc:                                                         # noqa: BLE001
        return EnvVerdict(UNKNOWN, False, f"could not read current_database(): {type(exc).__name__}; refused")
    return classify(db, env)
