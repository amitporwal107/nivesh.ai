"""Sector profile classifier.

Maps nidp.sector_master.sector strings → internal sector_profile constants.
The profile drives which scoring formula is applied in v3_scores_engine.
"""
from __future__ import annotations

from typing import Optional

# ── Profile constants ─────────────────────────────────────────────────────────
BANK     = "BANK"
NBFC     = "NBFC"
CYCLICAL = "CYCLICAL"
IT       = "IT"
FMCG     = "FMCG"
PHARMA   = "PHARMA"
CAPGOODS = "CAPGOODS"
DEFAULT  = "DEFAULT"

ALL_PROFILES = (BANK, NBFC, CYCLICAL, IT, FMCG, PHARMA, CAPGOODS, DEFAULT)

# ── Sector → profile mapping ──────────────────────────────────────────────────
# Keys are normalised lower-case substrings; first match wins.
# Covers all sectors seen in nidp.sector_master and NSE equity master.
_SECTOR_MAP: list[tuple[str, str]] = [
    # Banks
    ("bank",              BANK),
    ("banking",           BANK),

    # NBFCs / Housing Finance
    ("nbfc",              NBFC),
    ("finance",           NBFC),
    ("housing finance",   NBFC),
    ("microfinance",      NBFC),

    # IT
    ("information technology", IT),
    ("software",          IT),
    ("it services",       IT),
    ("technology",        IT),

    # FMCG / Consumer
    ("fmcg",              FMCG),
    ("consumer staple",   FMCG),
    ("personal care",     FMCG),
    ("tobacco",           FMCG),
    ("beverages",         FMCG),
    ("food",              FMCG),

    # Pharma / Healthcare
    ("pharma",            PHARMA),
    ("healthcare",        PHARMA),
    ("biotechnology",     PHARMA),
    ("hospital",          PHARMA),
    ("diagnostics",       PHARMA),

    # Capital Goods / Infrastructure
    ("capital goods",     CAPGOODS),
    ("industrial",        CAPGOODS),
    ("infrastructure",    CAPGOODS),
    ("engineering",       CAPGOODS),
    ("defence",           CAPGOODS),
    ("aerospace",         CAPGOODS),

    # FMCG / Consumer (check before generic "consumer" matches)
    ("consumer durable",   FMCG),
    ("consumer electronic", FMCG),

    # Cyclicals — more specific keywords FIRST (before shorter substrings)
    ("construction material", CYCLICAL),  # before "construction" → CAPGOODS
    ("metal",             CYCLICAL),
    ("mining",            CYCLICAL),
    ("cement",            CYCLICAL),
    ("automobile",        CYCLICAL),
    ("auto",              CYCLICAL),
    ("chemical",          CYCLICAL),
    ("real estate",       CYCLICAL),
    ("oil",               CYCLICAL),
    ("gas",               CYCLICAL),
    ("power",             CYCLICAL),
    ("steel",             CYCLICAL),
    ("aluminium",         CYCLICAL),
    ("realty",            CYCLICAL),
    ("textile",           CYCLICAL),
    ("paper",             CYCLICAL),
    ("plastic",           CYCLICAL),

    # Capital Goods / Infrastructure — "construction" after "construction material"
    ("construction",      CAPGOODS),
]


def classify(sector: Optional[str], industry: Optional[str] = None) -> str:
    """Return the sector_profile for a given sector/industry string.

    Falls through to DEFAULT if no match found.
    Order: sector checked first, then industry as fallback.
    """
    for text in (sector, industry):
        if not text:
            continue
        normalised = text.lower().strip()
        for keyword, profile in _SECTOR_MAP:
            if keyword in normalised:
                return profile
    return DEFAULT
