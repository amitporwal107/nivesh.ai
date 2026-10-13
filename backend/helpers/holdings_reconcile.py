"""Reconcile holdings that reach Nivesh from more than one source.

The same share can arrive from a CAS statement, a live broker connection and an
uploaded broker export, and all three land in `db.holdings`. Product rule
(decided 2026-10-13): **the broker wins**.

  * Rows read from a broker — a connection (`broker_account_id` set) or a
    broker's export file (`source == "broker_export"`) — survive a statement
    import. A statement import replaces everything else, as before.
  * A statement row is left out when a broker source already holds that ISIN,
    and is removed when a broker source starts holding it.
  * A new export from a broker replaces the earlier export from that broker,
    and a live connection to a broker supersedes that broker's export for the
    instruments it holds.

Matching is by ISIN only. Statement rows keep the ISIN in `ticker`; broker rows
carry it in `isin`, or it is resolved from the trading symbol through
masterdata. A row whose ISIN cannot be established is never matched, so it is
never removed on a guess — at the cost that such an instrument can still be
counted twice.

Known limit: the rule cannot tell two demat accounts apart. The same company
held at a connected broker and at a second, unconnected one shows only the
connected broker's quantity until the second is connected or uploaded.
"""
from __future__ import annotations

import logging
import re
from typing import Any, Dict, Iterable, List, Optional, Set, Tuple

logger = logging.getLogger(__name__)

BROKER_EXPORT_SOURCE = "broker_export"
# `source` labels written by statement imports (helpers.parsing.save_holdings
# and services.cas_snapshot_engine.write_holdings_table).
STATEMENT_SOURCES = ("cas", "snapshot_load")

_ISIN_RE = re.compile(r"^IN[A-Z0-9]{10}$")
_symbol_index: Optional[Dict[str, str]] = None


# ── Row classification ───────────────────────────────────────────────────
def is_broker_sourced(row: Dict[str, Any]) -> bool:
    """True for a row read from a broker connection or a broker's export."""
    return bool(row.get("broker_account_id")) or row.get("source") == BROKER_EXPORT_SOURCE


def broker_sourced_filter() -> Dict[str, Any]:
    """Mongo filter fragment matching `is_broker_sourced` rows."""
    return {"$or": [
        {"broker_account_id": {"$nin": [None, ""]}},
        {"source": BROKER_EXPORT_SOURCE},
    ]}


def not_broker_sourced_filter() -> Dict[str, Any]:
    """Mongo filter fragment for everything a statement import may replace."""
    return {
        "broker_account_id": {"$in": [None, ""]},
        "source": {"$ne": BROKER_EXPORT_SOURCE},
    }


# ── ISIN resolution ──────────────────────────────────────────────────────
def _as_isin(value: Any) -> str:
    s = str(value or "").strip().upper()
    return s if _ISIN_RE.match(s) else ""


def _clean_symbol(value: Any) -> str:
    """`NSE:INFY-EQ` → `INFY`. Series suffixes are one or two letters."""
    s = str(value or "").strip().upper().split(":")[-1]
    base, sep, suffix = s.rpartition("-")
    if sep and base and suffix.isalpha() and len(suffix) <= 2:
        return base
    return s


def _load_symbol_index() -> Dict[str, str]:
    """NSE trading symbol → ISIN, from the masterdata files. Empty when they
    are not on disk; resolution then simply finds nothing."""
    global _symbol_index
    if _symbol_index is not None:
        return _symbol_index
    index: Dict[str, str] = {}
    try:
        from services import masterdata
        # Equity master first so the listed equity wins a symbol shared with
        # another series in the bhavcopy.
        for source in (masterdata._load_equity_master(), masterdata._load_nse()):
            for isin, info in source.items():
                symbol = str(info.get("symbol") or "").strip().upper()
                if symbol:
                    index.setdefault(symbol, isin)
    except Exception:  # noqa: BLE001
        logger.exception("holdings_reconcile: masterdata symbol index unavailable")
    _symbol_index = index
    return index


def row_isin(row: Dict[str, Any]) -> str:
    """The ISIN a row states outright (`isin`, or an ISIN held in `ticker`), else ''."""
    return _as_isin(row.get("isin")) or _as_isin(row.get("ticker"))


def resolve_isin(row: Dict[str, Any]) -> str:
    """`row_isin`, falling back to the trading symbol's ISIN in masterdata."""
    isin = row_isin(row)
    if isin:
        return isin
    symbol = _clean_symbol(row.get("ticker"))
    return _load_symbol_index().get(symbol, "") if symbol else ""


def _isins(rows: Iterable[Dict[str, Any]]) -> List[str]:
    return sorted({resolve_isin(r) for r in rows} - {""})


def _isin_match(isins: List[str]) -> Dict[str, Any]:
    return {"$or": [{"isin": {"$in": isins}}, {"ticker": {"$in": isins}}]}


# ── Statement import ─────────────────────────────────────────────────────
async def broker_held_isins(db, user_id: str) -> Set[str]:
    """ISINs this user holds through any broker source."""
    cursor = db.holdings.find(
        {"user_id": user_id, **broker_sourced_filter()},
        {"_id": 0, "isin": 1, "ticker": 1},
    )
    return set(_isins(await cursor.to_list(length=5000)))


def drop_broker_held(rows: List[Dict[str, Any]], held: Set[str]) -> Tuple[List[Dict[str, Any]], int]:
    """Statement rows minus those whose ISIN a broker source already holds.
    Returns (kept rows, number left out)."""
    if not held:
        return rows, 0
    kept = [r for r in rows if resolve_isin(r) not in held]
    return kept, len(rows) - len(kept)


# ── Broker export upload ─────────────────────────────────────────────────
async def replace_broker_export(db, user_id: str, rows: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Call before storing uploaded rows. For each broker the upload is an
    export of: delete that broker's earlier export, and leave out instruments
    a live connection to the same broker already holds. Rows that are not a
    broker export pass through untouched."""
    brokers = sorted({
        r.get("broker") for r in rows
        if r.get("source") == BROKER_EXPORT_SOURCE and r.get("broker")
    })
    if not brokers:
        return rows
    live_held: Dict[str, Set[str]] = {}
    for broker in brokers:
        await db.holdings.delete_many(
            {"user_id": user_id, "source": BROKER_EXPORT_SOURCE, "broker": broker},
        )
        cursor = db.holdings.find(
            {"user_id": user_id, "broker": broker, "broker_account_id": {"$nin": [None, ""]}},
            {"_id": 0, "isin": 1, "ticker": 1},
        )
        live_held[broker] = set(_isins(await cursor.to_list(length=5000)))
    return [
        r for r in rows
        if not (
            r.get("source") == BROKER_EXPORT_SOURCE
            and resolve_isin(r) in live_held.get(r.get("broker"), set())
        )
    ]


# ── After broker rows are stored ─────────────────────────────────────────
async def apply_broker_wins(
    db, user_id: str, rows: List[Dict[str, Any]], *, broker: str, live: bool,
) -> Dict[str, int]:
    """Call after broker-sourced `rows` were stored for `broker`. Removes the
    statement copies they supersede and, for a live connection, that broker's
    export rows for the same instruments."""
    out = {"statement_rows_removed": 0, "export_rows_removed": 0}
    isins = _isins(rows)
    if not isins:
        return out
    res = await db.holdings.delete_many({
        "user_id": user_id,
        "broker_account_id": {"$in": [None, ""]},
        "source": {"$in": list(STATEMENT_SOURCES)},
        **_isin_match(isins),
    })
    out["statement_rows_removed"] = res.deleted_count
    if live:
        res = await db.holdings.delete_many({
            "user_id": user_id,
            "source": BROKER_EXPORT_SOURCE,
            "broker": broker,
            **_isin_match(isins),
        })
        out["export_rows_removed"] = res.deleted_count
    if any(out.values()):
        logger.info(
            "broker wins: removed %d statement and %d export rows superseded by %s",
            out["statement_rows_removed"], out["export_rows_removed"], broker,
            extra={"user_id": user_id},
        )
    return out
