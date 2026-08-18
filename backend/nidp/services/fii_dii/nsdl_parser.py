"""NSDL FPI / DII "Daily Trends" HTML parsers.

Why this exists:
    nidp.fii_dii_flows was fed only by NSE's `/api/fiidiiTradeReact`.
    NSE fronts every host with Akamai and 403s an egress IP whose
    reputation has dipped, which left 14 of 47 trading days missing.
    NSDL publishes the same daily institutional-flow picture from the
    custodian side, is not behind Akamai, and is reachable when NSE is
    not — so it doubles as a fallback source and as the *confirmed*
    counterpart to NSE's provisional numbers.

Two reports, both ASP.NET WebForms grids:
    FPI  https://www.fpi.nsdl.co.in/web/Reports/Latest.aspx
    DII  https://www.fpi.nsdl.co.in/web/Users/DIIGenerateReport.aspx?Rep=L

Grid shape:
    Both use rowspan, so a row carries only the labels that *change*.
    The trailing four cells are always
    (gross purchases, gross sales, net investment, net USD mn); the
    leading cells are labels, and how many there are tells you which
    level changed:

        Bank || Equity || Stock Exchange || 581.13 || 193.7 || 387.43 || 40.6
               Corporate Debt || Stock Exchange || ...      <- type inherited
                                 Primary market & others || ...  <- both inherited

    Negative values are parenthesised: "(618.83)" -> -618.83.

Deliberately NOT done — summing NSDL's own sub-totals:
    NSDL's DII note states that "Mutual Funds and Alternative Investment
    Funds are included both in Investor and Investment categories and
    hence sub-totals cannot be summed up to arrive at total resource
    mobilization." The `*-total` rows are therefore parsed and returned
    tagged, never added together.

Pure functions — no I/O, so they golden-file test against a saved page.
"""
from __future__ import annotations

import html
import logging
import re
from datetime import datetime
from typing import Any, Optional

logger = logging.getLogger(__name__)

# The closed set of "Investment Route" values. Used to disambiguate a
# two-label row: (instrument, route) vs (type, instrument).
_ROUTES = {"stock exchange", "primary market & others"}

_NUM_RE = re.compile(r"^\(?-?[\d,]+(?:\.\d+)?\)?$")


def _num(s: str) -> Optional[float]:
    """Parse an NSDL money cell. Parentheses mean negative."""
    s = (s or "").strip().replace(",", "").replace("\xa0", "")
    if not s or s in ("-", "—", "NA"):
        return None
    neg = s.startswith("(") and s.endswith(")")
    if neg:
        s = s[1:-1]
    try:
        v = float(s)
    except ValueError:
        return None
    return -v if neg else v


def _cells(row_html: str) -> list[str]:
    out = []
    for c in re.findall(r"<t[dh].*?</t[dh]>", row_html, re.S):
        txt = html.unescape(re.sub(r"<[^>]*>", "", c))
        txt = txt.replace("\xa0", " ").strip()
        if txt:
            out.append(txt)
    return out


def _biggest_table(body: bytes | str) -> str:
    s = body.decode("utf-8", errors="replace") if isinstance(body, bytes) else body
    tables = re.findall(r"<table.*?</table>", s, re.S)
    return max(tables, key=len) if tables else ""


def _report_date(body: bytes | str) -> Optional[str]:
    """Pull the 'on 17-Aug-2026' report date out of the page heading."""
    s = body.decode("utf-8", errors="replace") if isinstance(body, bytes) else body
    m = re.search(r"(\d{1,2}-[A-Za-z]{3}-\d{4})", re.sub(r"<[^>]*>", " ", s))
    if not m:
        return None
    for fmt in ("%d-%b-%Y", "%d-%B-%Y"):
        try:
            return datetime.strptime(m.group(1), fmt).date().isoformat()
        except ValueError:
            continue
    return None


def _split(cells: list[str]) -> tuple[Optional[str], list[str], list[float | None]]:
    """Split a row into (row_date, labels, [buy, sell, net, net_usd]).

    `row_date` is the row's own "Reporting Date" cell when it carries one.
    The Latest page repeats a single date; the Archive page returns many
    days in one response, each new day starting a row that leads with its
    date. Returning it lets one parser serve both.

    Trailing non-money cells (the 'Rs.95.4263' conversion column) are
    dropped. Returns (None, [], []) for non-data rows (headings, notes).
    """
    cs = [c for c in cells if not c.startswith("Rs.")]
    row_date: Optional[str] = None
    if cs and re.match(r"^\d{1,2}-[A-Za-z]{3}-\d{4}$", cs[0]):
        for fmt in ("%d-%b-%Y", "%d-%B-%Y"):
            try:
                row_date = datetime.strptime(cs[0], fmt).date().isoformat()
                break
            except ValueError:
                continue
        cs = cs[1:]
    nums_from = None
    for i, c in enumerate(cs):
        if _NUM_RE.match(c.replace(" ", "")):
            nums_from = i
            break
    if nums_from is None:
        return None, [], []
    labels = cs[:nums_from]
    nums = [_num(c) for c in cs[nums_from:]]
    if len(nums) < 3:
        return None, [], []
    return row_date, labels, (nums + [None, None, None, None])[:4]


def parse_nsdl_fpi(body: bytes | str, fallback_date: Optional[str] = None
                   ) -> list[dict[str, Any]]:
    """Parse the FPI 'Daily Trends in FPI Investments' grid.

    Emits fii_dii_flows-shaped rows with category='FII' (NSDL says FPI;
    the existing NSE parser already folds FPI into FII) and a segment
    derived from the asset class + investment route.
    """
    as_of = _report_date(body) or fallback_date
    if not as_of:
        logger.warning("NSDL FPI: no report date found")
        return []

    rows: list[dict[str, Any]] = []
    asset: Optional[str] = None
    cur_date = as_of
    for r in re.findall(r"<tr.*?</tr>", _biggest_table(body), re.S):
        row_date, labels, nums = _split(_cells(r))
        if row_date:
            cur_date = row_date
        if not nums:
            continue
        if len(labels) >= 2:
            asset, route = labels[0], labels[1]
        elif len(labels) == 1:
            route = labels[0]
        else:
            continue
        if asset is None:
            continue
        seg = _fpi_segment(asset, route)
        if seg is None:
            continue
        rows.append({
            "as_of_date": cur_date,
            "category": "FII",
            "segment": seg,
            "buy_value_cr": nums[0],
            "sell_value_cr": nums[1],
            "net_value_cr": nums[2],
        })
    return rows


def _fpi_segment(asset: str, route: str) -> Optional[str]:
    a, rt = asset.strip().lower(), route.strip().lower()
    if rt in ("sub-total", "total"):
        return None                      # never store NSDL's own aggregates
    if a == "equity":
        if rt == "stock exchange":
            return "EQUITY_CASH"         # the direct analogue of NSE's figure
        if rt == "primary market & others":
            return "EQUITY_PRIMARY"
    if a.startswith("debt") and rt == "stock exchange":
        return "DEBT_" + a.replace("debt-", "").replace(" ", "_").upper()
    if a == "hybrid" and rt == "stock exchange":
        return "HYBRID"
    return None


def parse_nsdl_dii(body: bytes | str, fallback_date: Optional[str] = None
                   ) -> list[dict[str, Any]]:
    """Parse the DII 'Daily Trends' grid into per-investor-type rows.

    category is DII_<TYPE> (DII_BANK, DII_INSURANCE, DII_MF, DII_AIF,
    DII_OTHERS) so the DII split NSE never published is preserved.
    NSDL's own `*-total` rows are skipped — see the module docstring.
    """
    as_of = _report_date(body) or fallback_date
    if not as_of:
        logger.warning("NSDL DII: no report date found")
        return []

    rows: list[dict[str, Any]] = []
    dii_type: Optional[str] = None
    instrument: Optional[str] = None
    for r in re.findall(r"<tr.*?</tr>", _biggest_table(body), re.S):
        _row_date, labels, nums = _split(_cells(r))
        if not nums:
            continue
        if len(labels) >= 3:
            dii_type, instrument, route = labels[0], labels[1], labels[2]
        elif len(labels) == 2:
            # (instrument, route) if the 2nd is a route, else (type, instrument)
            if labels[1].strip().lower() in _ROUTES:
                instrument, route = labels[0], labels[1]
            else:
                dii_type, instrument = labels[0], labels[1]
                route = ""
        elif len(labels) == 1:
            lbl = labels[0].strip().lower()
            if lbl.endswith("-total") or lbl == "total":
                continue                 # NSDL aggregate — not summable
            route = labels[0]
        else:
            continue
        if not (dii_type and instrument):
            continue
        # Only the equity cash-market leg is comparable to NSE's DII number.
        if instrument.strip().lower() != "equity":
            continue
        if route.strip().lower() != "stock exchange":
            continue
        rows.append({
            "as_of_date": as_of,
            "category": "DII_" + _dii_type_code(dii_type),
            "segment": "EQUITY_CASH",
            "buy_value_cr": nums[0],
            "sell_value_cr": nums[1],
            "net_value_cr": nums[2],
        })

    rows.extend(_derived_dii_total(rows, as_of))
    return rows


def _derived_dii_total(per_type: list[dict[str, Any]], as_of: str
                       ) -> list[dict[str, Any]]:
    """Add the aggregate category='DII' row, summed over investor types.

    NSDL publishes no single "DII" equity number, but downstream expects
    one (it is the analogue of NSE's DII cash print, and the
    `fii_dii.cash_rows_present` validator requires categories FII *and*
    DII for segment EQUITY_CASH).

    Summing is sound *here* specifically because the instrument axis is
    pinned to Equity. NSDL's warning that "sub-totals cannot be summed up"
    concerns its `*-total` rows, which run across the instrument
    dimension where MF and AIF appear as both investor type and
    instrument and would double-count. Bank / Insurance / MFs / AIFs /
    Others buying *equity on the stock exchange* are disjoint investors,
    so their equity legs add up cleanly.
    """
    legs = [r for r in per_type if r["segment"] == "EQUITY_CASH"]
    if not legs:
        return []

    def _sum(key: str) -> Optional[float]:
        vals = [r[key] for r in legs if r.get(key) is not None]
        return round(sum(vals), 2) if vals else None

    return [{
        "as_of_date": as_of,
        "category": "DII",
        "segment": "EQUITY_CASH",
        "buy_value_cr": _sum("buy_value_cr"),
        "sell_value_cr": _sum("sell_value_cr"),
        "net_value_cr": _sum("net_value_cr"),
    }]


def _dii_type_code(t: str) -> str:
    t = t.strip().lower().rstrip("s")
    return {
        "bank": "BANK",
        "insurance": "INSURANCE",
        "mf": "MF",
        "aif": "AIF",
        "other": "OTHERS",
    }.get(t, re.sub(r"[^A-Z0-9]+", "_", t.upper()))
