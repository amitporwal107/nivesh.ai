"""Map Claude Vision CAS JSON → internal formats used by the rest of
the engine (holdings list + normalized `mutual_funds` shape consumed
by `services.cas_transactions.extract_transactions`).

Claude's output shape is documented in
`services.claude_cas_parser.EXTRACTION_PROMPT`. The fields we care
about here:

  holdings.equities[]            → asset_type="equity"
  holdings.preference_shares[]   → asset_type="equity" (sector="Preference Shares")
  holdings.sovereign_gold_bonds  → asset_type="gold"
  holdings.mutual_funds_demat    → asset_type="mutual_fund" (parsed_by="claude_demat")
  holdings.mutual_fund_folios    → asset_type="mutual_fund" (parsed_by="claude_folio")
  transactions.demat_transactions       (currently NOT exported — the
                                         existing engine treats demat
                                         buys/sells separately; future)
  transactions.mutual_fund_transactions → folded into the normalised
                                         {mutual_funds: [{schemes:
                                         [{transactions:[]}]}]} shape
                                         so cas_transactions.extract_
                                         transactions() can consume them.
"""
from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)


def _f(v, default: float = 0.0) -> float:
    try:
        if v is None or v == "":
            return default
        return float(v)
    except (TypeError, ValueError):
        return default


def _i(v, default: int = 0) -> int:
    try:
        if v is None or v == "":
            return default
        return int(float(v))
    except (TypeError, ValueError):
        return default


def _classify_sector(name: str) -> str:
    n = (name or "").lower()
    if any(k in n for k in ["index", "nifty", "sensex", "bees"]): return "Index"
    if any(k in n for k in ["small cap", "smallcap"]): return "Small Cap"
    if any(k in n for k in ["mid cap", "midcap"]): return "Mid Cap"
    if any(k in n for k in ["large cap", "largecap", "bluechip", "frontline", "large & mid"]): return "Large Cap"
    if any(k in n for k in ["flexi cap", "flexicap", "multi cap", "multicap"]): return "Flexi Cap"
    if any(k in n for k in ["balanced", "hybrid", "advantage", "dynamic"]): return "Balanced"
    if any(k in n for k in ["elss", "tax"]): return "ELSS"
    if any(k in n for k in ["debt", "bond", "gilt", "liquid", "money market", "overnight", "short", "credit", "arbitrage"]): return "Debt"
    if any(k in n for k in ["gold", "sgb"]): return "Gold"
    if any(k in n for k in ["international", "global", "us ", "nasdaq", "fang", "nyse"]): return "International"
    if any(k in n for k in ["contra", "value"]): return "Value"
    if any(k in n for k in ["focused", "opportunities"]): return "Focused"
    return "Other"


def _classify_mf(name: str) -> Tuple[str, str]:
    n = (name or "").lower()
    plan = "Direct" if "direct" in n else ("Regular" if "regular" in n else "Unknown")
    if "growth" in n:
        option = "Growth"
    elif "idcw" in n:
        option = "IDCW Reinvestment" if "reinv" in n else ("IDCW Payout" if "payout" in n else "IDCW")
    elif "dividend" in n:
        option = "Dividend Reinvestment" if "reinv" in n else "Dividend Payout"
    else:
        option = "Growth"
    return plan, option


# ── Holdings mapping ──────────────────────────────────────────────────
def _holding_from_equity(row: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    isin = (row.get("isin") or "").strip()
    name = (row.get("company_name") or row.get("stock_symbol") or "").strip()
    qty = _f(row.get("num_shares"))
    value = _f(row.get("value_inr"))
    price = _f(row.get("market_price_inr"))
    if price == 0 and qty > 0 and value > 0:
        price = round(value / qty, 4)
    if not isin or not name:
        return None
    is_etf = any(k in name.lower() for k in ["etf", "bees"])
    return {
        "name": name,
        "ticker": isin,
        "asset_type": "etf" if is_etf else "equity",
        "quantity": round(qty, 4),
        "buy_price": round(price, 4),
        "current_price": round(price, 4),
        "sector": _classify_sector(name) if is_etf else "Other",
        "parsed_by": "claude",
    }


def _holding_from_pref(row: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    isin = (row.get("isin") or "").strip()
    name = (row.get("company_name") or "").strip()
    qty = _f(row.get("num_shares"))
    value = _f(row.get("value_inr"))
    price = _f(row.get("market_price_inr"))
    if price == 0 and qty > 0 and value > 0:
        price = round(value / qty, 4)
    if not isin or not name:
        return None
    return {
        "name": name,
        "ticker": isin,
        "asset_type": "equity",
        "quantity": round(qty, 4),
        "buy_price": round(price, 4),
        "current_price": round(price, 4),
        "sector": "Preference Shares",
        "parsed_by": "claude",
    }


def _holding_from_sgb(row: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    isin = (row.get("isin") or "").strip()
    raw_name = (row.get("series") or row.get("issuer") or "Sovereign Gold Bond").strip()
    # Issuer-only names (e.g. "GOVERNMENT") leak through when Claude finds the
    # SGB row but no explicit series text. Resolve via ISIN lookup so the UI
    # shows the actual series (e.g. "SGB 2023-24 Series III") instead.
    from services.sgb_prices import resolve_sgb_display_name
    name = resolve_sgb_display_name(raw_name, isin)
    qty = _f(row.get("num_units"))
    price = _f(row.get("market_price_per_unit_inr"))
    value = _f(row.get("value_inr"))
    fv = _f(row.get("face_value_per_unit_inr"))
    # SGB per-gram prices have historically ranged ~₹2,500–₹20,000. When the
    # parser drops the *total holding value* into `market_price_per_unit_inr`
    # (e.g. 1329224 instead of ~15,000) and `value_inr` is left as 0, the
    # downstream `qty × price` blows up by 4-5 orders of magnitude. Detect the
    # anomaly and reinterpret the field as total value, then synthesise a
    # plausible (qty, unit_price) using the RBI issue price when known.
    SGB_UNIT_PRICE_CEILING = 50_000.0  # ₹/gram — well above any real market price
    NOMINAL_SGB_UNIT_PRICE = 10_000.0  # mid-range fallback when issue price unknown
    suspect = (value <= 0 and price > SGB_UNIT_PRICE_CEILING) or (
        value <= 0 and qty > 0 and price > 0 and fv > 0 and price > 50 * fv
    )
    if suspect:
        from services.sgb_prices import get_sgb_issue_price
        total = price  # the misplaced total
        sgb_info = get_sgb_issue_price(isin) or {}
        unit_price = float(sgb_info.get("issue_price") or NOMINAL_SGB_UNIT_PRICE)
        qty = round(total / unit_price, 4)
        price = round(unit_price, 4)
        value = total
    if price == 0 and qty > 0 and value > 0:
        price = round(value / qty, 4)
    if not isin and not name:
        return None
    return {
        "name": name,
        "ticker": isin or name,
        "asset_type": "gold",
        "quantity": round(qty, 4),
        "buy_price": round(price, 4),
        "current_price": round(price, 4),
        "sector": "Gold",
        "parsed_by": "claude",
    }


def _holding_from_mf_demat(row: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    isin = (row.get("isin") or "").strip()
    name = (row.get("fund_name") or "").strip()
    qty = _f(row.get("num_units"))
    nav = _f(row.get("nav_inr"))
    value = _f(row.get("value_inr"))
    if nav == 0 and qty > 0 and value > 0:
        nav = round(value / qty, 4)
    # When `value_inr` materially disagrees with qty*nav, trust the printed
    # value (it's read directly from the CAS column) and back-fill qty —
    # NAV is typically the most reliable column when both are present.
    if value > 0 and nav > 0 and qty > 0:
        expected = qty * nav
        if expected > 0 and abs(expected - value) / value > 0.05:
            qty = round(value / nav, 4)
    if not isin or not name:
        return None
    plan, option = _classify_mf(name)
    is_etf = any(k in name.lower() for k in ["etf", "bees"])
    return {
        "name": name,
        "ticker": isin,
        "asset_type": "etf" if is_etf else "mutual_fund",
        "quantity": round(qty, 4),
        "buy_price": round(nav, 4),
        "current_price": round(nav, 4),
        "sector": _classify_sector(name),
        "plan": plan,
        "option": option,
        "parsed_by": "claude_demat",
    }


def _holding_from_mf_folio(row: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    isin = (row.get("isin") or "").strip()
    name = (row.get("fund_name") or "").strip()
    qty = _f(row.get("num_units"))
    nav = _f(row.get("current_nav_inr"))
    value = _f(row.get("current_value_inr"))
    avg_cost = _f(row.get("avg_cost_per_unit_inr"))
    total_cost = _f(row.get("total_cost_inr"))
    if avg_cost == 0 and total_cost > 0 and qty > 0:
        avg_cost = round(total_cost / qty, 4)
    if nav == 0 and qty > 0 and value > 0:
        nav = round(value / qty, 4)
    # When `current_value_inr` disagrees with qty*nav by >5%, trust the
    # printed value (CAMS/KFin column is reliable) and back-fill qty.
    if value > 0 and nav > 0 and qty > 0:
        expected = qty * nav
        if expected > 0 and abs(expected - value) / value > 0.05:
            qty = round(value / nav, 4)
    if not isin or not name:
        return None
    plan, option = _classify_mf(name)
    is_etf = any(k in name.lower() for k in ["etf", "bees"])
    return {
        "name": name,
        "ticker": isin,
        "asset_type": "etf" if is_etf else "mutual_fund",
        "quantity": round(qty, 4),
        "buy_price": round(avg_cost or nav, 4),
        "current_price": round(nav, 4),
        "sector": _classify_sector(name),
        "plan": plan,
        "option": option,
        "folio_number": (row.get("folio_number") or "").strip(),
        "parsed_by": "claude_folio",
    }


_PURCHASE_TXN_KEYWORDS = ("PURCHASE", "SIP", "BUY", "ALLOTMENT", "INVESTMENT")
_NON_PURCHASE_KEYWORDS = ("REDEMPTION", "REDEEM", "SELL", "SALE", "SWITCH OUT", "SWITCH-OUT", "STT", "STAMP", "REVERSAL", "CANCEL", "PLEDGE")


def _is_purchase(t: Dict[str, Any]) -> bool:
    raw_type = (t.get("transaction_type") or t.get("type") or "").upper()
    desc = (t.get("description") or "").upper()
    blob = f"{raw_type} {desc}"
    if any(k in blob for k in _NON_PURCHASE_KEYWORDS):
        return False
    if any(k in blob for k in _PURCHASE_TXN_KEYWORDS):
        return True
    # Fallback: any txn with positive units AND positive amount looks like a buy
    try:
        units = float(t.get("units") or 0)
        amt = float(t.get("amount_inr") or t.get("amount") or 0)
    except (TypeError, ValueError):
        units, amt = 0.0, 0.0
    return units > 0 and amt > 0


def _build_buy_date_index(claude_data: Dict[str, Any]) -> Tuple[Dict[Tuple[str, str], str], Dict[str, str]]:
    """Scan transactions and return two earliest-purchase-date maps:
      by_isin_folio: {(isin, folio): YYYY-MM-DD}  — for MF folios
      by_isin:       {isin: YYYY-MM-DD}            — fallback for demat / equities

    The Claude payload puts transactions in a top-level dict (`mutual_fund_transactions`,
    `demat_transactions`) instead of nesting them under each holding the way
    casparser.in does, so the existing per-row helper can't see them.
    """
    by_pair: Dict[Tuple[str, str], str] = {}
    by_isin: Dict[str, str] = {}
    txns_root = claude_data.get("transactions") or {}

    def _ingest(items):
        for t in items or []:
            if not isinstance(t, dict):
                continue
            if not _is_purchase(t):
                continue
            d = (t.get("date") or "")[:10]
            if not d:
                continue
            isin = (t.get("isin") or "").strip().upper()
            folio = (t.get("folio_number") or t.get("folio") or "").strip()
            if isin and folio:
                key = (isin, folio)
                if key not in by_pair or d < by_pair[key]:
                    by_pair[key] = d
            if isin:
                if isin not in by_isin or d < by_isin[isin]:
                    by_isin[isin] = d

    _ingest(txns_root.get("mutual_fund_transactions"))
    _ingest(txns_root.get("demat_transactions"))
    return by_pair, by_isin


def _apply_buy_date(h: Dict[str, Any], row: Dict[str, Any],
                    by_pair: Dict[Tuple[str, str], str],
                    by_isin: Dict[str, str]) -> None:
    if h.get("buy_date"):
        return
    isin = (h.get("ticker") or "").strip().upper()
    folio = (row.get("folio_number") or row.get("folio") or "").strip()
    bd = by_pair.get((isin, folio)) if folio else None
    bd = bd or by_isin.get(isin)
    if bd:
        h["buy_date"] = bd


def map_to_holdings(claude_data: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Flatten Claude's nested holdings into our internal list."""
    out: List[Dict[str, Any]] = []
    holdings = claude_data.get("holdings") or {}
    by_pair, by_isin = _build_buy_date_index(claude_data)

    for r in holdings.get("equities") or []:
        h = _holding_from_equity(r)
        if h: _apply_buy_date(h, r, by_pair, by_isin); out.append(h)
    for r in holdings.get("preference_shares") or []:
        h = _holding_from_pref(r)
        if h: _apply_buy_date(h, r, by_pair, by_isin); out.append(h)
    for r in holdings.get("sovereign_gold_bonds") or []:
        h = _holding_from_sgb(r)
        if h: _apply_buy_date(h, r, by_pair, by_isin); out.append(h)
    for r in holdings.get("mutual_funds_demat") or []:
        h = _holding_from_mf_demat(r)
        if h: _apply_buy_date(h, r, by_pair, by_isin); out.append(h)
    for r in holdings.get("mutual_fund_folios") or []:
        h = _holding_from_mf_folio(r)
        if h: _apply_buy_date(h, r, by_pair, by_isin); out.append(h)

    n_dated = sum(1 for h in out if h.get("buy_date"))
    logger.info("Claude → %s holdings mapped (%s with buy_date)", len(out), n_dated)
    return out


# ── Transactions normalisation ────────────────────────────────────────
def map_to_normalized_transactions(claude_data: Dict[str, Any]) -> Dict[str, Any]:
    """Reshape Claude's `transactions.mutual_fund_transactions` array
    into the `{mutual_funds: [{amc, folio_number, schemes:
    [{scheme_name, isin, transactions: [...]}]}]}` shape that
    `services.cas_transactions.extract_transactions()` consumes.

    Each scheme is grouped by (folio_number, isin) so all transactions
    for the same folio+scheme combine into a single bucket.
    """
    txns = (claude_data.get("transactions") or {}).get("mutual_fund_transactions") or []
    if not isinstance(txns, list) or not txns:
        return {"mutual_funds": []}

    # Group by (folio_number, isin)
    groups: Dict[Tuple[str, str], Dict[str, Any]] = {}
    for t in txns:
        if not isinstance(t, dict):
            continue
        folio = (t.get("folio_number") or "").strip()
        isin = (t.get("isin") or "").strip()
        scheme_name = (t.get("fund_name") or "").strip()
        amc = _amc_from_fund_name(scheme_name)
        key = (folio, isin or scheme_name)
        if key not in groups:
            groups[key] = {
                "amc": amc,
                "folio_number": folio,
                "scheme_name": scheme_name,
                "isin": isin,
                "transactions": [],
            }
        # Build the txn record in the casparser.in-compatible shape:
        # {date, type/description, amount, units, nav}
        groups[key]["transactions"].append({
            "date": (t.get("date") or "")[:10],
            "type": (t.get("transaction_type") or "").upper(),
            "description": (t.get("transaction_type") or "").replace("_", " "),
            "amount": _f(t.get("amount_inr")),
            "units": _f(t.get("units")),
            "nav": _f(t.get("nav_inr") or t.get("price_inr")),
            "balance": _f(t.get("closing_balance_units")),
        })

    # Reshape into mutual_funds[folio][schemes[]] structure
    folios: Dict[Tuple[str, str], Dict[str, Any]] = {}
    for (folio, _isinkey), g in groups.items():
        # AMC + folio number is unique per investor
        f_key = (g["amc"], folio)
        folio_doc = folios.setdefault(f_key, {
            "amc": g["amc"],
            "folio_number": folio,
            "schemes": [],
        })
        folio_doc["schemes"].append({
            "scheme_name": g["scheme_name"],
            "isin": g["isin"],
            "transactions": g["transactions"],
        })

    return {"mutual_funds": list(folios.values())}


def _amc_from_fund_name(name: str) -> str:
    """Best-effort AMC extraction — picks the first 1-2 words before
    common suffixes like 'Mutual Fund', 'AMC', 'Asset Management'.
    """
    if not name:
        return ""
    n = name.strip()
    for marker in [" Mutual Fund", " Asset Management", " AMC"]:
        idx = n.lower().find(marker.lower())
        if idx > 0:
            return n[:idx].strip()
    # Otherwise take up to first 3 words
    parts = n.split()
    return " ".join(parts[:3])


def map_to_internal(claude_data: Dict[str, Any]) -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
    """Convenience: returns (holdings, normalized_for_txns) in a single
    call — matches the tuple shape used by `parse_cas_pdf_with_data`."""
    return map_to_holdings(claude_data), map_to_normalized_transactions(claude_data)
