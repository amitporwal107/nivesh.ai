"""Broker holdings-export parsing for the manual upload path.

A user who does not want a live broker connection uploads the holdings file
their broker lets them download. Those files are not the tidy "header on row 1"
sheets the upload parsers used to assume: they carry account details above the
header, broker-specific column names, Indian-format numbers ("1,23,456.78") and
totals / disclaimer rows below the data.

Layouts read here (.csv, .xlsx, .xls):
    Zerodha, Groww, Upstox, Angel One, ICICI Direct, HDFC Securities,
    Kotak Securities, Dhan, 5paisa   — equity holdings
    MF Central                       — mutual-fund holdings
    generic                          — the Name / Quantity / Buy Price sheet the
                                       upload endpoint has always accepted

The per-broker column names are taken from WealthPulse
(https://github.com/kustonaut/WealthPulse, MIT licence —
src/wealthpulse/parsers/*.py). The implementation is our own.

Entry points: :func:`parse_csv_statement` and :func:`parse_excel_statement`.
Both return a :class:`ParsedStatement` whose `holdings` are row dicts in the
shape `helpers.parsing.save_holdings` consumes. Rows of a recognised broker
export also carry `source` ("broker_export"), `broker` (the slug) and, when the
file gives one, `isin` — what helpers.holdings_reconcile matches on. Generic
rows carry none of the three, so they are stored exactly as before.
"""
import csv
import io
import logging
import math
import re
from dataclasses import dataclass, field
from typing import Callable, List, Optional, Tuple

from fastapi import HTTPException

logger = logging.getLogger(__name__)

# Broker exports put client details / titles above the table, so the header is
# searched for in the leading rows rather than assumed to be row 1.
_HEADER_SCAN_ROWS = 40

_XLSX_MAGIC = b"PK\x03\x04"  # .xlsx is a zip; anything else is handed to xlrd (.xls)
_ISIN = re.compile(r"IN[A-Z0-9]{9}\d")
# `source` stamped on rows of a recognised broker export
# (helpers.holdings_reconcile.BROKER_EXPORT_SOURCE).
_BROKER_EXPORT_SOURCE = "broker_export"


@dataclass(frozen=True)
class _Layout:
    id: str  # for a broker this is the slug stored on its rows as `broker`
    label: Optional[str] = None
    # Each signature is a set of header keys that together identify the export.
    signatures: Tuple[frozenset, ...] = ()
    filename_hints: Tuple[str, ...] = ()
    # WealthPulse skips rows with quantity <= 0 for these brokers; we do the same.
    drop_zero_qty: bool = False
    asset_type: str = "equity"


def _sig(*keys: str) -> frozenset:
    return frozenset(keys)


_BROKERS = (
    _Layout("zerodha", "Zerodha",
            (_sig("symbol", "average price", "previous closing price"),   # Console .xlsx
             # Kite's own holdings .csv. Not in WealthPulse: it shares Instrument /
             # Avg. cost / Cur. val with the Upstox layout and adds "Day chg.".
             _sig("instrument", "avg cost", "cur val", "day chg")),
            ("zerodha", "kite")),
    _Layout("groww", "Groww",
            (_sig("stock name", "buy value", "closing value"),),
            ("groww", "grow")),
    _Layout("upstox", "Upstox",
            (_sig("instrument", "avg cost", "cur val"),),
            ("upstox",), drop_zero_qty=True),
    _Layout("angel", "Angel One",
            (_sig("avg cost", "current value", "% p&l"),        # .xlsx export
             _sig("scrip name", "avg price", "cur value")),     # .csv export
            ("angelone", "angelbroking", "angel"), drop_zero_qty=True),
    _Layout("icicidirect", "ICICI Direct",
            (_sig("stock symbol", "company name", "buy avg price"),),
            ("icicidirect", "icici"), drop_zero_qty=True),
    _Layout("hdfcsec", "HDFC Securities",
            (_sig("company name", "buy avg", "current value"),),
            ("hdfcsecurities", "hdfcsec", "hdfc"), drop_zero_qty=True),
    _Layout("kotak", "Kotak Securities",
            (_sig("symbol", "avg price", "change %"),),
            ("kotaksecurities", "kotaksec", "kotakneo", "kotak"), drop_zero_qty=True),
    _Layout("dhan", "Dhan",
            (_sig("trading symbol", "avg cost price", "close price"),),
            ("dhan",), drop_zero_qty=True),
    _Layout("fivepaisa", "5paisa",
            (_sig("scrip name", "scrip code", "avg rate"),),
            ("5paisa", "fivepaisa"), drop_zero_qty=True),
    _Layout("mfcentral", "MF Central",
            (_sig("scheme name", "units", "invested value", "current value"),),
            ("mfcentral", "mutualfunds", "mutual_funds", "mf"), asset_type="mutual_fund"),
)
_GENERIC = _Layout("generic")
# A holdings table we can read but whose broker the columns do not give away.
_UNIDENTIFIED = _Layout("unidentified")

# Header keys (see _norm) for the generic template — exactly the column names
# the upload parsers accepted before this module existed, in the priority order
# parse_excel_holdings used, so a sheet that imported then imports the same now.
_GENERIC_COLUMNS = {
    "name": ("name", "scheme name", "fund", "stock", "scheme"),
    "ticker": ("ticker", "symbol", "isin"),
    "asset_type": ("asset type", "type"),
    "quantity": ("quantity", "qty", "units", "balance units"),
    "buy_price": ("buy price", "avg price", "avg cost", "nav", "cost"),
    "current_price": ("current price", "ltp", "cmp", "current nav", "market value"),
    "sector": ("sector",),
    "buy_date": ("buy date", "date"),
}
# parse_csv_holdings ranked two of them differently; kept for the same reason.
_GENERIC_CSV_ORDER = {
    "name": ("name", "stock", "scheme name", "fund"),
    "buy_price": ("buy price", "avg price", "cost", "avg cost", "nav"),
}

# Header keys for broker / MF exports: the union of WealthPulse's per-broker
# column names. "quantity available" (Zerodha) and "average buy price" (Groww)
# are spellings we added alongside WealthPulse's "qty available" / "avg buy price".
_EXPORT_COLUMNS = {
    "name": ("company name", "stock name", "scheme name", "security name", "name"),
    "symbol": ("stock symbol", "trading symbol", "nse symbol", "symbol", "instrument",
               "scrip name", "script name", "scrip", "script", "stock", "security", "company"),
    # Exchange / broker codes: only used when a row has neither symbol nor ISIN.
    "code": ("scrip code", "stock code"),
    "isin": ("isin", "isin code", "isin no"),
    "quantity": ("quantity", "qty", "qty available", "quantity available", "net qty",
                 "total qty", "holding qty", "available qty", "free qty", "units"),
    "buy_price": ("average price", "avg price", "avg cost", "avg buy price",
                  "average buy price", "buy avg price", "buy avg", "avg cost price",
                  "avg rate", "average rate", "buy price", "cost price"),
    "current_price": ("ltp", "last price", "current price", "close price", "closing price",
                      "previous closing price", "mkt price", "market price"),
    # Totals, used to derive a unit price when the export has no price column.
    "invested": ("invested value", "buy value"),
    "value": ("current value", "cur value", "cur val", "closing value", "mkt value",
              "market value"),
    "sector": ("sector", "industry"),
}

_INSTRUMENT_KEYS = frozenset(
    _GENERIC_COLUMNS["name"] + _EXPORT_COLUMNS["name"] + _EXPORT_COLUMNS["symbol"])
_QUANTITY_KEYS = frozenset(_GENERIC_COLUMNS["quantity"] + _EXPORT_COLUMNS["quantity"])
_PRICE_KEYS = frozenset(
    _EXPORT_COLUMNS["buy_price"] + _EXPORT_COLUMNS["current_price"]
    + _EXPORT_COLUMNS["invested"] + _EXPORT_COLUMNS["value"])

_UNRECOGNISED = (
    "Could not find a holdings table in this file. Looked in the first "
    f"{_HEADER_SCAN_ROWS} rows for a header row with a name or symbol column "
    f"({', '.join(sorted(_INSTRUMENT_KEYS))}) and a quantity column "
    f"({', '.join(sorted(_QUANTITY_KEYS))}); a broker export also needs a price or "
    f"value column ({', '.join(sorted(_PRICE_KEYS))}). Upload the holdings file "
    "downloaded from Zerodha, Groww, Upstox, Angel One, ICICI Direct, HDFC Securities, "
    "Kotak Securities, Dhan, 5paisa or MF Central, or a sheet with Name, Quantity, "
    "Buy Price and Current Price columns."
)
_UNREADABLE_EXCEL = (
    "Could not read this Excel file. It may be damaged or password-protected. "
    "Download the holdings file from your broker again, or save it as .xlsx or .csv "
    "and upload that."
)

# Cell text that means "no value" in a numeric column.
_NO_NUMBER = frozenset({"", "-", "--", "na", "n/a", "nil", "null", "none"})
_NUMBER_NOISE = re.compile(r"rs\.?|inr|[₹$,%\s]", re.IGNORECASE)

# A row whose label is made only of these words is a totals / summary line
# ("Total", "Grand Total:", "Total Invested Value", "Current Value"), not a holding.
_SUMMARY_WORDS = frozenset(
    "total totals subtotal grand sub net overall portfolio summary holdings invested "
    "investment current market value amount cost p&l pnl returns gain profit loss "
    "unrealised unrealized".split())


@dataclass
class ParsedStatement:
    """What was read from an uploaded holdings file."""
    holdings: list = field(default_factory=list)  # rows in the shape save_holdings consumes
    layout: Optional[str] = None   # a broker slug, "generic" or "unidentified"; None for an empty file
    broker: Optional[str] = None   # broker slug ("zerodha"); None for generic / unidentified
    broker_name: Optional[str] = None  # display name ("Zerodha")
    kind: str = ""                 # "csv" | "xlsx" | "xls"
    header_row: int = 0            # 1-based row the header was found on; 0 for an empty file
    skipped_rows: int = 0          # non-blank rows below the header that were not holdings


def parse_csv_statement(content: bytes, filename: str = "") -> ParsedStatement:
    """Read a holdings CSV. `filename` is only a secondary hint for naming the broker."""
    return _parse_tables([_read_csv(content)], "csv", filename)


def parse_excel_statement(content: bytes, filename: str = "") -> ParsedStatement:
    """Read a holdings workbook: .xlsx via openpyxl, legacy .xls via xlrd."""
    if content[:4] == _XLSX_MAGIC:
        return _parse_tables(_read_xlsx(content), "xlsx", filename)
    return _parse_tables(_read_xls(content), "xls", filename)


# ── File readers: bytes -> list of sheets, each a list of rows of cells ─────

def _read_csv(content: bytes) -> list:
    # utf-8-sig drops the BOM Excel writes; cp1252 covers Windows exports;
    # latin-1 accepts any byte, so it has to come last.
    for encoding in ("utf-8-sig", "cp1252", "latin-1"):
        try:
            text = content.decode(encoding)
            break
        except UnicodeDecodeError:
            continue
    else:
        raise HTTPException(status_code=400, detail="Could not decode file. Please use UTF-8 encoding.")
    try:
        return list(csv.reader(io.StringIO(text, newline="")))
    except csv.Error as e:
        raise HTTPException(status_code=400, detail=f"Could not read the CSV file: {e}") from e


def _read_xlsx(content: bytes) -> list:
    import openpyxl
    try:
        wb = openpyxl.load_workbook(io.BytesIO(content), read_only=True, data_only=True)
        try:
            # Active sheet first (the only one read before), then the others in order.
            sheets = ([ws for ws in wb.worksheets if ws is wb.active]
                      + [ws for ws in wb.worksheets if ws is not wb.active])
            tables = []
            for ws in sheets:
                # Some exporters write a wrong <dimension> (e.g. "A1"); read-only mode
                # would then yield a single cell. Resetting makes openpyxl read every row.
                ws.reset_dimensions()
                tables.append([list(row) for row in ws.iter_rows(values_only=True)])
            return tables
        finally:
            wb.close()
    except Exception as e:  # noqa: BLE001 — openpyxl raises many types on a damaged workbook
        logger.warning("statement export: unreadable .xlsx: %s: %s", type(e).__name__, e)
        raise HTTPException(status_code=400, detail=_UNREADABLE_EXCEL) from e


def _read_xls(content: bytes) -> list:
    import xlrd
    try:
        book = xlrd.open_workbook(file_contents=content)
        tables = []
        for sheet in book.sheets():
            rows = []
            for r in range(sheet.nrows):
                cells = []
                for cell in sheet.row(r):
                    if cell.ctype in (xlrd.XL_CELL_EMPTY, xlrd.XL_CELL_BLANK, xlrd.XL_CELL_ERROR):
                        cells.append(None)  # an error cell holds an error code, not a value
                    elif cell.ctype == xlrd.XL_CELL_DATE:
                        cells.append(xlrd.xldate_as_datetime(cell.value, book.datemode))
                    else:
                        cells.append(cell.value)
                rows.append(cells)
            tables.append(rows)
        return tables
    except Exception as e:  # noqa: BLE001 — xlrd raises many types on a damaged / encrypted workbook
        logger.warning("statement export: unreadable .xls: %s: %s", type(e).__name__, e)
        raise HTTPException(status_code=400, detail=_UNREADABLE_EXCEL) from e


# ── Cell helpers ────────────────────────────────────────────────────────────

def _blank(value) -> bool:
    return value is None or (isinstance(value, str) and not value.strip())


def _text(value) -> str:
    """Cell -> stripped text. A whole number read as a float (500325.0) loses the ".0"."""
    if value is None:
        return ""
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    return str(value).strip()


def _norm(cell) -> str:
    """Header cell -> lookup key: "Avg. Cost", "avg_cost" and " AVG  COST " are all "avg cost"."""
    return " ".join(_text(cell).lower().replace("_", " ").replace(".", "").split())


def _num(value) -> Optional[float]:
    """Cell -> float, or None when the cell is blank or holds no number.

    Reads numeric cells and text such as "1,23,456.78", "₹ 2,400.50", "Rs. 500"
    and the accounting negative "(1,200.00)"; "-", "N/A" and the like are blank.
    """
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        number = float(value)
    else:
        text = _NUMBER_NOISE.sub("", str(value)).lower()
        negative = text.startswith("(") and text.endswith(")")
        text = text.strip("()")
        if text in _NO_NUMBER:
            return None
        try:
            number = -float(text) if negative else float(text)
        except ValueError:
            return None
    return number if math.isfinite(number) else None


def _clean_symbol(symbol: str) -> str:
    """Drop exchange prefix and series suffix: "NSE:RELIANCE-EQ", "NSE_EQ:RELIANCE"
    and "BSE-RELIANCE" all become "RELIANCE"."""
    symbol = symbol.upper().split(":")[-1].strip()
    if symbol.startswith(("NSE-", "BSE-")):
        symbol = symbol[4:]
    if symbol.endswith("_EQ"):
        symbol = symbol[:-3]
    # Exchange series suffix (-EQ, -BE, -Z ...); -RR marks a REIT and stays.
    base, dash, series = symbol.rpartition("-")
    if dash and base and len(series) <= 2 and series != "RR":
        symbol = base
    return symbol


def _is_summary_label(name: str) -> bool:
    words = re.sub(r"[:/()\-]", " ", name.lower()).split()
    return bool(words) and all(w in _SUMMARY_WORDS for w in words)


# ── Header and layout detection ─────────────────────────────────────────────

def _generic_columns(kind: str) -> dict:
    return {**_GENERIC_COLUMNS, **_GENERIC_CSV_ORDER} if kind == "csv" else _GENERIC_COLUMNS


def _layout_from_filename(filename: str) -> Optional[_Layout]:
    name = (filename or "").lower()
    for layout in _BROKERS:
        for hint in layout.filename_hints:
            # Whole word only: "dhan_holdings.csv" yes, "dhananjay.csv" no.
            if re.search(rf"(?<![a-z0-9]){re.escape(hint)}(?![a-z])", name):
                return layout
    return None


def _identify_broker(keys: set, filename: str) -> Optional[_Layout]:
    """Name the broker from its signature columns; the file name only breaks a tie."""
    scores = {
        layout: max((len(sig) for sig in layout.signatures if sig <= keys), default=0)
        for layout in _BROKERS
    }
    best = max(scores.values())
    if not best:
        return None
    candidates = [layout for layout, score in scores.items() if score == best]
    hinted = _layout_from_filename(filename)
    return hinted if hinted in candidates else candidates[0]


def _find_header(rows: list, kind: str, filename: str) -> Optional[Tuple[int, _Layout]]:
    """Locate the header row in the leading rows. Returns (row index, layout) or None."""
    generic_names = set(_generic_columns(kind)["name"])
    for index, row in enumerate(rows[:_HEADER_SCAN_ROWS]):
        keys = {_norm(cell) for cell in row} - {""}
        if not (keys & _INSTRUMENT_KEYS and keys & _QUANTITY_KEYS):
            continue
        broker = _identify_broker(keys, filename)
        if broker:
            return index, broker
        if keys & generic_names:
            return index, _GENERIC
        if keys & _PRICE_KEYS:
            return index, _layout_from_filename(filename) or _UNIDENTIFIED
    # The old parsers took the first row as the header whenever it had a name
    # column, even with no quantity column (such rows import with quantity 0).
    for index, row in enumerate(rows):
        if any(not _blank(cell) for cell in row):
            return (index, _GENERIC) if {_norm(cell) for cell in row} & generic_names else None
    return None


def _picker(header: List[str], columns: dict) -> Callable:
    """Build pick(row, field): the first non-blank cell among the field's columns."""
    index = {
        fld: [i for alias in aliases for i, key in enumerate(header) if key == alias]
        for fld, aliases in columns.items()
    }

    def pick(row, fld):
        for i in index[fld]:
            if i < len(row) and not _blank(row[i]):
                return row[i]
        return None

    return pick


# ── Row mapping ─────────────────────────────────────────────────────────────

def _generic_holding(row, pick) -> Optional[dict]:
    """Generic template row, read the way the old parsers did: only a name is
    required and a missing number is 0."""
    name = _text(pick(row, "name"))
    ticker = _text(pick(row, "ticker"))
    if not name or (_is_summary_label(name) and not _ISIN.fullmatch(ticker.upper())):
        return None
    return {
        "name": name,
        "ticker": ticker,
        "asset_type": _text(pick(row, "asset_type")).lower() or "equity",
        "quantity": _num(pick(row, "quantity")) or 0.0,
        "buy_price": _num(pick(row, "buy_price")) or 0.0,
        "current_price": _num(pick(row, "current_price")) or 0.0,
        "sector": _text(pick(row, "sector")) or "Other",
        "buy_date": _text(pick(row, "buy_date")),
    }


def _export_holding(row, pick, layout: _Layout) -> Optional[dict]:
    """Broker / MF export row. `ticker` is the trading symbol when the export
    has one, else the ISIN; the ISIN itself travels in `isin`."""
    isin = _text(pick(row, "isin")).upper()
    if not _ISIN.fullmatch(isin):
        isin = ""
    label = _text(pick(row, "symbol"))
    # A trading symbol has no spaces; a company name in that column is not one.
    symbol = "" if " " in label else _clean_symbol(label)
    name = _text(pick(row, "name")) or symbol or label
    qty, buy, cur, invested, value = (
        _num(pick(row, fld)) for fld in ("quantity", "buy_price", "current_price", "invested", "value"))

    if not name or (_is_summary_label(name) and not isin):
        return None
    # Footers, notes and section titles: text with no ISIN and no number at all.
    if not isin and all(n is None for n in (qty, buy, cur, invested, value)):
        return None
    qty = qty or 0.0
    if layout.drop_zero_qty and qty <= 0:
        return None

    # Some exports give totals rather than unit prices (MF Central has no price column).
    if not buy and invested and qty > 0:
        buy = round(invested / qty, 4)
    if not cur and value and qty > 0:
        cur = round(value / qty, 4)

    if isin.startswith("INF"):
        asset_type = "mutual_fund"
    elif isin.startswith("INE"):
        asset_type = "equity"
    else:
        asset_type = layout.asset_type
    holding = {
        "name": name,
        "ticker": symbol or isin or _clean_symbol(_text(pick(row, "code"))),
        "asset_type": asset_type,
        "quantity": qty,
        "buy_price": buy or 0.0,
        "current_price": cur or 0.0,
        "sector": _text(pick(row, "sector")) or "Other",
        "buy_date": "",
    }
    if isin:
        holding["isin"] = isin
    if layout is not _UNIDENTIFIED:
        # A named broker: save_holdings replaces that broker's earlier export.
        holding["source"] = _BROKER_EXPORT_SOURCE
        holding["broker"] = layout.id
    return holding


def _parse_tables(tables: list, kind: str, filename: str) -> ParsedStatement:
    """Read holdings from the first sheet that has a recognisable header row."""
    for rows in tables:
        found = _find_header(rows, kind, filename)
        if not found:
            continue
        index, layout = found
        header = [_norm(cell) for cell in rows[index]]
        generic = layout is _GENERIC
        pick = _picker(header, _generic_columns(kind) if generic else _EXPORT_COLUMNS)

        data_rows = [row for row in rows[index + 1:] if any(not _blank(c) for c in row)]
        holdings = []
        for row in data_rows:
            holding = _generic_holding(row, pick) if generic else _export_holding(row, pick, layout)
            if holding:
                holdings.append(holding)

        skipped = len(data_rows) - len(holdings)
        logger.info(
            "statement export parsed: layout=%s kind=%s header_row=%d holdings=%d skipped=%d",
            layout.id, kind, index + 1, len(holdings), skipped,
        )
        broker = layout.id if layout in _BROKERS else None
        return ParsedStatement(holdings, layout.id, broker, layout.label, kind, index + 1, skipped)

    if any(not _blank(cell) for rows in tables for row in rows for cell in row):
        raise HTTPException(status_code=400, detail=_UNRECOGNISED)
    # Nothing in the file at all: same empty result the old parsers gave.
    return ParsedStatement(kind=kind)
