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
NIDP_ROOT: Final[Path] = Path(__file__).resolve().parent.parent

# T08 fix: default raw-archive path.
# On the production VM NIDP_HOME=/opt/nidp is set by the cron environment,
# so raw archives land in the persistent /opt/nidp/raw_archives/ volume
# (writable host mount) instead of the read-only Docker layer.
# In dev (no NIDP_HOME), falls back to <repo>/data/nidp_raw.
_nidp_home = os.environ.get("NIDP_HOME", "").strip()
NIDP_RAW_DIR: Final[Path] = Path(
    os.environ.get("NIDP_RAW_DIR")
    or (f"{_nidp_home}/raw_archives" if _nidp_home else str(NIDP_ROOT.parent / "data" / "nidp_raw"))
)
# mkdir is best-effort: skip silently on read-only filesystems so that
# import-time failures don't break services that never call store().
try:
    NIDP_RAW_DIR.mkdir(parents=True, exist_ok=True)
except OSError:
    pass

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

# Optional egress proxy for NSE hosts ONLY (e.g. "http://10.160.0.5:3128").
#
# NSE blocks by SOURCE IP, not by request shape. Measured 2026-08-19, the same
# request with the same headers from two VMs in the same region and project:
#
#     nidp-stack-vm  34.93.60.254  -> 403     (the ingestion host)
#     nivesh-app-vm  34.47.250.214 -> 200
#
# So no amount of UA/cookie/Referer work fixes it — the traffic has to leave by a
# different address. Setting this routes only NSE requests through the proxy;
# BSE and every other host keep the direct path, so the BSE fallbacks are
# unaffected and a broken proxy cannot take them down with it. Unset = direct.
NSE_HTTPS_PROXY: Final[str] = os.environ.get("NSE_HTTPS_PROXY", "").strip()

# Minimum gap between NSE requests, seconds. The block was almost certainly
# earned by request volume, so moving to a new IP without slowing down just
# burns the new IP too. 0 disables.
NSE_MIN_REQUEST_INTERVAL_S: Final[float] = float(
    os.environ.get("NSE_MIN_REQUEST_INTERVAL_S", "0.35") or 0
)

# ── Source URL templates ────────────────────────────────────────────
# All hosts known to NIDP. Per-source templates use these.
# NB: As of late-2024 NSE deprecated the legacy `archives.nseindia.com`
# host (now returns Akamai 503). All archive content moved to
# `nsearchives.nseindia.com`. We keep the constant name `NSE_ARCHIVES`
# for clarity at call sites but point it at the live host.
NSE_ARCHIVES: Final[str] = "https://nsearchives.nseindia.com"
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

# 2.1 FII/DII cash daily — NSE moved from XLS archive to JSON API.
# Old: archives.nseindia.com/content/fo/fii_stats_{YYYYMMDD}.xls (404)
# New: JSON array of {category, date, buyValue, sellValue, netValue}
FII_DII_URL: Final[str] = (
    f"{NSE_WWW}/api/fiidiiTradeReact"
)
# Legacy XLS archive (kept for parser auto-detect / historical backfill)
NSDL_FPI_FORTNIGHTLY_URL: Final[str] = (
    "https://www.fpi.nsdl.co.in/web/Reports/FPI_Fortnightly_Selection.aspx"
)
FII_DII_URL_LEGACY: Final[str] = (
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

# 11.1 NSE financial results — rolling list endpoint per filing period.
# Each list entry carries an `xbrl` URL pointing at the filing
# document; the ingester fetches each XBRL doc separately.
NSE_FINANCIALS_LIST_URL_QUARTERLY: Final[str] = (
    f"{NSE_WWW}/api/corporates-financial-results?index=equities&period=Quarterly"
)
NSE_FINANCIALS_LIST_URL_ANNUAL: Final[str] = (
    f"{NSE_WWW}/api/corporates-financial-results?index=equities&period=Annual"
)

# 11.2 NSE shareholding pattern — rolling list endpoint per filing period.
# Same shape as financial results: list returns manifests with XBRL
# URLs; ingester deep-fetches each XBRL.
NSE_SHAREHOLDING_LIST_URL: Final[str] = (
    f"{NSE_WWW}/api/corporate-share-holdings-master?index=equities"
)

# 11.3 NSE Equity Master — sector / industry classification CSV.
NSE_EQUITY_MASTER_URL: Final[str] = (
    f"{NSE_NSEARCHIVES}/content/equities/EQUITY_L.csv"
)

# 11.4 NSE FO bhavcopy — EOD options + futures by trading day.
# Post-Jul-2024 unified format: BhavCopy_NSE_FO_*.csv.zip
NSE_FO_BHAVCOPY_URL_NEW: Final[str] = (
    f"{NSE_NSEARCHIVES}/content/fo/BhavCopy_NSE_FO_0_0_0_{{YYYYMMDD}}_F_0000.csv.zip"
)
# Pre-cutover (legacy fo_bhavcopy)
NSE_FO_BHAVCOPY_URL_OLD: Final[str] = (
    f"{NSE_ARCHIVES}/content/historical/DERIVATIVES/{{YYYY}}/{{MMM}}/fo{{DDMMMYYYY}}bhav.csv.zip"
)
NSE_FO_BHAVCOPY_FORMAT_CUTOVER_DATE: Final[str] = "2024-07-08"

# ── Mutual fund sources ─────────────────────────────────────────────
AMFI_WWW: Final[str] = "https://www.amfiindia.com"
AMFI_PORTAL: Final[str] = "https://portal.amfiindia.com"

# 12.1 AMFI daily NAV — pipe-delimited file with all schemes' current NAV.
# Carries scheme metadata (code, ISINs, name) inline as section headers,
# so the same fetch drives mf_scheme_master upserts as well as mf_nav_daily.
# NB: AMFI moved this from www.amfiindia.com → portal.amfiindia.com in 2026.
# The www.amfiindia.com path now 302s to portal — we hit portal directly
# to skip the round-trip.
AMFI_NAV_ALL_URL: Final[str] = f"{AMFI_PORTAL}/spages/NAVAll.txt"

# 12.2 MFAPI.in — unofficial JSON aggregator over AMFI historical NAV.
# Used for backfill / gap-fill only; daily ingest stays AMFI-direct.
MFAPI_LIST_URL:    Final[str] = "https://api.mfapi.in/mf"
MFAPI_SCHEME_URL:  Final[str] = "https://api.mfapi.in/mf/{SCHEME_CODE}"

# 12.3 AMFI notices/circulars — landing page lists individual notices.
# Source for scheme lifecycle events (mergers, renames, regulatory changes).
AMFI_CIRCULARS_URL: Final[str] = (
    f"{AMFI_WWW}/research-information/other-data/notices-circular"
)

# 12.4 Per-AMC scheme info / disclosure pages. Used by mf_disclosure_snapshot
# and mf_holdings; one config per top-10 AMC. Each AMC site differs, so
# the per-AMC fetcher/parser pair is registered in
# nidp.services.mf_disclosure_snapshot.amc_dispatch and mf_holdings.amc_dispatch.
MF_AMC_TOP10: Final[tuple[str, ...]] = (
    "sbi", "icici_pru", "hdfc", "nippon", "kotak",
    "absl", "uti", "axis", "tata", "mirae",
)

# Tier-2 AMCs with working portfolio adapters (added 2026-05-27).
# Included in nightly mf_holdings run alongside MF_AMC_TOP10.
MF_AMC_TIER2: Final[tuple[str, ...]] = (
    "quant",
    "jm_financial",
)

# Tier-3 AMCs whose FULL portfolio disclosure (spreadsheet) is on AdvisorKhoj
# and parses cleanly via the AdvisorKhoj adapter (added 2026-06-25). Resolved
# by scheme-name prefix (no amc_id in the master). Included in the holdings run.
MF_AMC_TIER3: Final[tuple[str, ...]] = (
    "franklin",
    "ppfas",
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
    ("NSE_FIN",             "nse_financials",      NSE_FINANCIALS_LIST_URL_QUARTERLY, "B", 0.85, "daily"),
    ("NSE_SHP",             "nse_shareholding",    NSE_SHAREHOLDING_LIST_URL,   "B", 0.85, "daily"),
    ("NSE_EQUITY_MASTER",   "nse_equity_master",   NSE_EQUITY_MASTER_URL,       "A", 0.95, "weekly"),
    ("NSE_FO_BHAVCOPY",     "fno_bhavcopy",        NSE_FO_BHAVCOPY_URL_NEW,     "A", 0.95, "daily"),
    # Sector-level FPI custody has no NSE equivalent — it is reported by the
    # depository, not the exchange. Class A: NSDL is the primary custodian record.
    ("NSDL_FPI_FORTNIGHTLY", "fpi_sector_auc",  NSDL_FPI_FORTNIGHTLY_URL,    "A", 0.95, "fortnightly"),
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
