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
SGB_ISIN_RE = re.compile(r'\b(IN\d{10,13})\b')
NUM_RE = re.compile(r'[\d,]+\.?\d*')

# Table header patterns for precise section detection
EQUITY_HEADER = re.compile(r'ISIN\s+Company\s+Name\s+Face\s+Value', re.IGNORECASE)
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
            isin = m.group(1)
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

            after = block_clean[block_clean.index(isin) + len(isin):]
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

            if value > 0:
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
            isin = m.group(1)
            block = line
            j = i + 1
            while j < len(lines):
                nl = lines[j].strip()
                if ISIN_RE.search(nl) or SUB_TOTAL_RE.search(nl) or SGB_HEADER.search(nl):
                    break
                block += " " + nl
                j += 1

            block_clean = re.sub(r'of which Pledged.*', '', block, flags=re.IGNORECASE)
            after = block_clean[block_clean.index(isin) + len(isin):]
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

            # Validate
            if units > 0 and nav > 0 and value > 0:
                expected = units * nav
                if abs(expected - value) / max(value, 1) > 0.2:
                    units = round(value / nav, 3) if nav > 0 else units

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
            block = line
            j = i + 1
            while j < len(lines):
                nl = lines[j].strip()
                if SGB_ISIN_RE.search(nl) or SUB_TOTAL_RE.search(nl) or 'Total' == nl.split()[0] if nl.split() else False:
                    break
                block += " " + nl
                j += 1

            nums = extract_all_numbers(block)
            # Remove coupon rate (2.50)
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
            isin_blocks.append({"isin": m.group(1), "start": i, "lines": [line], "pre_nums": pre_nums})
        elif isin_blocks:
            isin_blocks[-1]["lines"].append(line)
        i += 1

    for block in isin_blocks:
        isin = block["isin"]
        full_text = " ".join(l for l in block["lines"] if l.strip())
        # Remove MF UCC codes and noise
        full_text = re.sub(r'MF[A-Z0-9]{5,}', '', full_text)
        full_text = re.sub(r'NOT AVAILABLE', '', full_text)

        after = full_text[full_text.index(isin) + len(isin):]

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


def parse_nsdl_cas_image(content: bytes, password: str = "") -> List[Dict]:
    """Parse image-based NSDL/CDSL CAS PDF using local Tesseract OCR."""
    from pdf2image import convert_from_bytes

    kwargs = {"dpi": 200}
    if password:
        kwargs["userpw"] = password

    try:
        images = convert_from_bytes(content, **kwargs)
    except Exception as e:
        logger.error(f"PDF to image conversion failed: {e}")
        return []

    logger.info(f"CAS local OCR: {len(images)} pages")

    # OCR pages and find where transactions start
    page_texts = []
    holdings_end_page = len(images)
    for i, img in enumerate(images):
        text = ocr_page(img)
        page_texts.append(text)
        # Transactions section has "ISIN : INE..." pattern
        if TRANSACTION_MARKER.search(text) and i > 3:
            holdings_end_page = i
            logger.info(f"Transaction section starts at page {i+1}, stopping holdings parse")
            break

    # Combine holdings pages only (skip page 0 = cover letter)
    combined = "\n".join(page_texts[1:holdings_end_page])

    all_holdings = []

    # 1. Parse Equities
    eq_section = _extract_section(combined, EQUITY_HEADER, [MF_M_HEADER, SGB_HEADER, MF_FOLIO_HEADER])
    if eq_section:
        all_holdings.extend(parse_equities(eq_section))

    # 2. Parse Mutual Funds (M) — demat ETFs
    # May appear multiple times (different demat accounts)
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
        section = combined[start:end]
        all_holdings.extend(parse_mf_demat(section))

    # 3. Parse Sovereign Gold Bonds — find the one after "Sub Total" of MF(M), not the composition
    sgb_section = ""
    for sm in SGB_HEADER.finditer(combined):
        candidate = combined[sm.end():sm.end() + 3000]
        # Real SGB section has ISIN-like numbers (IN00...) within first 500 chars
        if SGB_ISIN_RE.search(candidate[:500]):
            sub = SUB_TOTAL_RE.search(candidate)
            sgb_section = candidate[:sub.start()] if sub else candidate[:2000]
            break
    if sgb_section:
        all_holdings.extend(parse_sgb(sgb_section))

    # 4. Parse MF Folios
    for mf in MF_FOLIO_HEADER.finditer(combined):
        start = mf.end()
        end = len(combined)
        sub = SUB_TOTAL_RE.search(combined[start:])
        if sub:
            end = start + sub.start()
        section = combined[start:end]
        all_holdings.extend(parse_mf_folios(section))

    # Deduplicate by ISIN
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
