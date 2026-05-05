"""NIDP runtime configuration — source URLs, retry policy, paths.

All knobs the ingestion layer consumes live here. Nothing else in the
NIDP module hard-codes URLs or paths. This keeps the source
inventory legible in one place and makes future swap-out (primary →
fallback) a config change, not a code change.

Source URLs are templates with the following placeholders:
    {YYYYMMDD}  — eight-digit date          (20260504)
    {DDMMYYYY}  — eight-digit reverse date  (04052026)
    {DDMMMYYYY} — old NSE format            (04MAY2026)
    {YYYY}      — four-digit year
    {MMM}       — three-letter month upper  (MAY)

URLs verified against the PRD's source list (§4) and the audit done
in the discussion phase. Where the PRD URL has shifted (e.g. NSE moved
bhavcopy to the post-Jul-2024 layout in 2024), both forms are noted —
the ingester picks based on `as_of_date`.
"""
from __future__ import annotations

import os
from pathlib import Path
from typing import Final

# ── Paths ───────────────────────────────────────────────────────────
NIDP_ROOT: Final[Path] = Path(__file__).resolve().parent
NIDP_RAW_DIR: Final[Path] = Path(
    os.environ.get("NIDP_RAW_DIR")
    or (NIDP_ROOT.parent.parent / "data" / "nidp_raw")
)
NIDP_RAW_DIR.mkdir(parents=True, exist_ok=True)

MIGRATIONS_DIR: Final[Path] = NIDP_ROOT / "migrations"

# ── HTTP defaults ───────────────────────────────────────────────────
HTTP_TIMEOUT_S: Final[int] = 30
HTTP_RETRY_ATTEMPTS: Final[int] = 4
HTTP_RETRY_BACKOFF_S: Final[float] = 1.5     # exponential base

# Browser-grade UA. NSE archives reject curl-style UAs.
DEFAULT_UA: Final[str] = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/124.0.0.0 Safari/537.36"
)

# ── Source URL templates ────────────────────────────────────────────
# All hosts known to NIDP. Per-source templates use these.
NSE_ARCHIVES: Final[str] = "https://archives.nseindia.com"
NSE_NSEARCHIVES: Final[str] = "https://nsearchives.nseindia.com"
NSE_WWW: Final[str] = "https://www.nseindia.com"
BSE_WWW: Final[str] = "https://www.bseindia.com"
RBI_WWW: Final[str] = "https://www.rbi.org.in"

# ── P0 source registry (matches user-locked list of 10) ─────────────
# Each entry below is a logical source. The ingester implementations
# import these to keep URL knowledge in one place.

# 1.3 EOD bhavcopy — post-Jul-2024 format
BHAVCOPY_URL_NEW: Final[str] = (
    f"{NSE_NSEARCHIVES}/content/cm/BhavCopy_NSE_CM_0_0_0_{{YYYYMMDD}}_F_0000.csv.zip"
)
# Pre-Jul-2024 format (kept for historical backfill)
BHAVCOPY_URL_OLD: Final[str] = (
    f"{NSE_ARCHIVES}/content/historical/EQUITIES/{{YYYY}}/{{MMM}}/cm{{DDMMMYYYY}}bhav.csv.zip"
)
BHAVCOPY_FORMAT_CUTOVER_DATE: Final[str] = "2024-07-08"

# 1.4 Delivery / sec_bhavdata_full
DELIVERY_URL: Final[str] = (
    f"{NSE_ARCHIVES}/products/content/sec_bhavdata_full_{{DDMMYYYY}}.csv"
)

# 1.5 Index close all
INDEX_CLOSE_URL: Final[str] = (
    f"{NSE_ARCHIVES}/content/indices/ind_close_all_{{DDMMYYYY}}.csv"
)

# 1.6 Index constituents — one URL per index. We seed the most
# important; extend as needed.
INDEX_CONSTITUENT_URLS: Final[dict[str, str]] = {
    "Nifty 50":   f"{NSE_ARCHIVES}/content/indices/ind_nifty50list.csv",
    "Nifty 100":  f"{NSE_ARCHIVES}/content/indices/ind_nifty100list.csv",
    "Nifty 200":  f"{NSE_ARCHIVES}/content/indices/ind_nifty200list.csv",
    "Nifty 500":  f"{NSE_ARCHIVES}/content/indices/ind_nifty500list.csv",
    "Nifty Bank": f"{NSE_ARCHIVES}/content/indices/ind_niftybanklist.csv",
    "Nifty IT":   f"{NSE_ARCHIVES}/content/indices/ind_niftyitlist.csv",
}

# 2.1 FII/DII cash daily
FII_DII_URL: Final[str] = (
    f"{NSE_ARCHIVES}/content/fo/fii_stats_{{YYYYMMDD}}.xls"
)

# 6.1 Corporate actions — NSE moved this from CSV (now 404) to a
# JSON API. The new endpoint returns an array of dicts with fields
# symbol/series/subject/exDate/recDate/bcStartDate/bcEndDate/etc.
# Parser detects JSON vs legacy CSV automatically.
CORPORATE_ACTIONS_URL_ROLLING: Final[str] = (
    f"{NSE_WWW}/api/corporates-corporateActions?index=equities"
)
# Date-stamped archive (when present — legacy)
CORPORATE_ACTIONS_URL_DAILY: Final[str] = (
    f"{NSE_ARCHIVES}/content/corporate_actions/CA_{{YYYYMMDD}}.csv"
)

# 7.1 / 7.2 Bulk + block deals — rolling files
BULK_DEALS_URL: Final[str] = f"{NSE_ARCHIVES}/content/equities/bulk.csv"
BLOCK_DEALS_URL: Final[str] = f"{NSE_ARCHIVES}/content/equities/block.csv"

# 8.1 RBI 10Y yield — fixes the current `^TNX = US 10Y` bug.
# RBI publishes via ReferenceRateArchive (HTML scrape) and DBIE.
RBI_REF_RATE_URL: Final[str] = (
    f"{RBI_WWW}/Scripts/ReferenceRateArchive.aspx"
)
RBI_GSEC_URL: Final[str] = (
    f"{RBI_WWW}/Scripts/BS_NSDPDisplay.aspx?param=4"   # G-Sec daily reference
)

# 10.1 NSE holiday master — JSON endpoint
NSE_HOLIDAY_URL: Final[str] = (
    f"{NSE_WWW}/api/holiday-master?type=trading"
)

# ── Per-ingester source-class metadata (mirrors schema seed) ────────
SOURCE_REGISTRY: Final[list[dict]] = [
    # name, ingester, url-pattern, class, confidence, freq
    ("NSE_BHAVCOPY",        "bhavcopy",            BHAVCOPY_URL_NEW,            "B", 0.92, "daily"),
    ("NSE_SEC_BHAVDATA",    "delivery",            DELIVERY_URL,                "B", 0.90, "daily"),
    ("NSE_IND_CLOSE",       "index_close",         INDEX_CLOSE_URL,             "A", 0.95, "daily"),
    ("NSE_INDEX_LIST",      "index_constituents",  "{INDEX_NAME}",              "A", 0.95, "quarterly"),
    ("NSE_FII_DII",         "fii_dii",             FII_DII_URL,                 "B", 0.90, "daily"),
    ("NSE_CA",              "corporate_actions",   CORPORATE_ACTIONS_URL_ROLLING,"B", 0.92, "daily"),
    ("NSE_BULK",            "bulk_deals",          BULK_DEALS_URL,              "A", 0.95, "daily"),
    ("NSE_BLOCK",           "block_deals",         BLOCK_DEALS_URL,             "A", 0.95, "daily"),
    ("RBI_REF_RATE",        "rbi_yields",          RBI_REF_RATE_URL,            "B", 0.85, "daily"),
    ("NSE_HOLIDAY_MASTER",  "nse_calendar",        NSE_HOLIDAY_URL,             "B", 0.90, "annual"),
]


# ── Helpers ─────────────────────────────────────────────────────────
def fmt_url(template: str, dt) -> str:
    """Render a URL template against a `datetime.date`.

    Substitutes {YYYYMMDD}, {DDMMYYYY}, {DDMMMYYYY}, {YYYY}, {MMM}.
    """
    return (
        template
        .replace("{YYYYMMDD}",  dt.strftime("%Y%m%d"))
        .replace("{DDMMYYYY}",  dt.strftime("%d%m%Y"))
        .replace("{DDMMMYYYY}", dt.strftime("%d%b%Y").upper())
        .replace("{YYYY}",      dt.strftime("%Y"))
        .replace("{MMM}",       dt.strftime("%b").upper())
    )
