"""
ML-based OCR Correction Engine for CAS Parsing.
Learns from manual corrections to improve future parsing accuracy.

How it works:
1. When a CAS is parsed, holdings are stored with their raw OCR text
2. When a user or admin manually corrects a holding (fix ISIN, name, values), 
   the correction is stored as a training example
3. Future parsing uses these corrections to:
   a. Auto-correct known garbled ISINs (pattern matching)
   b. Fix known company name OCR errors
   c. Apply value corrections for specific patterns

The engine improves over time as more corrections accumulate.
"""
import json
import logging
import os
import re
from datetime import datetime, timezone
from typing import Dict, List, Optional, Tuple
from rapidfuzz import fuzz

logger = logging.getLogger("ocr_correction")

CORRECTIONS_PATH = os.path.join(os.path.dirname(__file__), "..", "data", "ocr_corrections.json")


def _load_corrections() -> dict:
    """Load correction database."""
    if not os.path.exists(CORRECTIONS_PATH):
        return {"isin_map": {}, "name_map": {}, "patterns": [], "stats": {"total_corrections": 0, "auto_applied": 0}}
    with open(CORRECTIONS_PATH) as f:
        return json.load(f)


def _save_corrections(data: dict):
    """Save correction database."""
    os.makedirs(os.path.dirname(CORRECTIONS_PATH), exist_ok=True)
    with open(CORRECTIONS_PATH, "w") as f:
        json.dump(data, f, indent=2)


def add_isin_correction(garbled_isin: str, correct_isin: str, context: str = ""):
    """Record an ISIN OCR correction. This teaches the engine for future parsing."""
    db = _load_corrections()
    db["isin_map"][garbled_isin] = {
        "correct": correct_isin,
        "context": context,
        "added_at": datetime.now(timezone.utc).isoformat(),
        "times_applied": 0,
    }
    db["stats"]["total_corrections"] += 1

    # Also learn the character-level pattern
    if len(garbled_isin) == len(correct_isin):
        for i, (g, c) in enumerate(zip(garbled_isin, correct_isin)):
            if g != c:
                pattern = {"position": i, "ocr_char": g, "correct_char": c, "count": 1}
                # Check if pattern already exists
                found = False
                for p in db["patterns"]:
                    if p["position"] == i and p["ocr_char"] == g and p["correct_char"] == c:
                        p["count"] += 1
                        found = True
                        break
                if not found:
                    db["patterns"].append(pattern)

    _save_corrections(db)
    logger.info("Learned ISIN correction: %s → %s", garbled_isin, correct_isin)


def add_name_correction(garbled_name: str, correct_name: str, isin: str = ""):
    """Record a company/scheme name OCR correction."""
    db = _load_corrections()
    key = garbled_name.lower().strip()
    db["name_map"][key] = {
        "correct": correct_name,
        "isin": isin,
        "added_at": datetime.now(timezone.utc).isoformat(),
    }
    db["stats"]["total_corrections"] += 1
    _save_corrections(db)
    logger.info("Learned name correction: '%s' → '%s'", garbled_name, correct_name)


def apply_corrections(holdings: list) -> list:
    """Apply learned corrections to parsed holdings."""
    db = _load_corrections()
    isin_map = db.get("isin_map", {})
    name_map = db.get("name_map", {})
    patterns = db.get("patterns", [])
    applied = 0

    for h in holdings:
        isin = h.get("ticker", "")
        name = h.get("name", "")

        # 1. Direct ISIN correction
        if isin in isin_map:
            correction = isin_map[isin]
            h["ticker"] = correction["correct"]
            correction["times_applied"] = correction.get("times_applied", 0) + 1
            applied += 1
            logger.debug("Auto-corrected ISIN: %s → %s", isin, correction['correct'])
            continue

        # 2. Pattern-based ISIN correction
        if isin and len(isin) == 12:
            corrected = list(isin)
            changed = False
            for p in patterns:
                pos = p["position"]
                if pos < len(corrected) and corrected[pos] == p["ocr_char"] and p["count"] >= 2:
                    corrected[pos] = p["correct_char"]
                    changed = True
            if changed:
                new_isin = "".join(corrected)
                if new_isin != isin:
                    h["ticker"] = new_isin
                    applied += 1
                    logger.debug("Pattern-corrected ISIN: %s → %s", isin, new_isin)

        # 3. Name correction
        name_key = name.lower().strip()
        if name_key in name_map:
            correction = name_map[name_key]
            h["name"] = correction["correct"]
            if correction.get("isin") and not h.get("ticker"):
                h["ticker"] = correction["isin"]
            applied += 1

        # 4. Fuzzy name correction (for names that are close but not exact)
        if name and len(name) > 3:
            best_score = 0
            best_correction = None
            for key, correction in name_map.items():
                score = fuzz.ratio(name_key, key)
                if score > 85 and score > best_score:
                    best_score = score
                    best_correction = correction
            if best_correction:
                h["name"] = best_correction["correct"]
                if best_correction.get("isin"):
                    h["ticker"] = best_correction["isin"]
                applied += 1

    if applied > 0:
        db["stats"]["auto_applied"] += applied
        _save_corrections(db)
        logger.info("Applied %s learned corrections", applied)

    return holdings


def seed_known_corrections():
    """Seed the correction database with known OCR errors from testing."""
    known_isin_corrections = [
        # NSDL known errors
        ("INEO66P01011", "INE066P01011", "INOX WIND - O→0 at pos 3"),
        ("INF200KO1RAO", "INF200K01RA0", "SBI Contra - O→0 at pos 7,11"),
        ("INFOS0101569", "INF090I01569", "Franklin Small Cap - O→0,S→9,1→I"),
        ("INF769KO1IR7", "INF769K01IR7", "Mirae Asset - O→0 at pos 7"),
        ("INF179KO1830", "INF179K01830", "HDFC Balanced Adv - O→0 at pos 7"),
        ("INF109KO16LO", "INF109K016L0", "ICICI Pru Large Cap - O→0"),
        ("INF109KO1AF8", "INF109K01AF8", "ICICI Pru Value - O→0 at pos 7"),
        # CDSL known errors
        ("INF209KO1BR9", "INF209K01BR9", "Aditya Birla Large Cap - O→0"),
        ("INF179KO1CR2", "INF179K01CR2", "HDFC Mid Cap Growth - O→0"),
        ("INF179KO1CT8", "INF179K01CT8", "HDFC Mid Cap IDCW - O→0"),
        ("INF109KO1AF8", "INF109K01AF8", "ICICI Pru Value - O→0"),
        ("INF174KO1187", "INF174K01187", "Kotak Large & Midcap - O→0"),
        ("INF769KO1EY2", "INF769K01EY2", "Mirae Midcap - O→0"),
        ("INF204KO1HY3", "INF204K01HY3", "Nippon Small Cap - O→0"),
    ]

    known_name_corrections = [
        ("NECONGOT ee", "NTPC GREEN ENERGY LIMITED", "INE733E01010"),
        ("RN oe", "ORIENT CEMENT LIMITED", "INE876N01018"),
        ("BOONWiANES", "GODREJ CONSUMER PRODUCTS LIMITED", "INE364U01010"),
    ]

    for garbled, correct, context in known_isin_corrections:
        add_isin_correction(garbled, correct, context)

    for garbled, correct, isin in known_name_corrections:
        add_name_correction(garbled, correct, isin)

    logger.info("Seeded %s ISIN + %s name corrections", len(known_isin_corrections), len(known_name_corrections))


def get_correction_stats() -> dict:
    """Get statistics about the correction engine."""
    db = _load_corrections()
    return {
        "total_corrections": db["stats"]["total_corrections"],
        "auto_applied": db["stats"]["auto_applied"],
        "isin_corrections": len(db.get("isin_map", {})),
        "name_corrections": len(db.get("name_map", {})),
        "patterns_learned": len(db.get("patterns", [])),
    }
