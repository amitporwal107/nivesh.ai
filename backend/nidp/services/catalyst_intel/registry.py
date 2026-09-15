"""The source universe, in the user's priority order. `status`: live = machine-readable feed wired; listing = HTML
listing page parsed by the generic dated-link extractor; blocked = the host refuses this VM (probe 2026-09-15);
js_rendered = needs a browser; not_built = on the list, no adapter yet."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional


@dataclass(frozen=True)
class Source:
    id: str
    name: str
    klass: str           # regulator | exchange | government | global | ratings | news
    priority: str        # P0..P3
    url: str
    status: str
    adapter: Optional[str] = None       # adapters.<function>
    fetch: str = "get"                  # get | nse_api_days | bse_subcat_days
    country: str = "IN"
    notes: str = ""


SOURCES: tuple[Source, ...] = (
    # ── P0: Indian regulators and exchanges ─────────────────────────────────────────────────────────────────────
    Source("rbi_press", "RBI press releases", "regulator", "P0", "https://www.rbi.org.in/pressreleases_rss.xml", "live", "parse_rss",
           notes="page: https://www.rbi.org.in/Scripts/BS_PressReleaseDisplay.aspx; pubDate is naive IST"),
    Source("rbi_notifications", "RBI notifications / circulars", "regulator", "P0", "https://www.rbi.org.in/notifications_rss.xml", "live", "parse_rss",
           notes="page: https://www.rbi.org.in/Scripts/BS_CircularIndexDisplay.aspx"),
    Source("sebi_rss", "SEBI media, orders, circulars (RSS)", "regulator", "P0", "https://www.sebi.gov.in/sebirss.xml", "live", "parse_rss",
           notes="covers enforcement, recovery, circulars, press; page: https://www.sebi.gov.in/media-and-notifications.html"),
    Source("sebi_press", "SEBI press releases (listing)", "regulator", "P0", "https://www.sebi.gov.in/sebiweb/home/HomeAction.do?doListing=yes&sid=6&ssid=23", "listing", "parse_listing"),
    Source("cci_combination_press", "CCI combination press releases", "regulator", "P0", "https://www.cci.gov.in/combination/press-release", "live", "parse_cci_datatable", fetch="cci_datatable",
           notes="DataTables server-side JSON on the page URL (X-Requested-With); 498 press releases; order_date dd/mm/yyyy"),
    Source("cci_combination_orders", "CCI combination orders (s.31)", "regulator", "P0", "https://www.cci.gov.in/combination/orders-section31", "live", "parse_cci_datatable", fetch="cci_datatable",
           notes="same mechanism; 1,460 orders with party, status, decision date"),
    Source("cci_antitrust_orders", "CCI antitrust orders", "regulator", "P0", "https://www.cci.gov.in/antitrust/orders", "not_built",
           notes="DataTables with a different column set; the JSON call needs its own column list (not yet mapped)"),
    Source("nse_announcements_api", "NSE corporate announcements (API, per calendar day)", "exchange", "P0",
           "https://www.nseindia.com/api/corporate-announcements?index=equities&from_date={d}&to_date={d}", "live", "parse_nse_api", fetch="nse_api_days",
           notes="page: https://www.nseindia.com/companies-listing/corporate-filings-announcements; d = DD-MM-YYYY"),
    Source("nse_announcements_rss", "NSE corporate announcements (RSS)", "exchange", "P0", "https://nsearchives.nseindia.com/content/RSS/Online_announcements.xml", "live", "parse_rss"),
    Source("nse_board_meetings_rss", "NSE board meetings (RSS)", "exchange", "P0", "https://nsearchives.nseindia.com/content/RSS/Board_Meetings.xml", "live", "parse_rss"),
    Source("nse_corporate_actions_rss", "NSE corporate actions (RSS)", "exchange", "P0", "https://nsearchives.nseindia.com/content/RSS/Corporate_action.xml", "live", "parse_rss"),
    Source("bse_announcements_rss", "BSE corporate announcements (RSS)", "exchange", "P0", "https://www.bseindia.com/data/xml/announcements.xml", "live", "parse_rss",
           notes="page: https://www.bseindia.com/corporates/ann.html; ~12,000 items, scrip code per item"),
    Source("bse_subcat_api", "BSE announcements (subcategory API, per calendar day)", "exchange", "P0",
           "https://api.bseindia.com/BseIndiaAPI/api/AnnSubCategoryGetData/w?pageno={page}&strCat=-1&strPrevDate={d}&strScrip=&strSearch=P&strToDate={d}&strType=C&subcategory=-1",
           "live", "parse_bse_subcat", fetch="bse_subcat_days", notes="AnnGetData (used by the staging feed) answers 'No Record Found!' since 2026-09-12; d = YYYYMMDD, 50 rows/page"),
    # ── P0/P1: government ───────────────────────────────────────────────────────────────────────────────────────
    Source("pib", "Press Information Bureau", "government", "P0", "https://pib.gov.in/RssMain.aspx?ModId=6&Lang=2&Regid=3", "not_built",
           notes="RSS answers Hindi titles regardless of Lang; English listing needs the PressReleasePage; PIB Defence = same feed filtered"),
    Source("nhai", "NHAI", "government", "P0", "https://nhai.gov.in/", "js_rendered", notes="home is a JS shell; tenders live on etenders/eprocure"),
    Source("mod", "Ministry of Defence", "government", "P0", "https://mod.gov.in/en", "listing", "parse_listing", notes="/en serves the English what's-new list; root is Hindi"),
    Source("eprocure", "Central Public Procurement Portal", "government", "P0", "https://eprocure.gov.in/eprocure/app", "not_built",
           notes="reachable; tender lists need the per-department search with a session; captcha on detail pages"),
    Source("mnre", "Ministry of New and Renewable Energy", "government", "P1", "https://mnre.gov.in/", "listing", "parse_listing"),
    Source("heavy_industries", "Ministry of Heavy Industries", "government", "P1", "https://www.heavyindustries.gov.in/en", "listing", "parse_listing", notes="/en for English; root is Hindi"),
    Source("mines", "Ministry of Mines", "government", "P1", "https://mines.gov.in/", "not_built", notes="home is a redirect shell (5 KB)"),
    Source("dgft", "DGFT notifications", "government", "P0", "https://www.dgft.gov.in/CP/?opt=notification", "blocked", notes="403 from this VM"),
    Source("mca", "Ministry of Corporate Affairs", "government", "P1", "https://www.mca.gov.in/", "blocked", notes="403 from this VM"),
    Source("ibbi", "IBBI", "regulator", "P1", "https://www.ibbi.gov.in/", "listing", "parse_listing"),
    Source("nclt", "NCLT", "regulator", "P1", "https://nclt.gov.in/", "listing", "parse_listing"),
    Source("cdsco_alerts", "CDSCO alerts", "regulator", "P0", "https://www.cdsco.gov.in/opencms/opencms/en/Alerts/", "listing", "parse_listing"),
    Source("cdsco_notices", "CDSCO public notices", "regulator", "P1", "https://www.cdsco.gov.in/opencms/opencms/en/Notifications/Public-Notices/", "listing", "parse_listing"),
    # ── P1: global ──────────────────────────────────────────────────────────────────────────────────────────────
    Source("fda_warning_letters", "US FDA warning letters", "global", "P0", "https://www.fda.gov/inspections-compliance-enforcement-and-criminal-investigations/compliance-actions-and-activities/warning-letters", "blocked", country="US", notes="404 abuse-detection page from this VM"),
    Source("fda_import_alerts", "US FDA import alerts", "global", "P0", "https://www.fda.gov/industry/actions-enforcement/import-alerts", "blocked", country="US"),
    Source("gleif_press", "GLEIF press releases", "global", "P1", "https://www.gleif.org/en/newsroom/press-releases", "listing", "parse_listing", country="GLOBAL"),
    Source("gleif_news", "GLEIF and LEI news", "global", "P1", "https://www.gleif.org/en/newsroom/gleif-and-lei-news", "listing", "parse_listing", country="GLOBAL"),
    Source("sec_edgar", "US SEC EDGAR", "global", "P2", "https://www.sec.gov/edgar/search/", "not_built", country="US"),
    Source("esma", "ESMA", "global", "P2", "https://www.esma.europa.eu/", "not_built", country="EU"),
    # ── P1: ratings ─────────────────────────────────────────────────────────────────────────────────────────────
    Source("icra", "ICRA rating actions", "ratings", "P1", "https://www.icra.in/", "listing", "parse_listing"),
    Source("crisil", "CRISIL", "ratings", "P1", "https://www.crisil.com/", "not_built", notes="home has no dated listing; ratings pages are JS"),
    Source("care", "CARE Ratings", "ratings", "P1", "https://www.careratings.com/", "not_built"),
    Source("india_ratings", "India Ratings", "ratings", "P1", "https://www.indiaratings.co.in/", "not_built"),
    # ── P2: news (confirmation, never the sole trigger) ─────────────────────────────────────────────────────────
    Source("reuters", "Reuters", "news", "P2", "https://www.reuters.com/", "blocked", notes="401 from this VM"),
    Source("et_stocks", "Economic Times — stocks", "news", "P2", "https://economictimes.indiatimes.com/markets/stocks/rssfeeds/2146842.cms", "live", "parse_rss"),
    Source("bs_companies", "Business Standard — companies", "news", "P2", "https://www.business-standard.com/rss/companies-101.rss", "live", "parse_rss"),
    Source("bs_markets", "Business Standard — markets", "news", "P2", "https://www.business-standard.com/rss/markets-106.rss", "live", "parse_rss"),
    Source("mint_companies", "Mint — companies", "news", "P2", "https://www.livemint.com/rss/companies", "live", "parse_rss"),
    Source("mint_markets", "Mint — markets", "news", "P2", "https://www.livemint.com/rss/markets", "live", "parse_rss"),
    Source("cnbc_market", "CNBC-TV18 — market", "news", "P2", "https://www.cnbctv18.com/commonfeeds/v1/cne/rss/market.xml", "live", "parse_rss"),
    Source("moneycontrol", "Moneycontrol", "news", "P2", "https://www.moneycontrol.com/rss/business.xml", "not_built", notes="RSS stale since 2024-04"),
)
_BY_ID = {s.id: s for s in SOURCES}


def get_source(source_id: str) -> Source:
    return _BY_ID[source_id]


def by_status(status: str) -> list[Source]:
    return [s for s in SOURCES if s.status == status]
