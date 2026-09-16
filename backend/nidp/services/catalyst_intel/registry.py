"""The source universe, in the user's priority order, as a registry of ingestion routes.

Three ingestion modes (the user's design, 2026-09-16):
  api      structured feed or JSON/Atom endpoint (RBI/SEC/openFDA/NHAI's own API/CCI DataTables)
  http     HTML listing, RSS or a form postback fetched by plain HTTP (NSE/BSE/PIB/ministries/CPPP tables)
  browser  needs a real browser and/or a non-cloud egress; served by a browser worker through the job queue

A source may carry several routes; the monitor tries them in order (PRIMARY egress → SECONDARY egress → BROWSER job)
and records which one served. Statuses are granular and observed, never a permanent "blocked":
  live               fetched through its primary route from this VM
  live_secondary     fetched only through the secondary egress (a proxy) — reported as such, never as live
  degraded           the endpoint answers but with partial or stale data (FDA warning-letters xlsx export)
  empty / stale      the route answered with no rows (fine within the SLA, stale past it)
  blocked_temporary  rate limit / abuse detection / 5xx — retry later
  waf_blocked        CloudFront/Akamai refuse cloud egress (this VM AND app-vm, probed 2026-09-16) — needs a browser worker elsewhere
  captcha_gated      a captcha search stands between us and the rows (CPPP awards)
  session_required   the listing needs an interactive session (old eprocure app pages)
  js_rendered        a JS shell with no API found yet
  endpoint_unknown   host reachable, machine-readable endpoint not yet located
  not_built          on the list, no adapter yet
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

MODES = ("api", "http", "browser")
STATUSES = ("live", "live_secondary", "live_browser", "degraded", "empty", "stale", "blocked_temporary", "waf_blocked", "captcha_gated",
            "session_required", "js_rendered", "endpoint_unknown", "not_built")
RUNNABLE = ("live", "live_secondary", "degraded")            # statuses the monitor fetches over HTTP from this VM
UA_PLAIN, UA_BROWSER, UA_SEC = "plain", "browser", "sec"      # per-route user-agent policy (see transports.py)


@dataclass(frozen=True)
class Route:
    mode: str                    # api | http | browser
    fetch: str                   # get | nse_api_days | bse_subcat_days | cci_datatable | pib_days | nhai_api | cppp_pages | browser_job
    url: str
    adapter: str                 # adapters.<function>
    egress: str = "primary"      # primary = this VM | secondary = app-vm proxy (CIE_SECONDARY_PROXY)
    ua: str = UA_BROWSER
    pages: int = 1


@dataclass(frozen=True)
class Source:
    id: str
    name: str
    klass: str                   # regulator | exchange | government | global | ratings | news
    priority: str                # P0..P3
    url: str
    status: str
    adapter: Optional[str] = None
    fetch: str = "get"
    country: str = "IN"
    notes: str = ""
    mode: str = "http"
    sla_hours: float = 24.0      # how fresh a working source is expected to be; an empty feed older than this is 'stale'
    routes: tuple = ()           # explicit routes; empty = one route derived from (mode, fetch, url, adapter)
    ua: str = UA_BROWSER


def routes_for(s: Source) -> tuple:
    if s.routes:
        return s.routes
    if not s.adapter:
        return ()
    return (Route(s.mode if s.mode != "browser" else "http", s.fetch, s.url, s.adapter, ua=s.ua),)


def _R(mode, fetch, url, adapter, **kw) -> Route:
    return Route(mode, fetch, url, adapter, **kw)


SOURCES: tuple[Source, ...] = (
    # ── P0: Indian regulators and exchanges ─────────────────────────────────────────────────────────────────────
    Source("rbi_press", "RBI press releases", "regulator", "P0", "https://www.rbi.org.in/pressreleases_rss.xml", "live", "parse_rss", mode="api", sla_hours=48,
           notes="page: https://www.rbi.org.in/Scripts/BS_PressReleaseDisplay.aspx; pubDate is naive IST"),
    Source("rbi_notifications", "RBI notifications / circulars", "regulator", "P0", "https://www.rbi.org.in/notifications_rss.xml", "live", "parse_rss", mode="api", sla_hours=72,
           notes="page: https://www.rbi.org.in/Scripts/BS_CircularIndexDisplay.aspx"),
    Source("sebi_rss", "SEBI media, orders, circulars (RSS)", "regulator", "P0", "https://www.sebi.gov.in/sebirss.xml", "live", "parse_rss", mode="api", sla_hours=48,
           notes="covers enforcement, recovery, circulars, press; page: https://www.sebi.gov.in/media-and-notifications.html"),
    Source("sebi_press", "SEBI press releases (listing)", "regulator", "P0", "https://www.sebi.gov.in/sebiweb/home/HomeAction.do?doListing=yes&sid=6&ssid=23", "live", "parse_listing", sla_hours=96),
    Source("cci_combination_press", "CCI combination press releases", "regulator", "P0", "https://www.cci.gov.in/combination/press-release", "live", "parse_cci_datatable", fetch="cci_datatable", mode="api", sla_hours=168,
           notes="DataTables server-side JSON on the page URL (X-Requested-With); order_date dd/mm/yyyy"),
    Source("cci_combination_orders", "CCI combination orders (s.31)", "regulator", "P0", "https://www.cci.gov.in/combination/orders-section31", "live", "parse_cci_datatable", fetch="cci_datatable", mode="api", sla_hours=168,
           notes="same mechanism; party, status, decision date"),
    Source("cci_antitrust_orders", "CCI antitrust orders", "regulator", "P0", "https://www.cci.gov.in/antitrust/orders", "endpoint_unknown", mode="api",
           notes="DataTables with a different column set; the JSON call needs its own column list (not yet mapped)"),
    Source("nse_announcements_api", "NSE corporate announcements (API, per calendar day)", "exchange", "P0",
           "https://www.nseindia.com/api/corporate-announcements?index=equities&from_date={d}&to_date={d}", "live", "parse_nse_api", fetch="nse_api_days", mode="api", sla_hours=24,
           notes="page: https://www.nseindia.com/companies-listing/corporate-filings-announcements; d = DD-MM-YYYY"),
    Source("nse_announcements_rss", "NSE corporate announcements (RSS)", "exchange", "P0", "https://nsearchives.nseindia.com/content/RSS/Online_announcements.xml", "live", "parse_rss", mode="api", sla_hours=24),
    Source("nse_board_meetings_rss", "NSE board meetings (RSS)", "exchange", "P0", "https://nsearchives.nseindia.com/content/RSS/Board_Meetings.xml", "live", "parse_rss", mode="api", sla_hours=168),
    Source("nse_corporate_actions_rss", "NSE corporate actions (RSS)", "exchange", "P0", "https://nsearchives.nseindia.com/content/RSS/Corporate_action.xml", "live", "parse_rss", mode="api", sla_hours=72),
    Source("bse_announcements_rss", "BSE corporate announcements (RSS)", "exchange", "P0", "https://www.bseindia.com/data/xml/announcements.xml", "live", "parse_rss", mode="api", sla_hours=24,
           notes="page: https://www.bseindia.com/corporates/ann.html; ~12,000 items, scrip code per item"),
    Source("bse_subcat_api", "BSE announcements (subcategory API, per calendar day)", "exchange", "P0",
           "https://api.bseindia.com/BseIndiaAPI/api/AnnSubCategoryGetData/w?pageno={page}&strCat=-1&strPrevDate={d}&strScrip=&strSearch=P&strToDate={d}&strType=C&subcategory=-1",
           "live", "parse_bse_subcat", fetch="bse_subcat_days", mode="api", sla_hours=24, notes="AnnGetData (used by the staging feed) answers 'No Record Found!' since 2026-09-12; d = YYYYMMDD, 50 rows/page"),
    # ── P0/P1: government (Phase 1 of the user's unblocking plan: NHAI + PIB + eProcure + DGFT) ─────────────────
    Source("pib", "Press Information Bureau (English, all ministries, per day)", "government", "P0", "https://www.pib.gov.in/allRel.aspx?reg=3&lang=1", "live", "parse_pib_day", fetch="pib_days", mode="http", sla_hours=24,
           notes="ASP.NET postback per calendar day (ddlday/ddlMonth/ddlYear, region 3 = PIB Delhi, lang 1 = English); RssMain.aspx is Hindi-only and answered 0 bytes on 2026-09-16"),
    Source("nhai_press_release", "NHAI press releases", "government", "P0", "https://nhai.gov.in/nhai/api/press-release", "live", "parse_nhai_api", fetch="nhai_api", mode="api", sla_hours=72,
           notes="the Angular app's own API (apiService.post + FormData; base URL in main.b6072fa2…js); PDF per item"),
    Source("nhai_news", "NHAI in the news (press clippings)", "government", "P1", "https://nhai.gov.in/nhai/api/news", "live", "parse_nhai_api", fetch="nhai_api", mode="api", sla_hours=168),
    Source("nhai_tenders", "NHAI tenders", "government", "P0", "https://nhai.gov.in/nhai/api/tenderlist", "live", "parse_nhai_api", fetch="nhai_api", mode="api", sla_hours=72),
    Source("cppp_tenders", "CPPP (eProcure) latest active tenders, central", "government", "P0", "https://eprocure.gov.in/cppp/latestactivetendersnew/cpppdata", "live", "parse_cppp_table", fetch="cppp_pages", mode="http", sla_hours=24,
           routes=(_R("http", "cppp_pages", "https://eprocure.gov.in/cppp/latestactivetendersnew/cpppdata", "parse_cppp_table", pages=3),),
           notes="10 rows/page, newest first; page n via the base64 ?url= parameter; the old /eprocure/app pages need a session and a captcha"),
    Source("cppp_corrigendums", "CPPP (eProcure) active corrigendums", "government", "P1", "https://eprocure.gov.in/cppp/latestactivecorrigendumsnew/cpppdata", "live", "parse_cppp_table", fetch="cppp_pages", mode="http", sla_hours=24,
           routes=(_R("http", "cppp_pages", "https://eprocure.gov.in/cppp/latestactivecorrigendumsnew/cpppdata", "parse_cppp_table", pages=2),)),
    Source("cppp_awards", "CPPP (eProcure) results of tenders (AOC)", "government", "P0", "https://eprocure.gov.in/cppp/resultoftendersnew/cpppdata", "captcha_gated", "parse_cppp_table", mode="browser", sla_hours=24,
           routes=(_R("browser", "browser_job", "https://eprocure.gov.in/cppp/resultoftendersnew/cpppdata", "parse_cppp_table"),),
           notes="award listing sits behind a captcha search form (org + year + captcha) — a browser worker solves it interactively"),
    Source("mod", "Ministry of Defence", "government", "P0", "https://mod.gov.in/en", "live", "parse_listing", sla_hours=168, notes="/en serves the English what's-new list; root is Hindi"),
    Source("mnre", "Ministry of New and Renewable Energy", "government", "P1", "https://mnre.gov.in/", "live", "parse_listing", sla_hours=168),
    Source("heavy_industries", "Ministry of Heavy Industries", "government", "P1", "https://www.heavyindustries.gov.in/en", "live", "parse_listing", sla_hours=168, notes="/en for English; root is Hindi"),
    Source("mines", "Ministry of Mines", "government", "P1", "https://mines.gov.in/", "endpoint_unknown", notes="home is a redirect shell (5 KB)"),
    Source("dgft", "DGFT notifications / trade policy", "government", "P0", "https://www.dgft.gov.in/CP/?opt=notification", "waf_blocked", "parse_listing", mode="browser", sla_hours=72,
           routes=(_R("http", "get", "https://www.dgft.gov.in/CP/?opt=notification", "parse_listing"),
                   _R("http", "get", "https://www.dgft.gov.in/CP/?opt=notification", "parse_listing", egress="secondary"),
                   _R("browser", "browser_job", "https://www.dgft.gov.in/CP/?opt=notification", "parse_listing")),
           notes="CloudFront 403 from this VM (34.93.60.254) AND via app-vm egress, browser and plain UA alike (2026-09-16) — a cloud-ASN block; browser worker on another egress"),
    Source("mca", "Ministry of Corporate Affairs", "government", "P1", "https://www.mca.gov.in/", "waf_blocked", "parse_listing", mode="browser", sla_hours=168,
           routes=(_R("http", "get", "https://www.mca.gov.in/", "parse_listing"), _R("http", "get", "https://www.mca.gov.in/", "parse_listing", egress="secondary"),
                   _R("browser", "browser_job", "https://www.mca.gov.in/", "parse_listing")),
           notes="403 from both cloud egresses (2026-09-16); not a dependency for Phase 1"),
    Source("ibbi", "IBBI", "regulator", "P1", "https://www.ibbi.gov.in/", "live", "parse_listing", sla_hours=168, notes="answered HTTP 500 on 2026-09-16 08:45; health tracks it"),
    Source("nclt", "NCLT", "regulator", "P1", "https://nclt.gov.in/", "live", "parse_listing", sla_hours=168),
    Source("cdsco_alerts", "CDSCO alerts", "regulator", "P0", "https://www.cdsco.gov.in/opencms/opencms/en/Alerts/", "live", "parse_listing", sla_hours=168),
    Source("cdsco_notices", "CDSCO public notices", "regulator", "P1", "https://www.cdsco.gov.in/opencms/opencms/en/Notifications/Public-Notices/", "live", "parse_listing", sla_hours=168),
    # ── P1: global (structured feeds only; never scraping) ───────────────────────────────────────────────────────
    Source("openfda_drug_enforcement", "US FDA drug recalls (openFDA enforcement API)", "global", "P0", "https://api.fda.gov/drug/enforcement.json?sort=report_date:desc&limit=100", "live", "parse_openfda_enforcement",
           mode="api", sla_hours=168, country="US", ua=UA_PLAIN, notes="1,000 requests/day without a key; recalling_firm + country per record"),
    Source("openfda_device_enforcement", "US FDA device recalls (openFDA enforcement API)", "global", "P1", "https://api.fda.gov/device/enforcement.json?sort=report_date:desc&limit=100", "live", "parse_openfda_enforcement",
           mode="api", sla_hours=168, country="US", ua=UA_PLAIN),
    Source("fda_recalls_rss", "US FDA recalls, market withdrawals, safety alerts (RSS)", "global", "P1", "https://www.fda.gov/about-fda/contact-fda/stay-informed/rss-feeds/recalls/rss.xml", "live", "parse_rss",
           mode="api", sla_hours=168, country="US", ua=UA_PLAIN, notes="Akamai flags the browser UA on www.fda.gov (abuse-detection redirect); the plain UA passes"),
    Source("fda_press_rss", "US FDA press releases (RSS)", "global", "P2", "https://www.fda.gov/about-fda/contact-fda/stay-informed/rss-feeds/press-releases/rss.xml", "live", "parse_rss",
           mode="api", sla_hours=168, country="US", ua=UA_PLAIN),
    Source("fda_warning_letters", "US FDA warning letters", "global", "P0",
           "https://www.fda.gov/inspections-compliance-enforcement-and-criminal-investigations/compliance-actions-and-activities/warning-letters/datatables-data?page&_format=xlsx",
           "degraded", "parse_fda_warning_letters_xlsx", mode="http", sla_hours=168, country="US", ua=UA_PLAIN,
           routes=(_R("http", "get", "https://www.fda.gov/inspections-compliance-enforcement-and-criminal-investigations/compliance-actions-and-activities/warning-letters/datatables-data?page&_format=xlsx",
                      "parse_fda_warning_letters_xlsx", ua=UA_PLAIN),
                   _R("browser", "browser_job", "https://www.fda.gov/inspections-compliance-enforcement-and-criminal-investigations/compliance-actions-and-activities/warning-letters", "parse_listing")),
           notes="the xlsx export returns 1,000 of 3,680 letters in index order (posted 2021-03 .. 2026-04-14 on 2026-09-16), so it is partial and stale; the page's DataTables ajax view answers 503 from here"),
    Source("fda_import_alerts", "US FDA import alerts", "global", "P0", "https://www.accessdata.fda.gov/cms_ia/default.html", "blocked_temporary", "parse_listing", mode="browser", sla_hours=168, country="US",
           routes=(_R("http", "get", "https://www.accessdata.fda.gov/cms_ia/default.html", "parse_listing", ua=UA_PLAIN),
                   _R("browser", "browser_job", "https://www.accessdata.fda.gov/cms_ia/default.html", "parse_listing")),
           notes="accessdata.fda.gov answered the excessive-requests apology page on 2026-09-16 (abuse detection on this VM's IP)"),
    Source("gleif_press", "GLEIF press releases", "global", "P1", "https://www.gleif.org/en/newsroom/press-releases", "live", "parse_listing", country="GLOBAL", sla_hours=336),
    Source("gleif_news", "GLEIF and LEI news", "global", "P1", "https://www.gleif.org/en/newsroom/gleif-and-lei-news", "live", "parse_listing", country="GLOBAL", sla_hours=336),
    Source("sec_edgar_6k", "US SEC EDGAR current 6-K filings (foreign private issuers, incl. Indian ADRs)", "global", "P2",
           "https://www.sec.gov/cgi-bin/browse-edgar?action=getcurrent&type=6-K&company=&dateb=&owner=include&count=100&output=atom", "live", "parse_sec_atom",
           mode="api", sla_hours=72, country="US", ua=UA_SEC, notes="SEC fair-access policy: a descriptive UA, ≤10 req/s"),
    Source("esma", "ESMA", "global", "P2", "https://www.esma.europa.eu/", "not_built", country="EU"),
    # ── P1: ratings (Phase 3 of the unblocking plan) ────────────────────────────────────────────────────────────
    Source("icra", "ICRA rating actions", "ratings", "P1", "https://www.icra.in/", "live", "parse_listing", sla_hours=72),
    Source("crisil", "CRISIL", "ratings", "P1", "https://www.crisil.com/", "not_built", notes="home has no dated listing; ratings pages are JS"),
    Source("care", "CARE Ratings", "ratings", "P1", "https://www.careratings.com/", "not_built"),
    Source("india_ratings", "India Ratings", "ratings", "P1", "https://www.indiaratings.co.in/", "not_built"),
    # ── P2: news (confirmation, never the sole trigger) ─────────────────────────────────────────────────────────
    Source("reuters", "Reuters", "news", "P2", "https://www.reuters.com/", "waf_blocked", mode="browser", notes="401 CloudFront from this VM"),
    Source("et_stocks", "Economic Times — stocks", "news", "P2", "https://economictimes.indiatimes.com/markets/stocks/rssfeeds/2146842.cms", "live", "parse_rss", mode="api", sla_hours=24),
    Source("bs_companies", "Business Standard — companies", "news", "P2", "https://www.business-standard.com/rss/companies-101.rss", "live", "parse_rss", mode="api", sla_hours=24),
    Source("bs_markets", "Business Standard — markets", "news", "P2", "https://www.business-standard.com/rss/markets-106.rss", "live", "parse_rss", mode="api", sla_hours=24),
    Source("mint_companies", "Mint — companies", "news", "P2", "https://www.livemint.com/rss/companies", "live", "parse_rss", mode="api", sla_hours=24),
    Source("mint_markets", "Mint — markets", "news", "P2", "https://www.livemint.com/rss/markets", "live", "parse_rss", mode="api", sla_hours=24),
    Source("cnbc_market", "CNBC-TV18 — market", "news", "P2", "https://www.cnbctv18.com/commonfeeds/v1/cne/rss/market.xml", "live", "parse_rss", mode="api", sla_hours=24),
    Source("moneycontrol", "Moneycontrol", "news", "P2", "https://www.moneycontrol.com/rss/business.xml", "not_built", notes="RSS stale since 2024-04"),
)
_BY_ID = {s.id: s for s in SOURCES}
assert len(_BY_ID) == len(SOURCES), "duplicate source id"


def get_source(source_id: str) -> Source:
    return _BY_ID[source_id]


def by_status(status: str) -> list[Source]:
    return [s for s in SOURCES if s.status == status]


def runnable() -> list[Source]:
    return [s for s in SOURCES if s.status in RUNNABLE]


def browser_only() -> list[Source]:
    """Sources whose only working route is a browser worker: the monitor queues their jobs instead of fetching."""
    return [s for s in SOURCES if s.status not in RUNNABLE and any(r.mode == "browser" for r in routes_for(s))]
