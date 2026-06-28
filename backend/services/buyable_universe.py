"""Buyable universe — the ISIN set selection.intersect_buyable consumes.

broker-connect has NO transactable-scheme source yet (feasibility §E, confirmed),
so per workspace decision NI-1 the MVP fallback is: "every AMFI-active
direct-growth scheme is buyable." This module supplies that ISIN set.

Contract with the builder (selection.intersect_buyable): an EMPTY set means
"no filter" (passthrough) — intersect_buyable already treats None/empty as
passthrough. So returning an empty set is the SAFE degrade: when the DB is
unreachable the builder simply applies no platform filter rather than dropping
every candidate.

Honesty contract (CONTEXT.md §1): the DB path here cannot be exercised in this
env (no DB, no network), so get_buyable_isins()'s query behavior is UNVERIFIED.
Only is_direct_growth() (pure) is unit-verified. On a None pool or any error,
get_buyable_isins() returns an empty set (logged) — it never fabricates ISINs.
"""
from __future__ import annotations

import logging
from typing import Set

from services import pg_client

logger = logging.getLogger(__name__)

# Tokens in a scheme name that mark the income/dividend option (NOT growth).
# IDCW = "Income Distribution cum Capital Withdrawal" (SEBI's rename of Dividend).
_INCOME_OPTION_TOKENS = ("idcw", "dividend", "payout", "reinvest")


def is_direct_growth(scheme_name: str) -> bool:
    """Heuristic: does this scheme name imply a Direct plan AND a Growth option?

    AMFI scheme names encode plan + option in the name itself, e.g.
    "Axis Bluechip Fund - Direct Plan - Growth". We accept a scheme iff:
      1. the name contains 'direct' (Direct plan, lower expense ratio), AND
      2. the name does NOT contain an income-option token (idcw / dividend /
         payout / reinvest) — those are the IDCW/Dividend variants, not Growth.

    Note: many growth schemes do not spell out the word "growth" (the option is
    implied when no dividend/IDCW token is present), so we do NOT require the
    literal token 'growth' — requiring it would wrongly drop valid growth plans.
    Absence of an income token is the discriminator. Empty/None → False.
    """
    name = str(scheme_name or "").lower()
    if "direct" not in name:
        return False
    return not any(tok in name for tok in _INCOME_OPTION_TOKENS)


async def get_buyable_isins() -> Set[str]:
    """Return the set of ISINs the user can transact (MVP fallback, decision NI-1).

    Queries instrument_master JOIN mutual_fund_metadata for active MF instruments
    and keeps those whose scheme name is_direct_growth(). Returns a set of ISINs.

    Safe degrade: if pg_client.get_pool() is None (no DB configured) or the query
    raises, returns an EMPTY set (logged). selection.intersect_buyable treats an
    empty set as passthrough, so the builder falls back to "all candidates
    buyable" rather than dropping everything.

    UNVERIFIED: the DB query path cannot be exercised in this env (no DB/network).
    """
    pool = await pg_client.get_pool()
    if pool is None:
        logger.warning("buyable_universe: no Postgres pool — returning empty set (passthrough)")
        return set()

    try:
        async with pool.acquire() as conn:
            rows = await conn.fetch(
                """
                SELECT im.isin,
                       im.instrument_name AS scheme_name
                FROM instrument_master im
                JOIN mutual_fund_metadata mfm ON mfm.instrument_id = im.instrument_id
                WHERE im.is_active = TRUE
                  AND im.isin IS NOT NULL
                """
            )
    except Exception as e:  # noqa: BLE001
        logger.warning("buyable_universe: query failed (%s) — returning empty set (passthrough)", e)
        return set()

    isins: Set[str] = set()
    for r in rows:
        isin = r["isin"]
        if isin and is_direct_growth(r["scheme_name"]):
            isins.add(isin)
    return isins
