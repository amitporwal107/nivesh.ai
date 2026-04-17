"""
Local CAS Parser — Zero cloud dependency.
Handles NSDL/CDSL image-based CAS PDFs using Tesseract OCR.
For text-based CAMS/KFintech PDFs, casparser library is used (in server.py).
"""
import io
import re
import logging
from typing import List, Dict
from PIL import Image, ImageEnhance

logger = logging.getLogger("cas_parser")

ISIN_RE = re.compile(r'\b(IN[A-Z0-9]{10})\b')
# Broader pattern to catch OCR-garbled ISINs (O/0, I/1, S/5 confusion)
ISIN_BROAD_RE = re.compile(r'\b([I1][NM][A-Z0-9OoSs]{10,11})\b')
SGB_ISIN_RE = re.compile(r'\b([I1]N\d{10,13})\b')  # OCR reads IN as 1N
NUM_RE = re.compile(r'[\d,]+\.?\d*')

# OCR character correction map for ISINs
# Position-aware: ISIN format is IN + F/E + 3 chars (AMC) + 2 digits + 4 chars + check
ISIN_OCR_MAP = str.maketrans({
    'O': '0', 'o': '0',  # O → 0 (most common in digit positions)
    'S': '5',             # S → 5
    'l': '1',             # l → 1
    'I': '1',             # I → 1 (only in digit positions, handled carefully)
    'B': '8',             # B → 8
    'Z': '2',             # Z → 2
    'G': '6',             # G → 6
})


def fix_isin_ocr(raw: str) -> str:
    """Fix common OCR errors in ISINs using position-aware correction."""
    if len(raw) < 12:
        return raw

    chars = list(raw)

    # Fix prefix: must be "IN"
    if chars[0] in ('1', 'i', '|', 'l'):
        chars[0] = 'I'
    if chars[1] in ('M', 'm'):
        chars[1] = 'N'

    # Position 2: E (equity) or F (mutual fund) — keep as letter
    # Positions 3-5: could be digits or letters (AMC code)
    # Positions 6-11: mostly digits, some letters

    # Apply position-aware corrections
    for i in range(3, len(chars)):
        ch = chars[i]
        # In digit-heavy positions (3,4,6,7,8,9,10,11), fix letter→digit
        if ch == 'O' or ch == 'o':
            chars[i] = '0'
        elif ch == 'S' and i >= 6:
            chars[i] = '5'
        elif ch == 'l' and i >= 6:
            chars[i] = '1'
        elif ch == 'I' and i >= 6:
            # Letter 'I' in a digit-heavy position is almost always OCR of '1'.
            # Only convert when flanked by digits (e.g. "M0INI0" → "M01NI0").
            prev_c = chars[i - 1] if i > 0 else ''
            next_c = chars[i + 1] if i + 1 < len(chars) else ''
            if prev_c.isdigit() or (next_c.isdigit() and i >= 7):
                chars[i] = '1'
        elif ch == 'B' and i >= 9:
            chars[i] = '8'
        elif ch == 'Z' and i >= 6:
            chars[i] = '2'
        elif ch == 'G' and i >= 9:
            chars[i] = '6'

    result = "".join(chars[:12])
    return result

# Table header patterns for precise section detection
EQUITY_HEADER = re.compile(
    r'(?:ISIN\s+(?:Stock\s+Symbol\s+)?Company\s+Name\s+Face\s+Value'
    r'|Equit(?:y|ies)\s+\(E\)\s*\n?\s*(?:Equity\s+Shares\s*\n?\s*)?Company\s+Name'
    r'|Equity\s+Shares\s*\n?\s*Company\s+Name\s+Face\s+Value)',
    re.IGNORECASE
)
MF_M_HEADER = re.compile(r'ISIN\s+(?:ISIN\s+)?Description\s+(?:No\.\s+of\s+)?NAV\s+Value', re.IGNORECASE)
SGB_HEADER = re.compile(r'Sovereign\s+Gold\s+Bonds?\s*\(SGB\)', re.IGNORECASE)
MF_FOLIO_HEADER = re.compile(r'ISIN\s+(?:ISIN\s+)?Description\s+Folio\s+No', re.IGNORECASE)
SUB_TOTAL_RE = re.compile(r'Sub\s+Total', re.IGNORECASE)
TRANSACTION_MARKER = re.compile(r'ISIN\s*:\s*IN[A-Z0-9]|Transaction\s+Statement', re.IGNORECASE)


def parse_num(s: str) -> float:
    try:
        return float(s.replace(",", ""))
    except (ValueError, AttributeError):
        return 0.0


def extract_all_numbers(text: str) -> List[float]:
    return [parse_num(m) for m in NUM_RE.findall(text) if parse_num(m) > 0]


def ocr_page(img: Image.Image) -> str:
    import pytesseract
    gray = img.convert('L')
    enhancer = ImageEnhance.Contrast(gray)
    enhanced = enhancer.enhance(1.8)
    return pytesseract.image_to_string(enhanced, lang='eng', config='--oem 3 --psm 4')


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


def _extract_section(full_text: str, start_pattern, end_patterns: list) -> str:
    """Extract text between start pattern and the first matching end pattern."""
    m = start_pattern.search(full_text)
    if not m:
        return ""
    start = m.end()
    end = len(full_text)
    for ep in end_patterns:
        em = ep.search(full_text[start:])
        if em:
            end = min(end, start + em.start())
    return full_text[start:end]


def parse_equities(text: str) -> List[Dict]:
    """Parse equities: ISIN COMPANY FACE_VAL SHARES MARKET_PRICE VALUE"""
    holdings = []
    lines = text.split('\n')
    i = 0
    while i < len(lines):
        line = lines[i].strip()
        m = ISIN_RE.search(line)
        if m and m.group(1).startswith("INE"):
            isin = fix_isin_ocr(m.group(1))
            raw_match = m.group(1)
            # Collect lines until next ISIN, Sub Total, or Mutual Funds
            block = line
            j = i + 1
            while j < len(lines):
                nl = lines[j].strip()
                if ISIN_RE.search(nl) or SUB_TOTAL_RE.search(nl) or 'Mutual Fund' in nl:
                    break
                block += " " + nl
                j += 1

            # Clean: remove pledged info, stock symbols
            block_clean = re.sub(r'of which Pledged.*?(?=\d|$)', '', block, flags=re.IGNORECASE)
            block_clean = re.sub(r'[A-Z]{3,}\.(NSE|BSE)', '', block_clean)
            block_clean = re.sub(r'Pledge\b', '', block_clean, flags=re.IGNORECASE)

            after = block_clean[block_clean.index(raw_match) + len(raw_match):]
            nums = extract_all_numbers(after)

            # Name: text before first number
            first_num = NUM_RE.search(after)
            name = after[:first_num.start()].strip() if first_num else after.strip()
            name = re.sub(r'[^\w\s&\-\(\)]', '', name).strip()
            name = re.sub(r'\s+', ' ', name).strip()

            if not name or len(name) < 2:
                i = j
                continue

            # Pattern: face_value(1/2/5/10), shares(int), market_price, value
            shares = 0
            price = 0.0
            value = 0.0

            # Filter numbers: face_value is always 1.0, 2.0, 5.0, or 10.0
            face_values = {1.0, 2.0, 5.0, 10.0}
            if len(nums) >= 4 and nums[0] in face_values:
                shares = int(nums[1])
                price = nums[2]
                value = nums[3]
            elif len(nums) >= 3:
                # No face value, or it was skipped
                shares = int(nums[0]) if nums[0] == int(nums[0]) and nums[0] < 100000 else 0
                price = nums[1]
                value = nums[2]
            elif len(nums) >= 2:
                price = nums[0]
                value = nums[1]
                shares = round(value / price) if price > 0 else 0

            # Validate shares * price ≈ value
            if shares > 0 and price > 0 and value > 0:
                expected = shares * price
                if abs(expected - value) / max(value, 1) > 0.15:
                    shares = round(value / price)

            if value > 0 or (shares == 0 and price > 0):
                holdings.append({
                    "name": name, "ticker": isin, "asset_type": "equity",
                    "quantity": shares, "buy_price": round(price, 2),
                    "current_price": round(price, 2), "sector": "Other",
                })
            i = j
        else:
            i += 1

    logger.info(f"Equities: parsed {len(holdings)} holdings")
    return holdings


def parse_mf_demat(text: str) -> List[Dict]:
    """Parse Mutual Funds (M) — demat ETFs: ISIN, Description, Units, NAV, Value"""
    holdings = []
    lines = text.split('\n')
    i = 0
    while i < len(lines):
        line = lines[i].strip()
        m = ISIN_RE.search(line)
        if m and m.group(1).startswith("INF"):
            isin = fix_isin_ocr(m.group(1))
            raw_match = m.group(1)
            block = line
            j = i + 1
            while j < len(lines):
                nl = lines[j].strip()
                if ISIN_RE.search(nl) or SUB_TOTAL_RE.search(nl) or SGB_HEADER.search(nl):
                    break
                block += " " + nl
                j += 1

            block_clean = re.sub(r'of which Pledged.*', '', block, flags=re.IGNORECASE)
            after = block_clean[block_clean.index(raw_match) + len(raw_match):]
            nums = extract_all_numbers(after)

            first_num = NUM_RE.search(after)
            name = after[:first_num.start()].strip() if first_num else after.strip()
            name = re.sub(r'[^\w\s&\-\(\)\+]', '', name).strip()

            units = 0.0
            nav = 0.0
            value = 0.0
            if len(nums) >= 3:
                units = nums[-3]
                nav = nums[-2]
                value = nums[-1]
            elif len(nums) >= 2:
                nav = nums[-2]
                value = nums[-1]
                units = round(value / nav, 3) if nav > 0 else 0
            elif len(nums) == 1:
                # Only value found (units missing from OCR — e.g., "." instead of number)
                value = nums[0]

            # Validate
            if units > 0 and nav > 0 and value > 0:
                expected = units * nav
                if abs(expected - value) / max(value, 1) > 0.2:
                    units = round(value / nav, 3) if nav > 0 else units

            # If units missing but value exists, try to recover from masterdata
            if value > 0 and units == 0 and isin:
                from services.masterdata import lookup_isin
                master = lookup_isin(isin)
                if master and master.get("price", 0) > 0:
                    nav = master["price"]
                    units = round(value / nav, 4)

            if value > 0 and name:
                holdings.append({
                    "name": name, "ticker": isin,
                    "asset_type": "etf" if any(k in name.lower() for k in ["etf", "bees"]) else "mutual_fund",
                    "quantity": round(units, 4), "buy_price": round(nav, 4),
                    "current_price": round(nav, 4), "sector": _classify_sector(name),
                })
            i = j
        else:
            i += 1

    logger.info(f"MF Demat: parsed {len(holdings)} holdings")
    return holdings


def parse_sgb(text: str) -> List[Dict]:
    """Parse Sovereign Gold Bonds: ISIN, Units, Face Value, Market Price, Value"""
    holdings = []
    lines = text.split('\n')
    i = 0
    while i < len(lines):
        line = lines[i].strip()
        m = SGB_ISIN_RE.search(line)
        if m:
            isin = m.group(1)
            # Fix OCR: 1N → IN
            if isin.startswith("1N"):
                isin = "IN" + isin[2:]
            block = line
            j = i + 1
            while j < len(lines):
                nl = lines[j].strip()
                if SGB_ISIN_RE.search(nl) or SUB_TOTAL_RE.search(nl):
                    break
                block += " " + nl
                j += 1

            nums = extract_all_numbers(block)
            # Remove numbers that are part of the ISIN and coupon rate (2.50)
            # Get numbers only from text AFTER the ISIN
            after_isin = block[block.index(m.group(0)) + len(m.group(0)):]
            nums = extract_all_numbers(after_isin)
            nums = [n for n in nums if not (2.49 <= n <= 2.51)]

            units = 0
            face_value = 0.0
            market_price = 0.0
            value = 0.0

            if len(nums) >= 4:
                units = int(nums[0]) if nums[0] < 1000 else 0
                face_value = nums[1]
                market_price = nums[2]
                value = nums[3]
            elif len(nums) >= 3:
                units = int(nums[0]) if nums[0] < 1000 else 0
                market_price = nums[1]
                value = nums[2]

            # Validate
            if units > 0 and market_price > 0 and value > 0:
                expected = units * market_price
                if abs(expected - value) / max(value, 1) > 0.15:
                    units = round(value / market_price) if market_price > 0 else units

            maturity = re.search(r'(\d{2}-\w{3}-\d{4})', block)
            name = f"Sovereign Gold Bond (Maturity: {maturity.group(1)})" if maturity else "Sovereign Gold Bond"

            if value > 0:
                holdings.append({
                    "name": name, "ticker": isin, "asset_type": "gold",
                    "quantity": units if units > 0 else 1,
                    "buy_price": round(face_value, 2) if face_value > 0 else round(market_price, 2),
                    "current_price": round(market_price, 2) if market_price > 0 else round(value, 2),
                    "sector": "Gold",
                })
            i = j
        else:
            i += 1

    logger.info(f"SGB: parsed {len(holdings)} holdings")
    return holdings


def parse_mf_folios(text: str) -> List[Dict]:
    """Parse MF Folios: ISIN, Desc, Folio, Units, Avg Cost, Total Cost, NAV, Current Value, PnL, Return"""
    holdings = []
    lines = text.split('\n')

    # First, find all ISIN positions and collect their full data blocks
    isin_blocks = []
    i = 0
    while i < len(lines):
        line = lines[i].strip()
        m = ISIN_RE.search(line)
        if m and (m.group(1).startswith("INF") or m.group(1).startswith("INE")):
            # Collect numbers from up to 3 non-empty lines BEFORE this ISIN
            pre_nums = []
            for k in range(max(0, i-3), i):
                prev = lines[k].strip()
                if prev and not ISIN_RE.search(prev) and not SUB_TOTAL_RE.search(prev):
                    pn = extract_all_numbers(prev)
                    # Only include standalone numbers (not part of text)
                    if pn and len(prev) < 30:
                        pre_nums.extend(pn)
            isin_blocks.append({"isin": fix_isin_ocr(m.group(1)), "raw_isin": m.group(1), "start": i, "lines": [line], "pre_nums": pre_nums})
        elif isin_blocks:
            isin_blocks[-1]["lines"].append(line)
        i += 1

    for block in isin_blocks:
        isin = block["isin"]
        raw_isin = block.get("raw_isin", isin)
        full_text = " ".join(l for l in block["lines"] if l.strip())
        # Remove MF UCC codes and noise
        full_text = re.sub(r'MF[A-Z0-9]{5,}', '', full_text)
        full_text = re.sub(r'NOT AVAILABLE', '', full_text)

        after = full_text[full_text.index(raw_isin) + len(raw_isin):]

        # Find folio number (8-12 digits)
        folio_match = re.search(r'\b(\d{8,12})\b', after)
        if folio_match:
            name = after[:folio_match.start()].strip()
            numbers_text = after[folio_match.end():]
        else:
            first_num = NUM_RE.search(after)
            name = after[:first_num.start()].strip() if first_num else after.strip()
            numbers_text = after[first_num.start():] if first_num else ""

        # Clean name
        name = re.sub(r'[^\w\s&\-\(\)/]', '', name).strip()
        name = re.sub(r'\s+', ' ', name).strip()
        name = re.sub(r'^[\s_\-=]+', '', name).strip()

        # Extract ALL numbers from the block
        nums = extract_all_numbers(numbers_text)
        # Prepend any numbers from previous line (NAV bleeding from OCR layout)
        if block.get("pre_nums"):
            nums = block["pre_nums"] + nums
        # Filter out folio-like large integers
        filtered = [n for n in nums if not (n == int(n) and n > 10000000)]

        # Pattern: units, avg_cost, total_cost, nav, value, pnl[, return%]
        # Use value-anchored approach with OCR decimal/comma error correction
        units = 0.0
        avg_cost = 0.0
        nav = 0.0
        value = 0.0

        if len(filtered) >= 5:
            units = filtered[0]
            avg_cost = filtered[1]
            total_cost = filtered[2]
            nav = filtered[3]
            value = filtered[4]

            # Validate: units * nav ≈ value
            if units > 0 and nav > 0:
                expected = units * nav
                if abs(expected - value) / max(value, 1) > 0.1:
                    # OCR may have confused decimal/comma. Try /1000 variants.
                    best_err = float('inf')
                    best = (units, avg_cost, nav, value)
                    best_value_size = 0
                    for vi in range(2, min(len(filtered), 7)):
                        v_c = filtered[vi]
                        if v_c < 100 or v_c > 10000000:
                            continue
                        for ni in range(min(len(filtered), 7)):
                            if ni == vi:
                                continue
                            n_c = filtered[ni]
                            if n_c < 1 or n_c > 100000:
                                continue
                            for ui in range(min(len(filtered), 7)):
                                if ui in (vi, ni):
                                    continue
                                for u_c in [filtered[ui], filtered[ui] / 1000]:
                                    if u_c <= 0:
                                        continue
                                    err = abs(u_c * n_c - v_c) / max(v_c, 1)
                                    if err < 0.05:
                                        # Prefer the combo with the LARGEST value
                                        # (current_value > total_cost in most cases)
                                        if v_c > best_value_size or (v_c == best_value_size and err < best_err):
                                            best_err = err
                                            best_value_size = v_c
                                            a = avg_cost
                                            for ai in range(min(len(filtered), 7)):
                                                if ai not in (vi, ni, ui) and 1 < filtered[ai] < 100000:
                                                    a = filtered[ai]
                                                    break
                                            best = (u_c, a, n_c, v_c)
                    if best_err < 0.1:
                        units, avg_cost, nav, value = best
        elif len(filtered) >= 3:
            units = filtered[0]
            nav = filtered[1]
            value = filtered[2]
            avg_cost = nav

        if value > 0 and name and len(name) > 3:
            holdings.append({
                "name": name, "ticker": isin, "asset_type": "mutual_fund",
                "quantity": round(units, 4),
                "buy_price": round(avg_cost, 4) if avg_cost > 0 else round(nav, 4),
                "current_price": round(nav, 4),
                "sector": _classify_sector(name),
            })

    logger.info(f"MF Folios: parsed {len(holdings)} holdings")
    return holdings


# ═══════════════════════════════════════════════════════════════
# CDSL-specific parsers
# ═══════════════════════════════════════════════════════════════

CDSL_EQUITY_HEADER = re.compile(r'ISIN\s+Security\s+Current', re.IGNORECASE)
CDSL_MF_HEADER = re.compile(r'Scheme\s+Name\s+Folio\s+No.*?(?:Bal|NAV)', re.IGNORECASE)
CDSL_MF_HELD = re.compile(r'FUND\s+UNITS\s+HELD\s+(?:AS\s+ON|WITH)', re.IGNORECASE)


def parse_cdsl_equities(text: str) -> List[Dict]:
    """Parse CDSL equity holdings. Last 2 numbers per entry are always (price, value)."""
    holdings = []
    lines = text.split('\n')
    i = 0
    while i < len(lines):
        line = lines[i].strip()
        m = ISIN_RE.search(line)
        if m:
            isin = fix_isin_ocr(m.group(1))
            block = line
            j = i + 1
            while j < len(lines):
                nl = lines[j].strip()
                if ISIN_RE.search(nl) or 'Page' in nl or CDSL_EQUITY_HEADER.search(nl):
                    break
                block += " " + nl
                j += 1

            after = block[block.index(m.group(1)) + len(m.group(1)):]
            # Strip security description noise: "EQUITY SHARES OF RE/RS.1/- EACH" etc
            after_clean = re.sub(r'#?\s*EQUITY\s+SHARES?\s+(?:OF\s+)?R[SE]\.?\s*[\d/\-]+\s*(?:EACH|AFTER|WITH|NEW|SUB|SPLIT|CAPITAL|REDUCTION|HAVING|PREMIUM)?[^0-9]*', ' ', after, flags=re.IGNORECASE)
            after_clean = re.sub(r'LIMITED|FORMERLY|PRIVATE|FV', ' ', after_clean, flags=re.IGNORECASE)

            # Name: text before first digit cluster in cleaned version
            first_num = re.search(r'\d', after_clean)
            name = after_clean[:first_num.start()].strip() if first_num else after_clean.strip()
            name = re.sub(r'[^\w\s&\-\(\)]', '', name).strip()
            name = re.sub(r'\s+', ' ', name).strip()

            # Also try getting a cleaner name from original text
            orig_name = re.search(r'([A-Z][A-Z\s&\-]+?)(?:\s*#|\s*EQUITY|\s+\d)', after)
            if orig_name and len(orig_name.group(1).strip()) > len(name):
                name = orig_name.group(1).strip()

            nums = extract_all_numbers(after_clean)
            # CDSL format: [qty_current, frozen, pledge, pledge_setup, free_bal, price, value]
            # Key insight: LAST 2 numbers are always (price, value)
            price = 0.0
            value = 0.0
            qty = 0

            if len(nums) >= 2:
                value = nums[-1]
                price = nums[-2]
                # Qty: calculate from value/price for reliability
                if price > 0:
                    qty = round(value / price)
                # Cross-check: first number is often total qty
                if len(nums) >= 3 and nums[0] == int(nums[0]) and nums[0] < 100000:
                    expected_val = nums[0] * price
                    if abs(expected_val - value) / max(value, 1) < 0.05:
                        qty = int(nums[0])

            asset_type = "etf" if any(k in (name + after).lower() for k in ["etf", "bees", "liquid"]) else "equity"
            if value > 0 and value < 10000000 and name and len(name) > 1:
                holdings.append({
                    "name": name, "ticker": isin, "asset_type": asset_type,
                    "quantity": qty, "buy_price": round(price, 2),
                    "current_price": round(price, 2),
                    "sector": _classify_sector(name) if asset_type != "equity" else "Other",
                })
            i = j
        else:
            i += 1

    logger.info(f"CDSL Equities: parsed {len(holdings)} holdings")
    return holdings


def parse_cdsl_mf_folios(text: str) -> List[Dict]:
    """Parse CDSL MF Folios. ISINs may be garbled (NF instead of INF, O instead of 0)."""
    holdings = []
    # CDSL MF ISINs: sometimes missing leading 'I', 'O' instead of '0', pipe prefix
    cdsl_isin_re = re.compile(r'[|]?\s*[I1|]?(NF[A-Z0-9O]{8,11})\b')
    lines = text.split('\n')
    i = 0
    while i < len(lines):
        line = lines[i].strip()
        m = cdsl_isin_re.search(line)
        if m:
            raw_isin = m.group(1)
            # Fix OCR: ensure starts with INF, fix common OCR errors
            isin = raw_isin if raw_isin.startswith("INF") else "I" + raw_isin
            isin = fix_isin_ocr(isin)

            # Collect lines for this entry
            block = line
            j = i + 1
            while j < len(lines):
                nl = lines[j].strip()
                nm = cdsl_isin_re.search(nl)
                if nm and nm.start() < 20:
                    break
                if 'Grand Total' in nl or 'Page' in nl:
                    break
                block += " " + nl
                j += 1

            # Extract numbers after ISIN
            after = block[block.index(m.group(0)) + len(m.group(0)):]
            # Remove folio numbers with / separator
            after = re.sub(r'\d{7,}/\d+', '', after)
            after = re.sub(r'\|', ' ', after)  # Clean pipe chars from OCR

            nums = extract_all_numbers(after)
            # Filter out folio-like large integers
            filtered = [n for n in nums if not (n == int(n) and n > 10000000)]

            # CDSL MF: units, nav, invested, valuation, pnl, pnl%
            units = 0.0
            nav = 0.0
            invested = 0.0
            value = 0.0

            if len(filtered) >= 4:
                units = filtered[0]
                nav = filtered[1]
                invested = filtered[2]
                value = filtered[3]
                # Validate
                if units > 0 and nav > 0:
                    expected = units * nav
                    if abs(expected - value) / max(value, 1) > 0.1:
                        # Try /1000 fix for decimal→comma OCR error
                        for u in [filtered[0], filtered[0] / 1000]:
                            exp = u * nav
                            if abs(exp - value) / max(value, 1) < 0.05:
                                units = u
                                break
                        else:
                            # Fallback: calc units from value/nav
                            if nav > 0:
                                units = value / nav
            elif len(filtered) >= 2:
                nav = filtered[0]
                value = filtered[1]
                units = value / nav if nav > 0 else 0

            # Get name from the few lines before the ISIN in the text
            name = ""
            for k in range(max(0, i - 5), i + 1):
                l = lines[k].strip()
                if not cdsl_isin_re.search(l) and not re.match(r'^\d', l) and len(l) > 3:
                    # Could be fund name
                    candidate = re.sub(r'[^\w\s&\-\(\)/]', '', l).strip()
                    if len(candidate) > len(name) and any(c.isalpha() for c in candidate):
                        name = candidate

            if not name:
                name = isin  # Fallback

            if value > 0:
                holdings.append({
                    "name": name, "ticker": isin, "asset_type": "mutual_fund",
                    "quantity": round(units, 4),
                    "buy_price": round(invested / units, 4) if units > 0 and invested > 0 else round(nav, 4),
                    "current_price": round(nav, 4),
                    "sector": _classify_sector(name),
                })
            i = j
        else:
            i += 1

    logger.info(f"CDSL MF Folios: parsed {len(holdings)} holdings")
    return holdings


def parse_nsdl_cas_image(content: bytes, password: str = "") -> List[Dict]:
    """Parse image-based NSDL/CDSL CAS PDF using local Tesseract OCR.
    Smart page selection: only OCR summary + holdings pages, skip transactions/KYC/disclaimers."""
    from pdf2image import convert_from_bytes
    import pytesseract

    kwargs = {"dpi": 200}
    if password:
        kwargs["userpw"] = password

    try:
        images = convert_from_bytes(content, **kwargs)
    except Exception as e:
        logger.error(f"PDF to image conversion failed: {e}")
        return []

    total_pages = len(images)
    logger.info(f"CAS PDF: {total_pages} pages")

    # ── Phase 1: Quick scan first 2 pages (low DPI) to detect CAS type + summary ──
    scan_texts = []
    for i in range(min(3, total_pages)):
        scan_texts.append(ocr_page(images[i]))

    scan_combined = "\n".join(scan_texts)
    is_cdsl = len(re.findall(r'C\s*D\s*S\s*L', scan_combined)) > 2
    cas_type = "CDSL" if is_cdsl else "NSDL"
    logger.info(f"Detected CAS type: {cas_type}")

    # Extract summary totals from first 2-3 pages
    summary = _extract_summary(scan_combined, cas_type)
    logger.info(f"Summary: {summary}")

    # ── Phase 2: Identify holdings pages ──
    holdings_pages = []
    for i in range(total_pages):
        if i < len(scan_texts):
            text = scan_texts[i]
        else:
            # Quick scan: OCR at lower DPI for speed, full page for accuracy
            from pdf2image import convert_from_bytes as cfb_quick
            quick_imgs = cfb_quick(content, dpi=100, first_page=i+1, last_page=i+1, **({} if not password else {"userpw": password}))
            text = ocr_page(quick_imgs[0]) if quick_imgs else ""

        is_holdings_page = _is_holdings_page(text, cas_type, i)
        if is_holdings_page:
            holdings_pages.append(i)

    logger.info(f"Holdings pages identified: {[p+1 for p in holdings_pages]} (of {total_pages})")

    # ── Phase 3: OCR holdings pages at TWO DPI levels (200 + 300) for maximum recall.
    # Different DPIs catch different rows depending on font density / page noise.
    page_texts_200 = {i: ocr_page(images[i]) for i in holdings_pages}
    hires_images: Dict[int, "Image.Image"] = {}
    page_texts_300 = {}
    try:
        hires_kwargs = {"dpi": 300}
        if password:
            hires_kwargs["userpw"] = password
        for p in holdings_pages:
            hi_imgs = convert_from_bytes(content, first_page=p+1, last_page=p+1, **hires_kwargs)
            if hi_imgs:
                hires_images[p] = hi_imgs[0]
                page_texts_300[p] = ocr_page(hi_imgs[0])
    except Exception as e:
        logger.warning(f"300 DPI re-render failed: {e}")

    ordered_texts_200 = [page_texts_200[i] for i in sorted(page_texts_200.keys())]
    ordered_texts_300 = [page_texts_300[i] for i in sorted(page_texts_300.keys())] if page_texts_300 else []

    logger.info(
        f"OCR'd {len(ordered_texts_200)} pages @200DPI, {len(ordered_texts_300)} @300DPI "
        f"(skipped {total_pages - len(ordered_texts_200)} non-holdings pages)"
    )

    # ── Phase 4a: Text parse at BOTH DPIs, then union ──
    def _run_text_parse(texts):
        if cas_type == "CDSL":
            return _parse_cdsl_cas(texts)
        return _parse_nsdl_cas(texts)

    holdings_txt_200 = _run_text_parse(ordered_texts_200)
    holdings_txt_300 = _run_text_parse(ordered_texts_300) if ordered_texts_300 else []
    # Union: for each ISIN, pick the entry with non-zero qty*price; prefer 300 DPI
    # when both are valid (usually more accurate text recognition).
    def _merge_dpi(a_list, b_list):
        merged_map: Dict[str, Dict] = {}
        for h in a_list:
            tk = h.get("ticker")
            if tk:
                merged_map[tk] = h
        for h in b_list:
            tk = h.get("ticker")
            if not tk:
                continue
            if tk not in merged_map:
                merged_map[tk] = h
                continue
            va = merged_map[tk].get("quantity", 0) * merged_map[tk].get("current_price", 0)
            vb = h.get("quantity", 0) * h.get("current_price", 0)
            if va == 0 and vb > 0:
                merged_map[tk] = h
            elif vb > 0 and va > 0 and merged_map[tk].get("quantity", 0) == 0 and h.get("quantity", 0) > 0:
                merged_map[tk] = h
        return list(merged_map.values())

    holdings_txt = _merge_dpi(holdings_txt_300, holdings_txt_200)
    logger.info(
        f"Text parse union: 200DPI={len(holdings_txt_200)}, 300DPI={len(holdings_txt_300)} "
        f"→ {len(holdings_txt)} unique"
    )

    # ── Phase 4b: Supplementary parser — img2table (recovers missed rows) ──
    holdings_tbl: List[Dict] = []
    try:
        from services.cas_parser_tables import parse_pages_via_tables
        # Use hi-res images for img2table (better table detection)
        holdings_page_imgs = [hires_images.get(i) or images[i] for i in holdings_pages]
        holdings_tbl = parse_pages_via_tables(holdings_page_imgs)
        logger.info(f"img2table pass: {len(holdings_tbl)} holdings")
    except Exception as e:
        logger.warning(f"img2table pass failed ({e}); using text-only result")

    # ── Phase 4c: Merge — pick the better entry per ISIN between text & table parses
    # Rule: prefer the row with non-zero (qty × price); if both non-zero, prefer the
    # row with a non-zero quantity (text parser sometimes gets value but loses qty).
    def _best(a: dict, b: dict) -> dict:
        va = a.get("quantity", 0) * a.get("current_price", 0)
        vb = b.get("quantity", 0) * b.get("current_price", 0)
        if va == 0 and vb > 0:
            return b
        if vb == 0 and va > 0:
            return a
        # Both non-zero: prefer one with a non-zero quantity
        qa, qb = a.get("quantity", 0), b.get("quantity", 0)
        if qa == 0 and qb > 0:
            return b
        if qb == 0 and qa > 0:
            return a
        # Otherwise keep the text-parsed one (safer default)
        return a

    merged: Dict[str, Dict] = {}
    for h in holdings_txt:
        tk = h.get("ticker")
        if tk:
            merged[tk] = h
    replaced = added_from_tbl = 0
    for h in holdings_tbl:
        tk = h.get("ticker")
        if not tk:
            continue
        if tk in merged:
            best = _best(merged[tk], h)
            if best is not merged[tk]:
                merged[tk] = best
                replaced += 1
        else:
            merged[tk] = h
            added_from_tbl += 1
    holdings = list(merged.values())
    logger.info(
        f"Merged: text={len(holdings_txt)} + table={len(holdings_tbl)} → "
        f"{len(holdings)} unique (added {added_from_tbl}, replaced {replaced})"
    )

    # ── Phase 5: Apply learned OCR corrections ──
    from services.ocr_correction import apply_corrections
    holdings = apply_corrections(holdings)

    # ── Phase 6: Validate and enrich against masterdata ──
    from services.masterdata import validate_and_enrich_holdings
    holdings = validate_and_enrich_holdings(holdings)

    # ── Phase 7: Log validation against summary ──
    if summary:
        _validate_against_summary(holdings, summary)

    return holdings


def _extract_summary(text: str, cas_type: str) -> dict:
    """Extract portfolio summary totals from first pages."""
    summary = {}
    # Look for total portfolio value
    total_match = re.search(r'(?:Total\s+Portfolio\s+Value|TOTAL|Grand\s+Total)\s*[:\s]*([₹\s]?[\d,]+\.?\d*)', text, re.IGNORECASE)
    if total_match:
        summary["total"] = parse_num(total_match.group(1).replace("₹", "").strip())

    if cas_type == "NSDL":
        # NSDL sections
        for section, pattern in [
            ("equities", r'Equities?\s*\(E\)\s*([\d,]+\.?\d*)'),
            ("mf_demat", r'Mutual\s+Funds?\s*\(M\)\s*([\d,]+\.?\d*)'),
            ("sgb", r'Sovereign\s+Gold\s+Bonds?\s*\(SGB\)\s*([\d,]+\.?\d*)'),
            ("mf_folios", r'Mutual\s+Fund\s+Folios?\s*\(F\)\s*([\d,]+\.?\d*)'),
        ]:
            m = re.search(pattern, text, re.IGNORECASE)
            if m:
                summary[section] = parse_num(m.group(1))
    else:
        # CDSL sections
        demat_match = re.search(r'CDSL\s+Demat\s+Account.*?([\d,]+\.\d+)', text, re.IGNORECASE)
        if demat_match:
            summary["demat"] = parse_num(demat_match.group(1))
        mf_match = re.search(r'Mutual\s+Fund\s+Folios.*?([\d,]+\.\d+)', text, re.IGNORECASE)
        if mf_match:
            summary["mf_folios"] = parse_num(mf_match.group(1))

    return summary


def _is_holdings_page(text: str, cas_type: str, page_idx: int) -> bool:
    """Determine if a page contains holdings data."""
    if page_idx < 2:
        return True

    text_lower = text.lower()
    # Check top portion for skip markers (not footers)
    top_text = text_lower[:400]

    # Skip pages where the main content is non-holdings
    skip_in_top = ['transaction statement', 'kyc status', 'important note',
                   'you will be receiving', 'holder details']
    for marker in skip_in_top:
        if marker in top_text:
            return False

    # Skip full-page disclaimers (check if entire page is about info)
    if text_lower.count('about cdsl') > 1 or text_lower.count('about nsdl') > 1:
        return False
    if 'load structure' in top_text:
        return False

    # NSDL: Transaction pages have "ISIN : INE..." pattern
    if re.search(r'ISIN\s*:\s*IN[A-Z0-9]', text):
        return False

    # Include pages with holdings markers
    holdings_markers = [
        r'ISIN\s+(?:Company|Security|Description)',
        r'Sub\s+Total',
        r'Scheme\s+Name\s+Folio',
        r'HOLDING\s+STATEMENT',
        r'Sovereign\s+Gold\s+Bond',
        r'PORTFOLIO\s+COMPOSITION',
        r'Mutual\s+Fund\s+Folios?\s*\(F\)',
        r'Equities?\s*\(E\)',
        r'Mutual\s+Funds?\s*\(M\)',
        r'MUTUAL\s+FUND\s+UNITS',
        r'FUND\s+UNITS\s+HELD',
        r'Grand\s+Total',
        r'Valuation\s+Date',
    ]
    for marker in holdings_markers:
        if re.search(marker, text, re.IGNORECASE):
            return True

    # Include pages with multiple ISINs
    isin_count = len(ISIN_RE.findall(text))
    if isin_count >= 2:
        return True

    return False


def _validate_against_summary(holdings: list, summary: dict):
    """Log validation of parsed holdings against summary totals."""
    total_parsed = sum(h["quantity"] * h["current_price"] for h in holdings)
    expected = summary.get("total", 0)
    if expected > 0:
        coverage = total_parsed / expected
        logger.info(f"Validation: parsed ₹{total_parsed:,.0f} / expected ₹{expected:,.0f} ({coverage:.0%})")
    else:
        logger.info(f"Validation: parsed ₹{total_parsed:,.0f} (no summary total to compare)")


def _parse_nsdl_cas(page_texts: list) -> List[Dict]:
    """Parse NSDL CAS format."""
    # Find where transactions start
    holdings_end_page = len(page_texts)
    for i, text in enumerate(page_texts):
        if TRANSACTION_MARKER.search(text) and i > 3:
            holdings_end_page = i
            logger.info(f"NSDL transaction section at page {i+1}")
            break

    combined = "\n".join(page_texts[1:holdings_end_page])
    all_holdings = []

    # 1. Equities
    eq_section = _extract_section(combined, EQUITY_HEADER, [MF_M_HEADER, SGB_HEADER, MF_FOLIO_HEADER])
    if eq_section:
        all_holdings.extend(parse_equities(eq_section))

    # 2. Mutual Funds (M) — demat ETFs
    for mm in MF_M_HEADER.finditer(combined):
        start = mm.end()
        end = len(combined)
        for ep in [SGB_HEADER, MF_FOLIO_HEADER, EQUITY_HEADER]:
            em = ep.search(combined[start:])
            if em:
                end = min(end, start + em.start())
        sub = SUB_TOTAL_RE.search(combined[start:end])
        if sub:
            end = start + sub.end()
        all_holdings.extend(parse_mf_demat(combined[start:end]))

    # 3. Sovereign Gold Bonds
    for sm in SGB_HEADER.finditer(combined):
        candidate = combined[sm.end():sm.end() + 3000]
        if SGB_ISIN_RE.search(candidate[:500]):
            sub = SUB_TOTAL_RE.search(candidate)
            sgb_section = candidate[:sub.start()] if sub else candidate[:2000]
            all_holdings.extend(parse_sgb(sgb_section))
            break

    # 4. MF Folios
    for mf in MF_FOLIO_HEADER.finditer(combined):
        start = mf.end()
        end = len(combined)
        sub = SUB_TOTAL_RE.search(combined[start:])
        if sub:
            end = start + sub.start()
        all_holdings.extend(parse_mf_folios(combined[start:end]))

    return _deduplicate(all_holdings)


def _parse_cdsl_cas(page_texts: list) -> List[Dict]:
    """Parse CDSL CAS format."""
    combined = "\n".join(page_texts)
    all_holdings = []

    # Find CDSL equity holding pages (have "HOLDING STATEMENT" or CDSL equity header)
    for header_match in CDSL_EQUITY_HEADER.finditer(combined):
        start = header_match.end()
        end = len(combined)
        # Find end: next page header or MF section
        next_header = CDSL_EQUITY_HEADER.search(combined[start:])
        if next_header:
            end = start + next_header.start()
        cdsl_mf = CDSL_MF_HEADER.search(combined[start:])
        if cdsl_mf:
            end = min(end, start + cdsl_mf.start())
        all_holdings.extend(parse_cdsl_equities(combined[start:end]))

    # Find CDSL MF folio pages — look for both header patterns
    for mf_pattern in [CDSL_MF_HEADER, CDSL_MF_HELD]:
        for mf_match in mf_pattern.finditer(combined):
            start = mf_match.end()
            end = len(combined)
            grand_total = re.search(r'Grand\s+Total', combined[start:])
            if grand_total:
                end = start + grand_total.start()
            # Also cap at next page header
            next_page = re.search(r'Page\s+\d+\s+of\s+\d+', combined[start:])
            if next_page:
                end = min(end, start + next_page.start())
            parsed = parse_cdsl_mf_folios(combined[start:end])
            if parsed:
                all_holdings.extend(parsed)
                break  # Found MF section
        if any(h["asset_type"] == "mutual_fund" for h in all_holdings):
            break  # Don't search with second pattern if first found results

    return _deduplicate(all_holdings)


def _deduplicate(all_holdings: list) -> list:
    """Deduplicate holdings by ISIN."""
    seen = set()
    unique = []
    for h in all_holdings:
        key = h["ticker"]
        if key and key in seen:
            continue
        if key:
            seen.add(key)
        unique.append(h)
    logger.info(f"CAS local OCR: {len(all_holdings)} total → {len(unique)} unique holdings")
    return unique
