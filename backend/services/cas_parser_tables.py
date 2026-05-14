"""
Table-aware CAS parser using img2table (OpenCV line detection) + Tesseract OCR.

This solves the "missed rows" failure mode of flat-text OCR parsing by extracting
structured DataFrames from each holdings page, then parsing holdings row-by-row
from known columns (no regex guessing on which number is price vs qty vs value).

Fallbacks to the legacy text-based parser in cas_parser.py when no tables are found.
"""
import io
import logging
import re
from typing import Dict, List, Optional
import numpy as np
import pandas as pd

logger = logging.getLogger("cas_parser_tables")

ISIN_RE = re.compile(r'\b(IN[A-Z0-9]{10})\b')

# ══════════════════════════════════════════════════════════════
# Number parsing
# ══════════════════════════════════════════════════════════════

def _clean(v) -> str:
    """Stringify a cell value, strip whitespace, replace NaN."""
    if v is None or (isinstance(v, float) and np.isnan(v)):
        return ""
    return str(v).strip()


def _parse_num(v) -> float:
    """Parse a numeric cell (handles ₹, commas, spaces, OCR garbage)."""
    s = _clean(v)
    if not s:
        return 0.0
    # Remove common OCR/currency prefixes
    s = re.sub(r'[₹=&<>$|]', '', s)
    s = s.replace(",", "").strip()
    # Pick first number-like token
    m = re.search(r'-?\d+\.?\d*', s)
    if not m:
        return 0.0
    try:
        return float(m.group())
    except ValueError:
        return 0.0


def _find_isin_in_text(s: str) -> str:
    """Extract ISIN from text, with OCR-char fixes."""
    if not s:
        return ""
    # Common OCR errors: 1N→IN, O→0
    s_fixed = s.replace("1N", "IN").replace("|N", "IN")
    m = ISIN_RE.search(s_fixed)
    if m:
        return _fix_isin(m.group(1))
    # Second pass: broader pattern with OCR-char substitutions
    m2 = re.search(r'\b[I1][NM][A-Z0-9O]{10}\b', s)
    if m2:
        candidate = m2.group(0).replace("1", "I", 1).replace("M", "N", 1).replace("O", "0")
        # Only in the numeric tail
        return _fix_isin(candidate[:2] + m2.group(0)[2:].replace("O", "0"))
    return ""


def _fix_isin(raw: str) -> str:
    """Fix common OCR errors in ISINs (port of cas_parser.fix_isin_ocr)."""
    if len(raw) < 12:
        return raw
    chars = list(raw[:12])
    if chars[0] in ('1', 'i', '|', 'l'):
        chars[0] = 'I'
    if chars[1] in ('M', 'm'):
        chars[1] = 'N'
    for i in range(3, 12):
        ch = chars[i]
        if ch in ('O', 'o'):
            chars[i] = '0'
        elif ch == 'S' and i >= 6:
            chars[i] = '5'
        elif ch == 'l' and i >= 6:
            chars[i] = '1'
        elif ch == 'I' and i >= 6:
            prev_c = chars[i - 1] if i > 0 else ''
            next_c = chars[i + 1] if i + 1 < 12 else ''
            if prev_c.isdigit() or (next_c.isdigit() and i >= 7):
                chars[i] = '1'
        elif ch == 'B' and i >= 9:
            chars[i] = '8'
        elif ch == 'Z' and i >= 6:
            chars[i] = '2'
        elif ch == 'G' and i >= 9:
            chars[i] = '6'
    return "".join(chars)


def _classify_sector(name: str) -> str:
    n = name.lower()
    if any(k in n for k in ["index", "nifty", "sensex", "bees"]): return "Index"
    if any(k in n for k in ["small cap", "smallcap"]): return "Small Cap"
    if any(k in n for k in ["mid cap", "midcap"]): return "Mid Cap"
    if any(k in n for k in ["large cap", "largecap", "large & mid", "bluechip", "frontline"]): return "Large Cap"
    if any(k in n for k in ["flexi cap", "flexicap", "multi cap", "multicap"]): return "Flexi Cap"
    if any(k in n for k in ["balanced", "hybrid", "advantage", "dynamic"]): return "Balanced"
    if any(k in n for k in ["elss", "tax"]): return "ELSS"
    if any(k in n for k in ["debt", "bond", "gilt", "liquid", "money market", "overnight", "short", "credit", "arbitrage"]): return "Debt"
    if any(k in n for k in ["gold", "sgb"]): return "Gold"
    if any(k in n for k in ["international", "global", "us ", "nasdaq", "fang", "nyse"]): return "International"
    if any(k in n for k in ["contra", "value"]): return "Value"
    if any(k in n for k in ["focused", "opportunities"]): return "Focused"
    return "Other"


def _clean_name(raw: str) -> str:
    """Clean a scheme/company name extracted from a table cell."""
    s = _clean(raw)
    if not s:
        return ""
    # Drop newlines, excess whitespace
    s = re.sub(r'\s+', ' ', s.replace("\n", " "))
    # Drop stock symbol suffixes (".NSE", ".BSE")
    s = re.sub(r'\b[A-Z]{3,}\.(NSE|BSE)\b', '', s)
    # Drop "of which Pledged..." and other boilerplate
    s = re.sub(r'of which\s+Pledged.*?$', '', s, flags=re.IGNORECASE)
    s = re.sub(r'Unconfirmed.*?$', '', s, flags=re.IGNORECASE)
    # Remove punctuation noise but keep common chars
    s = re.sub(r'[^\w\s&\-\(\)/.+]', ' ', s)
    s = re.sub(r'\s+', ' ', s).strip()
    return s


# ══════════════════════════════════════════════════════════════
# Table-type classification from headers
# ══════════════════════════════════════════════════════════════

def _header_text(df: pd.DataFrame, rows: int = 3) -> str:
    """Concatenate first N rows as a string for header detection."""
    parts = []
    for i in range(min(rows, len(df))):
        parts.extend(_clean(c) for c in df.iloc[i].tolist())
    return " ".join(parts).lower()


def classify_table(df: pd.DataFrame) -> str:
    """
    Return one of: 'equity', 'mf_demat', 'sgb', 'mf_folio', 'cdsl_equity',
                   'cdsl_mf_folio', 'summary', 'unknown'
    """
    header = _header_text(df, rows=3)

    # Disqualifiers: if header mentions MF-specific terms, never classify as equity
    has_folio = bool(re.search(r'folio\s*no', header))
    has_nav = bool(re.search(r'\bnav\b', header))
    has_units = bool(re.search(r'\bunits\b', header))

    # NSDL equity: ISIN + Company Name + Face Value + Shares + Market Price
    if (re.search(r'company\s*name', header) and re.search(r'face\s*value', header)
            and (re.search(r'shares', header) or re.search(r'no\.?\s*of', header))
            and not has_folio and not has_nav and not has_units):
        return 'equity'

    # NSDL SGB: maturity + coupon rate
    if re.search(r'maturity', header) and re.search(r'coupon', header):
        return 'sgb'

    # NSDL MF Folios: Folio No + Units + Avg Cost + Current NAV
    if has_folio and has_units and \
            (re.search(r'average\s*cost', header) or re.search(r'avg\.?\s*cost', header)
             or re.search(r'current\s*nav', header)):
        return 'mf_folio'

    # NSDL MF Demat (M): ISIN + Description + Units + NAV + Value (no Folio)
    if re.search(r'description', header) and has_units and has_nav and not has_folio:
        return 'mf_demat'

    # CDSL equity: "Security" + "Current"
    if re.search(r'security', header) and re.search(r'current', header) and not has_folio:
        return 'cdsl_equity'

    # CDSL MF: "Scheme Name" + "Folio"
    if re.search(r'scheme\s*name', header) and has_folio:
        return 'cdsl_mf_folio'

    # Summary: "ASSET CLASS"
    if re.search(r'asset\s*class', header):
        return 'summary'

    return 'unknown'


# ══════════════════════════════════════════════════════════════
# Row parsers — one per table type
# ══════════════════════════════════════════════════════════════

def _row_values(df: pd.DataFrame, row_idx: int) -> list:
    return [_clean(df.iat[row_idx, c]) for c in range(df.shape[1])]


def _all_numbers_in_row(row_vals: list) -> list:
    """Extract every parseable number from a row's cells, in column order."""
    nums = []
    for v in row_vals:
        if not v:
            continue
        for tok in re.findall(r'-?\d[\d,]*\.?\d*', v):
            n = _parse_num(tok)
            if n > 0:
                nums.append(n)
    return nums


def parse_equity_table(df: pd.DataFrame) -> List[Dict]:
    """
    NSDL Equity columns (typical):
      0: ISIN / Symbol   1: Company Name   2: Face Value
      3: Shares          4: Price          5: Value
    Strategy: locate ISIN by regex in any cell of the row, then use last two
    numeric cells as (price, value), and first integer ≤100k as quantity.
    """
    holdings = []
    for r in range(len(df)):
        row_vals = _row_values(df, r)
        row_blob = " ".join(row_vals)
        isin = _find_isin_in_text(row_blob)
        if not isin or not isin.startswith("INE"):
            continue

        # Name: first cell with alphabetic text, usually column 1
        name = ""
        for c_idx in range(df.shape[1]):
            cell = row_vals[c_idx]
            if not cell:
                continue
            # Skip cells that are the ISIN itself
            if ISIN_RE.search(cell):
                continue
            # Skip pure numeric cells
            if re.match(r'^[\d,\.\s]+$', cell):
                continue
            candidate = _clean_name(cell)
            if len(candidate) > len(name):
                name = candidate

        nums = _all_numbers_in_row(row_vals)
        # Filter: face_value appears as 1/2/5/10 — often the first small number
        face_values = {1.0, 2.0, 5.0, 10.0}
        qty = 0
        price = 0.0
        value = 0.0

        if len(nums) >= 4 and nums[0] in face_values:
            qty = int(nums[1]) if nums[1] == int(nums[1]) and nums[1] < 1000000 else 0
            price = nums[2]
            value = nums[3]
        elif len(nums) >= 3:
            # Often: shares, price, value
            if nums[0] == int(nums[0]) and nums[0] < 1000000:
                qty = int(nums[0])
            price = nums[-2]
            value = nums[-1]
        elif len(nums) >= 2:
            price = nums[-2]
            value = nums[-1]
            qty = round(value / price) if price > 0 else 0

        if value > 0 and price > 0:
            # Cross-check: shares * price ≈ value
            if qty > 0:
                exp = qty * price
                if abs(exp - value) / max(value, 1) > 0.15:
                    qty = round(value / price)
            else:
                qty = round(value / price)

        if value > 0 and name:
            holdings.append({
                "name": name, "ticker": isin, "asset_type": "equity",
                "quantity": qty, "buy_price": round(price, 2),
                "current_price": round(price, 2), "sector": "Other",
            })

    logger.info("[table] Equity: parsed %s holdings", len(holdings))
    return holdings


def parse_mf_demat_table(df: pd.DataFrame) -> List[Dict]:
    """NSDL MF Demat (M) columns: ISIN | Description | Units | NAV | Value."""
    holdings = []
    for r in range(len(df)):
        row_vals = _row_values(df, r)
        isin = _find_isin_in_text(" ".join(row_vals))
        if not isin or not isin.startswith("INF"):
            continue

        name = ""
        for cell in row_vals:
            if not cell or ISIN_RE.search(cell):
                continue
            if re.match(r'^[\d,\.\s]+$', cell):
                continue
            candidate = _clean_name(cell)
            if len(candidate) > len(name):
                name = candidate

        nums = _all_numbers_in_row(row_vals)
        units = nav = value = 0.0
        if len(nums) >= 3:
            units, nav, value = nums[-3], nums[-2], nums[-1]
        elif len(nums) == 2:
            nav, value = nums[-2], nums[-1]
            units = round(value / nav, 3) if nav > 0 else 0

        if value > 0 and name:
            asset_type = "etf" if any(k in name.lower() for k in ["etf", "bees"]) else "mutual_fund"
            holdings.append({
                "name": name, "ticker": isin, "asset_type": asset_type,
                "quantity": round(units, 4), "buy_price": round(nav, 4),
                "current_price": round(nav, 4),
                "sector": _classify_sector(name),
            })

    logger.info("[table] MF Demat: parsed %s holdings", len(holdings))
    return holdings


def parse_sgb_table(df: pd.DataFrame) -> List[Dict]:
    """NSDL SGB: ISIN | Issuer | Coupon | Maturity | FaceVal | Price | Value."""
    holdings = []
    for r in range(len(df)):
        row_vals = _row_values(df, r)
        row_blob = " ".join(row_vals)

        # Find SGB ISIN (IN00... format)
        m = re.search(r'\b(IN0[0-9A-Z]{10,11})\b', row_blob.replace("1N00", "IN00"))
        if not m:
            continue
        isin = m.group(1)

        nums = _all_numbers_in_row(row_vals)
        # Strip coupon rate (usually 2.50)
        nums = [n for n in nums if not (2.49 <= n <= 2.51)]

        # Columns: face_value (typically 10), market_price_per_unit, value
        units = 1
        face_val = market_price = value = 0.0
        if len(nums) >= 3:
            # Look for face_value ~10, and value (largest)
            face_val = nums[0] if nums[0] in (1.0, 10.0) else 10.0
            market_price = nums[-2]
            value = nums[-1]
            units = round(value / market_price) if market_price > 0 else 1
        elif len(nums) == 2:
            market_price = nums[0]
            value = nums[1]
            units = round(value / market_price) if market_price > 0 else 1

        maturity = re.search(r'(\d{2}-[A-Za-z]{3}-\d{4})', row_blob)
        name = f"Sovereign Gold Bond (Maturity: {maturity.group(1)})" if maturity else "Sovereign Gold Bond"

        if value > 0:
            holdings.append({
                "name": name, "ticker": isin, "asset_type": "gold",
                "quantity": units if units > 0 else 1,
                "buy_price": round(face_val, 2) if face_val > 0 else round(market_price, 2),
                "current_price": round(market_price, 2) if market_price > 0 else round(value, 2),
                "sector": "Gold",
            })

    logger.info("[table] SGB: parsed %s holdings", len(holdings))
    return holdings


def parse_mf_folio_table(df: pd.DataFrame) -> List[Dict]:
    """
    NSDL MF Folios columns (10):
      ISIN | Description | Folio | Units | Avg Cost | Total Cost | NAV | Current Value | Unrealised | Return%

    Uses AMFI masterdata NAV as an anchor when available: identifies the NAV
    column by proximity to the real-world NAV, which unambiguously locates
    units, total_cost, and current_value.
    """
    from services.masterdata import lookup_isin
    holdings = []
    for r in range(len(df)):
        row_vals = _row_values(df, r)
        row_blob = " ".join(row_vals)
        isin = _find_isin_in_text(row_blob)
        if not isin or not (isin.startswith("INF") or isin.startswith("INE")):
            continue

        # Name: the description cell (longest alpha cell)
        name = ""
        for cell in row_vals:
            if not cell or ISIN_RE.search(cell):
                continue
            if re.match(r'^[\d,\.\s/]+$', cell):
                continue
            candidate = _clean_name(cell)
            if re.match(r'^\d+$', candidate):
                continue
            if len(candidate) > len(name):
                name = candidate

        nums = _all_numbers_in_row(row_vals)
        # Filter folio-like large integers (7+ digit pure ints)
        filtered = [n for n in nums if not (n == int(n) and n > 10000000)]
        if len(filtered) < 3:
            continue

        # Masterdata NAV anchor
        master = lookup_isin(isin)
        master_nav = master.get("price", 0) if master else 0

        units = avg_cost = nav = value = 0.0

        if master_nav > 0:
            # Find the filtered number closest to master_nav — that's the NAV column.
            nav_idx = min(
                range(len(filtered)),
                key=lambda i: abs(filtered[i] - master_nav) / max(master_nav, 1)
            )
            candidate_nav = filtered[nav_idx]
            # Only accept if within 20% of master
            if abs(candidate_nav - master_nav) / max(master_nav, 1) < 0.20:
                nav = candidate_nav
                # Current Value is typically the column right after NAV, and is the
                # largest number in the row (units * nav).
                # Pick the number after nav_idx with (value / nav) giving a sane units count.
                best_val = 0
                best_units = 0
                for i in range(len(filtered)):
                    if i == nav_idx:
                        continue
                    v = filtered[i]
                    if v < nav * 0.5:  # too small to be current_value
                        continue
                    u = v / nav
                    # Sane units range: 0.001 to 10,000,000
                    if 0.001 < u < 10_000_000 and v > best_val:
                        best_val = v
                        best_units = u
                if best_val > 0:
                    value = best_val
                    units = best_units
                    # avg_cost: smallest remaining number > 1 and < nav*3
                    for v in filtered:
                        if v == nav or v == value:
                            continue
                        if 1 < v < nav * 3:
                            avg_cost = v
                            break

        # Fallback: positional parsing (original logic)
        if value == 0:
            if len(filtered) >= 5:
                units = filtered[0]
                avg_cost = filtered[1]
                nav = filtered[3]
                value = filtered[4]
                if units > 0 and nav > 0:
                    expected = units * nav
                    if abs(expected - value) / max(value, 1) > 0.1:
                        for u_c in [units, units / 1000]:
                            if abs(u_c * nav - value) / max(value, 1) < 0.05:
                                units = u_c
                                break
                        else:
                            units = value / nav if nav > 0 else units
            elif len(filtered) >= 3:
                units = filtered[0]
                nav = filtered[-2]
                value = filtered[-1]
                avg_cost = nav

        # Final sanity check: NAV must be reasonable (< 100k for any real MF)
        if nav <= 0 or nav > 100_000 or value <= 0:
            continue
        # Reject clearly broken rows where master_nav is known and parsed NAV is far off
        if master_nav > 0 and abs(nav - master_nav) / master_nav > 0.25:
            continue

        if name and len(name) >= 3:
            holdings.append({
                "name": name, "ticker": isin, "asset_type": "mutual_fund",
                "quantity": round(units, 4),
                "buy_price": round(avg_cost, 4) if avg_cost > 0 else round(nav, 4),
                "current_price": round(nav, 4),
                "sector": _classify_sector(name),
            })

    logger.info("[table] MF Folios: parsed %s holdings", len(holdings))
    return holdings


def parse_cdsl_equity_table(df: pd.DataFrame) -> List[Dict]:
    """
    CDSL Equity columns (typical):
      ISIN | Security | Current Qty | Frozen | Pledge | Setup | FreeBal | Price | Value
    Last 2 numeric cells are always (price, value).
    """
    holdings = []
    for r in range(len(df)):
        row_vals = _row_values(df, r)
        row_blob = " ".join(row_vals)
        isin = _find_isin_in_text(row_blob)
        if not isin:
            continue

        name = ""
        for cell in row_vals:
            if not cell or ISIN_RE.search(cell):
                continue
            if re.match(r'^[\d,\.\s]+$', cell):
                continue
            cand = _clean_name(re.sub(r'#?\s*EQUITY\s+SHARES?.*', '', cell, flags=re.IGNORECASE))
            cand = re.sub(r'\b(LIMITED|LTD|FORMERLY|PRIVATE|FV)\b', '', cand, flags=re.IGNORECASE).strip()
            if len(cand) > len(name):
                name = cand

        nums = _all_numbers_in_row(row_vals)
        if len(nums) < 2:
            continue
        value = nums[-1]
        price = nums[-2]
        qty = 0
        if price > 0:
            qty = round(value / price)
        if len(nums) >= 3 and nums[0] == int(nums[0]) and nums[0] < 100000:
            exp = nums[0] * price
            if abs(exp - value) / max(value, 1) < 0.05:
                qty = int(nums[0])

        asset_type = "etf" if any(k in (name + row_blob).lower() for k in ["etf", "bees"]) else "equity"
        if 0 < value < 10000000 and name and len(name) > 1:
            holdings.append({
                "name": name, "ticker": isin, "asset_type": asset_type,
                "quantity": qty, "buy_price": round(price, 2),
                "current_price": round(price, 2),
                "sector": _classify_sector(name) if asset_type != "equity" else "Other",
            })

    logger.info("[table] CDSL Equity: parsed %s holdings", len(holdings))
    return holdings


def parse_cdsl_mf_folio_table(df: pd.DataFrame) -> List[Dict]:
    """CDSL MF Folios: ISIN or Scheme | Folio | Units | NAV | Invested | Valuation | PnL | PnL%."""
    holdings = []
    for r in range(len(df)):
        row_vals = _row_values(df, r)
        row_blob = " ".join(row_vals)
        isin = _find_isin_in_text(row_blob)
        if not isin or not isin.startswith("INF"):
            continue

        name = ""
        for cell in row_vals:
            if not cell or ISIN_RE.search(cell):
                continue
            if re.match(r'^[\d,\.\s/]+$', cell):
                continue
            cand = _clean_name(cell)
            if re.match(r'^\d+$', cand):
                continue
            if len(cand) > len(name):
                name = cand

        nums = _all_numbers_in_row(row_vals)
        filtered = [n for n in nums if not (n == int(n) and n > 10000000)]

        units = nav = invested = value = 0.0
        if len(filtered) >= 4:
            units, nav, invested, value = filtered[0], filtered[1], filtered[2], filtered[3]
            if units > 0 and nav > 0:
                expected = units * nav
                if abs(expected - value) / max(value, 1) > 0.1:
                    for u_c in [units, units / 1000]:
                        if abs(u_c * nav - value) / max(value, 1) < 0.05:
                            units = u_c
                            break
                    else:
                        units = value / nav if nav > 0 else units
        elif len(filtered) >= 2:
            nav = filtered[0]
            value = filtered[1]
            units = value / nav if nav > 0 else 0

        if value > 0 and name and len(name) >= 3:
            holdings.append({
                "name": name, "ticker": isin, "asset_type": "mutual_fund",
                "quantity": round(units, 4),
                "buy_price": round(invested / units, 4) if units > 0 and invested > 0 else round(nav, 4),
                "current_price": round(nav, 4),
                "sector": _classify_sector(name),
            })

    logger.info("[table] CDSL MF Folios: parsed %s holdings", len(holdings))
    return holdings


# ══════════════════════════════════════════════════════════════
# Top-level entry
# ══════════════════════════════════════════════════════════════

def extract_tables_from_image(pil_image, n_threads: int = 4) -> list:
    """Extract all tables from a single page PIL image using img2table + Tesseract."""
    from img2table.document import Image as Img2TImage
    from img2table.ocr import TesseractOCR

    buf = io.BytesIO()
    pil_image.save(buf, format='PNG')
    buf.seek(0)
    doc = Img2TImage(src=buf)
    ocr = TesseractOCR(n_threads=n_threads, lang='eng')
    try:
        tables = doc.extract_tables(
            ocr=ocr,
            implicit_rows=True,
            implicit_columns=False,
            borderless_tables=True,
            min_confidence=50,
        )
        return tables
    except Exception as e:
        logger.warning("img2table extract failed: %s", e)
        return []


def parse_pages_via_tables(pil_images: list) -> List[Dict]:
    """Extract tables from each page, classify, and parse holdings."""
    all_holdings: List[Dict] = []
    for page_idx, img in enumerate(pil_images):
        try:
            tables = extract_tables_from_image(img)
        except Exception as e:
            logger.warning("Page %s table extract error: %s", page_idx+1, e)
            continue

        if not tables:
            continue

        logger.info("Page %s: %s tables found", page_idx+1, len(tables))
        for tbl_idx, tbl in enumerate(tables):
            df = tbl.df
            if df.empty or df.shape[0] < 2:
                continue
            kind = classify_table(df)
            logger.info("  Table %s: %s kind=%s", tbl_idx, df.shape, kind)

            if kind == 'equity':
                all_holdings.extend(parse_equity_table(df))
            elif kind == 'mf_demat':
                all_holdings.extend(parse_mf_demat_table(df))
            elif kind == 'sgb':
                all_holdings.extend(parse_sgb_table(df))
            elif kind == 'mf_folio':
                all_holdings.extend(parse_mf_folio_table(df))
            elif kind == 'cdsl_equity':
                all_holdings.extend(parse_cdsl_equity_table(df))
            elif kind == 'cdsl_mf_folio':
                all_holdings.extend(parse_cdsl_mf_folio_table(df))

    return all_holdings
