"""Turn a source's response into raw events. A raw event is a dict with: source_id, source_event_id, url, title, summary,
category, symbol, scrip_code, entity_text, published_at (aware datetime, IST for Indian sources), received_at, hash."""
from __future__ import annotations

import hashlib
import json
import re
from datetime import date, datetime, timedelta, timezone
from html import unescape
from html.parser import HTMLParser
from typing import Optional
from urllib.parse import urljoin
import xml.etree.ElementTree as ET

from ..tpd_model.event_gate import IST

_FORMATS = ("%a, %d %b %Y %H:%M:%S", "%d %b, %Y", "%d-%b-%Y %H:%M:%S", "%d-%b-%Y %I:%M %p", "%d-%b-%Y", "%a, %d %b %Y %H:%M:%S %z", "%Y-%m-%dT%H:%M:%S.%f", "%Y-%m-%dT%H:%M:%S%z",
            "%Y-%m-%dT%H:%M:%S", "%Y-%m-%d %H:%M:%S", "%Y-%m-%d", "%d-%m-%Y", "%d/%m/%Y", "%d.%m.%Y", "%b %d, %Y", "%d %b %Y", "%d %B %Y", "%d %B, %Y", "%B %d, %Y", "%Y-%b-%d", "%d-%b-%y", "%Y%m%d")
_US_TZ = {" EDT": " -0400", " EST": " -0500", " PDT": " -0700", " PST": " -0800", " CDT": " -0500", " CST": " -0600", " GMT": " +0000", " UTC": " +0000"}


def parse_feed_datetime(text: Optional[str], default_tz=IST) -> Optional[datetime]:
    if not text:
        return None
    t = re.sub(r"\s+", " ", text.strip()).replace("Sept ", "Sep ")
    t = re.sub(r"(\d)(st|nd|rd|th)\b", r"\1", t)
    for name, off in _US_TZ.items():                     # FDA / SEC feeds: "18:15:00 EDT"
        if t.endswith(name):
            t = t[: -len(name)] + off
    for fmt in _FORMATS:
        try:
            d = datetime.strptime(t, fmt)
        except ValueError:
            continue
        return d if d.tzinfo else d.replace(tzinfo=default_tz)
    m = re.match(r"(.+?) \+0530$", t)          # SEBI: "14 Sep, 2026 +0530"
    if m:
        return parse_feed_datetime(m.group(1), default_tz)
    return None


def _hash(*parts) -> str:
    return hashlib.sha256("\x1f".join(str(p or "") for p in parts).encode()).hexdigest()


def _event(source_id, url, title, published_at, received_at, summary=None, category=None, symbol=None, scrip_code=None, entity_text=None, source_event_id=None) -> dict:
    title = unescape(re.sub(r"\s+", " ", title or "")).strip()
    summary = unescape(re.sub(r"<[^>]+>", " ", summary or "")); summary = re.sub(r"\s+", " ", summary).strip()[:2000] or None
    return {"source_id": source_id, "source_event_id": source_event_id, "url": url, "title": title, "summary": summary, "category": category,
            "symbol": symbol, "scrip_code": scrip_code, "entity_text": entity_text, "published_at": published_at, "received_at": received_at,
            "hash": _hash(source_id, url, title, published_at.isoformat() if published_at else "")}


def parse_rss(raw: bytes, received_at: datetime, source_id: str) -> list[dict]:
    root = ET.fromstring(raw)
    out = []
    for it in root.iter("item"):
        g = {c.tag.split("}")[-1]: (c.text or "").strip() for c in it}
        pub = parse_feed_datetime(g.get("pubDate") or g.get("date"))
        title, link = g.get("title", ""), g.get("link", "")
        scrip, entity, symbol = g.get("scripcode"), None, None
        if source_id.startswith("bse_"):
            m = re.match(r"(.*?)\s*\((\d{6})\)\s*$", title)
            if m:
                entity, scrip = m.group(1).strip(), m.group(2)
        elif source_id.startswith("nse_"):
            entity = title.split(" - Ex-Date")[0].strip()
        out.append(_event(source_id, link, title, pub, received_at, summary=g.get("description"), scrip_code=scrip, entity_text=entity, symbol=symbol))
    return out


def parse_nse_api(raw: bytes, received_at: datetime, source_id: str = "nse_announcements_api") -> list[dict]:
    rows = json.loads(raw)
    rows = rows if isinstance(rows, list) else rows.get("data", [])
    out = []
    for r in rows:
        pub = parse_feed_datetime(r.get("an_dt") or r.get("sort_date"))
        att = r.get("attchmntFile") or ""
        out.append(_event(source_id, att or "https://www.nseindia.com/companies-listing/corporate-filings-announcements", f"{r.get('symbol')}: {r.get('desc')}", pub, received_at,
                          summary=r.get("attchmntText"), category=r.get("desc"), symbol=r.get("symbol"), entity_text=r.get("sm_name"), source_event_id=r.get("seq_id")))
    return out


def parse_bse_subcat(raw: bytes, received_at: datetime, source_id: str = "bse_subcat_api") -> list[dict]:
    d = json.loads(raw)
    rows = d.get("Table", []) if isinstance(d, dict) else []
    out = []
    for r in rows:
        pub = parse_feed_datetime(r.get("NEWS_DT") or r.get("DT_TM"))
        att = r.get("ATTACHMENTNAME") or ""
        url = f"https://www.bseindia.com/xml-data/corpfiling/AttachLive/{att}" if att else f"https://www.bseindia.com/corporates/ann.html#{r.get('NEWSID')}"
        out.append(_event(source_id, url, r.get("NEWSSUB") or r.get("HEADLINE") or "", pub, received_at, summary=r.get("HEADLINE") or r.get("MORE"),
                          category=r.get("CATEGORYNAME") or r.get("SUBCATNAME"), scrip_code=str(r.get("SCRIP_CD") or ""), entity_text=r.get("SLONGNAME"), source_event_id=r.get("NEWSID")))
    return out


_DATE_RX = re.compile(r"\b(\d{1,2}(?:st|nd|rd|th)?[-/. ](?:\d{1,2}|[A-Za-z]{3,9})[-/. ,]+\d{4}|\d{4}-(?:\d{2}|[A-Za-z]{3})-\d{2}|[A-Za-z]{3,9}\s+\d{1,2}(?:st|nd|rd|th)?,?\s+\d{4})\b")
_URL_DATE_RX = re.compile(r"(20\d{2})[-/_](\d{2})[-/_](\d{2})")
_SKIP_HREF = re.compile(r"^(#|javascript:|mailto:|tel:)|(twitter|facebook|youtube|instagram|linkedin|whatsapp)\.com", re.I)


class _Blocks(HTMLParser):
    """Segments a page into small blocks (li / tr / article / p / small divs) and collects the anchors and text in each."""
    OPEN = {"li", "tr", "article", "p", "h2", "h3", "h4"}

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.blocks: list[dict] = []; self.cur = None; self.href = None; self.a_text = []

    def _start(self):
        if self.cur and (self.cur["links"] or self.cur["text"].strip()):
            self.blocks.append(self.cur)
        self.cur = {"links": [], "text": ""}

    def handle_starttag(self, tag, attrs):
        if tag in self.OPEN:
            self._start()
        if tag == "time":
            dt = dict(attrs).get("datetime")
            if dt:
                if self.cur is None:
                    self._start()
                self.cur["text"] += " " + dt[:10] + " "
        if tag == "a":
            href = dict(attrs).get("href")
            if href and not _SKIP_HREF.search(href):
                self.href, self.a_text = href, []
        if tag == "br" and self.cur is not None:
            self.cur["text"] += " "

    def handle_endtag(self, tag):
        if tag == "a" and self.href is not None:
            if self.cur is None:
                self._start()
            self.cur["links"].append((self.href, " ".join(self.a_text).strip()))
            self.href = None
        if tag in self.OPEN and self.cur is not None:
            self._start(); self.cur = None if tag in ("tr", "li") else self.cur

    def handle_data(self, data):
        if self.href is not None:
            self.a_text.append(data.strip())
        if self.cur is None:
            self._start()
        self.cur["text"] += data

    def close(self):
        super().close(); self._start()


def parse_listing(raw: bytes, received_at: datetime, source_id: str, base_url: str) -> list[dict]:
    """Generic dated-link extractor for listing pages: a block that holds a link with a real title and a date (in its
    text or in the link's path) becomes an event; menus, social links and undated links are ignored."""
    p = _Blocks(); p.feed(raw.decode("utf-8", errors="replace")); p.close()
    blocks = [{"links": b["links"], "text": re.sub(r"\s+", " ", b["text"]).strip()} for b in p.blocks]
    dates = [(_DATE_RX.search(b["text"]) or _DATE_RX.search("")) for b in blocks]
    dates = [m.group(1) if m else None for m in dates]
    # a date that sits in its own block (a <span>, a <td>, a "what's new" line) belongs to the link block next to it
    for i, b in enumerate(blocks):
        if b["links"] and dates[i] is None:
            for j in (i + 1, i - 1):
                if 0 <= j < len(blocks) and dates[j] and not blocks[j]["links"]:
                    dates[i] = dates[j]; break
    def own_title(text: str) -> str:
        t = _DATE_RX.sub(" ", text); t = re.sub(r"^\s*\d{1,4}\s+", "", t); t = re.sub(r"\b\d+(\.\d+)?\s*[KM]B\b", " ", t)
        return re.sub(r"\s+", " ", t).strip()

    out, seen = [], set()
    for i, (b, d) in enumerate(zip(blocks, dates)):
        text = b["text"]
        prev_title = own_title(blocks[i - 1]["text"]) if i and dates[i - 1] is None and not blocks[i - 1]["links"] else ""
        links = list(b["links"])
        if not links and d and len(own_title(text)) >= 12:
            links = [(base_url, own_title(text))]          # a dated headline with no link of its own (a ministry's "what's new" line)
        for href, a_text in links:
            title = a_text or ""
            own = _DATE_RX.search(title)                      # a card that carries its own date (GLEIF, IBBI): it wins over the block's
            link_date = own.group(1) if own else None
            if own:
                title = re.sub(r"\s+", " ", title.replace(own.group(1), " ")).strip()
            if len(title) < 12:
                # icon links (a PDF glyph) and "read more" links carry no title: the row's own text, minus its serial, date and
                # size, is the title; if that is empty too, the undated block just before it is (a heading over a date line)
                title = own_title(text)
                if len(title) < 12 and len(prev_title) >= 12:
                    title = prev_title
            if len(title) < 12 or len(title) > 400:
                continue
            pub = parse_feed_datetime(link_date or d) if (link_date or d) else None
            title = re.sub(r"^(?:read more|और पढ़ें)\s*", "", title, flags=re.I).strip()
            if pub is None:
                mu = _URL_DATE_RX.search(href)
                if mu:
                    try:
                        pub = datetime(int(mu.group(1)), int(mu.group(2)), int(mu.group(3)), tzinfo=IST)
                    except ValueError:
                        pub = None
            if pub is None:
                continue
            url = urljoin(base_url, href)
            key = (url, title)
            if key in seen:
                continue
            seen.add(key)
            out.append(_event(source_id, url, title, pub, received_at, summary=text[:500]))
    return out


_TAG_RX = re.compile(r"<[^>]+>")
_HREF_RX = re.compile(r'href="([^"]+)"')


def parse_cci_datatable(raw: bytes, received_at: datetime, source_id: str) -> list[dict]:
    """CCI listings (DataTables server-side JSON): press releases carry title/order_date/files; combination orders carry
    party_name/order_status/decision_date/combination_no and order/summary files."""
    d = json.loads(raw)
    out = []
    for r in d.get("data", []):
        if "party_name" in r:                                   # combination orders
            title = f"{r.get('order_type') or 'Order'} {r.get('combination_no') or ''}: {r.get('party_name') or ''}".strip()
            pub = parse_feed_datetime(r.get("decision_date") or r.get("date_of_order") or r.get("notification_date"))
            files = _HREF_RX.findall(r.get("order_files") or "") + _HREF_RX.findall(r.get("summary_files") or "")
            url = files[0] if files else f"https://www.cci.gov.in/combination/orders-section31#dt_row_{r.get('id')}"
            out.append(_event(source_id, url, title, pub, received_at, summary=unescape(_TAG_RX.sub(" ", r.get("description") or "")),
                              category=r.get("order_status"), entity_text=r.get("party_name"), source_event_id=str(r.get("id"))))
        else:                                                   # press releases
            title = unescape(_TAG_RX.sub(" ", r.get("title") or "")).strip()
            pub = parse_feed_datetime(r.get("order_date"))
            files = _HREF_RX.findall(r.get("files") or "")
            url = files[0] if files else f"https://www.cci.gov.in/combination/press-release#dt_row_{r.get('id')}"
            out.append(_event(source_id, url, title, pub, received_at, summary=unescape(_TAG_RX.sub(" ", r.get("description") or "")), source_event_id=str(r.get("id"))))
    return out


# ── Phase 1 adapters (2026-09-16): PIB postback, NHAI API, CPPP tables, SEC Atom, openFDA, FDA xlsx export ───────────
_PIB_FIELDS = ("__VIEWSTATE", "__VIEWSTATEGENERATOR", "__EVENTVALIDATION", "__VIEWSTATEENCRYPTED")


def pib_form_state(raw: bytes) -> dict:
    """The ASP.NET hidden fields a postback must echo (they change on every response)."""
    h = raw.decode("utf-8", errors="replace")
    out = {}
    for f in _PIB_FIELDS:
        m = re.search(r'id="%s" value="([^"]*)"' % f, h)
        out[f] = m.group(1) if m else ""
    return out


def pib_postback_body(state: dict, day: date, region: str = "3", lang: str = "1", ministry: str = "0") -> bytes:
    """The day-select postback of allRel.aspx: region 3 = PIB Delhi, lang 1 = English, ministry 0 = all."""
    from urllib.parse import urlencode

    form = {"__EVENTTARGET": "ctl00$ContentPlaceHolder1$ddlday", "__EVENTARGUMENT": "", "__LASTFOCUS": "", **{k: state.get(k, "") for k in _PIB_FIELDS},
            "ctl00$Bar1$ddlregion": region, "ctl00$Bar1$ddlLang": lang, "ctl00$ContentPlaceHolder1$hydregionid": region, "ctl00$ContentPlaceHolder1$hydLangid": lang,
            "ctl00$ContentPlaceHolder1$ddlMinistry": ministry, "ctl00$ContentPlaceHolder1$ddlday": str(day.day), "ctl00$ContentPlaceHolder1$ddlMonth": str(day.month),
            "ctl00$ContentPlaceHolder1$ddlYear": str(day.year)}
    return urlencode(form).encode()


_PIB_ITEM_RX = re.compile(r"<h3[^>]*>(.*?)</h3>|<a[^>]*href=['\"]([^'\"]*PressReleaseDetail\.aspx\?PRID=(\d+))['\"][^>]*>(.*?)</a>", re.S | re.I)


def parse_pib_day(raw: bytes, received_at: datetime, source_id: str, day: date, base_url: str = "https://www.pib.gov.in/") -> list[dict]:
    """One event per release on the day listing, grouped under its ministry heading. The listing carries the day
    only, so published_at is the end of that day (conservative for any 'did it precede the move' question)."""
    h = raw.decode("utf-8", errors="replace")
    i = h.find('class="content-area"')
    seg = re.sub(r"</?(?:i|b|em|strong|u|sup|sub)\b[^>]*>", "", h[i:] if i >= 0 else h)   # inline tags appear inside title='…' attributes
    out, ministry, seen = [], None, set()
    for m in _PIB_ITEM_RX.finditer(seg):
        if m.group(1) is not None:
            ministry = unescape(re.sub(r"<[^>]+>", " ", m.group(1))).strip() or ministry
            continue
        href, prid, text = m.group(2), m.group(3), m.group(4)
        if prid in seen:
            continue
        seen.add(prid)
        title = unescape(re.sub(r"<[^>]+>", " ", text)).strip()
        pub = datetime(day.year, day.month, day.day, 23, 59, 59, tzinfo=IST)
        out.append(_event(source_id, urljoin(base_url, href), title, pub, received_at, summary=f"PIB Delhi | {ministry or 'ministry unknown'} | day precision (listing has no time)",
                          category=ministry, source_event_id=prid))
    return out


_NHAI_CATEGORY = {"news": "news", "press-release": "press_release", "tenderlist": "tender"}


def parse_nhai_api(raw: bytes, received_at: datetime, source_id: str) -> list[dict]:
    """nhai.gov.in/nhai/api/{news|press-release|tenderlist}: {"list": [{id, title, <date field>, upload_file: [{uf_target_id}], ...}]}"""
    d = json.loads(raw)
    rows = d.get("list", []) if isinstance(d, dict) else []
    cat = "press_release" if "press" in source_id else "tender" if "tender" in source_id else "news"
    out = []
    for r in rows:
        files = r.get("upload_file") or []
        pdf = next((f.get("uf_target_id") for f in files if f.get("uf_target_id")), None)
        pub = parse_feed_datetime(r.get("a_date_val") or r.get("ar_dt_val") or r.get("publish_date") or r.get("created") or r.get("date"))
        title = r.get("title") or ""
        if cat == "tender":
            tno = r.get("tender_no") or ""
            close = parse_feed_datetime(r.get("bid_submission_end_date")); opn = parse_feed_datetime(r.get("bid_opening_date"))
            summary = f"tender {tno}; bid closes {close.date().isoformat() if close else '?'}; opens {opn.date().isoformat() if opn else '?'}"
            out.append(_event(source_id, pdf or f"https://nhai.gov.in/#/tenders/{r.get('id')}", title, pub, received_at, summary=summary, category=cat, entity_text=tno or None, source_event_id=str(r.get("id"))))
        else:
            src = r.get("source_val") or (files[0].get("description") if files else None)
            summary = " | ".join(x for x in (src, re.sub(r"<[^>]+>", " ", r.get("body_value") or "").strip()) if x) or None
            out.append(_event(source_id, pdf or f"https://nhai.gov.in/#/{cat.replace('_', '-')}/{r.get('id')}", title, pub, received_at, summary=summary, category=cat, source_event_id=str(r.get("id"))))
    return out


def cppp_page_url(base_url: str, page: int) -> str:
    """CPPP pages beyond the first are addressed by a base64 of '<base>?page=n' in the ?url= parameter."""
    import base64
    from urllib.parse import quote

    if page <= 1:
        return base_url
    return f"{base_url}?url={quote(base64.b64encode(f'{base_url}?page={page}'.encode()).decode(), safe='')}"


_TD_RX = re.compile(r"<td[^>]*>(.*?)</td>", re.S | re.I)
_TR_RX = re.compile(r"<tr[^>]*>(.*?)</tr>", re.S | re.I)
_A_RX = re.compile(r"<a[^>]*href=\"([^\"]+)\"[^>]*>(.*?)</a>", re.S | re.I)


def parse_cppp_table(raw: bytes, received_at: datetime, source_id: str, base_url: str) -> list[dict]:
    """The CPPP listing tables: Sl.No | e-Published Date | Bid Submission Closing | Tender Opening | Title/Ref/Id | Organisation | Corrigendum."""
    h = raw.decode("utf-8", errors="replace")
    out, seen = [], set()
    for tr in _TR_RX.findall(h):
        tds = _TD_RX.findall(tr)
        if len(tds) < 6:
            continue
        pub = parse_feed_datetime(re.sub(r"<[^>]+>", " ", tds[1]).strip())
        if pub is None:
            continue
        a = _A_RX.search(tds[4])
        if not a:
            continue
        href, title = urljoin(base_url, unescape(a.group(1))), unescape(re.sub(r"<[^>]+>", " ", a.group(2))).strip()
        rest = unescape(re.sub(r"<[^>]+>", " ", tds[4][a.end():])).strip().strip("/")
        parts = [p for p in rest.split("/") if p.strip()]
        tid = parts[-1].strip() if parts and parts[-1].strip().isdigit() else None
        ref = "/".join(p.strip() for p in parts[:-1]) if tid else rest
        org = unescape(re.sub(r"<[^>]+>", " ", tds[5])).strip()
        close = parse_feed_datetime(re.sub(r"<[^>]+>", " ", tds[2]).strip()); opn = parse_feed_datetime(re.sub(r"<[^>]+>", " ", tds[3]).strip())
        cat = "corrigendum" if "corrig" in href or "corrig" in base_url else "tender"
        if href in seen:
            continue
        seen.add(href)
        summary = f"{org}; ref {ref or '-'}; bid closes {close.date().isoformat() if close else '?'}; opens {opn.date().isoformat() if opn else '?'}"
        out.append(_event(source_id, href, title, pub, received_at, summary=summary, category=cat, entity_text=org or None, source_event_id=tid or href.rsplit('/', 1)[-1][:40]))
    return out


_ATOM = "{http://www.w3.org/2005/Atom}"


def parse_sec_atom(raw: bytes, received_at: datetime, source_id: str) -> list[dict]:
    """EDGAR current-filings Atom: title '6-K - ISSUER (CIK) (Filer)', link to the filing index, updated, id with the accession number."""
    root = ET.fromstring(raw)
    out = []
    for e in root.iter(_ATOM + "entry"):
        title = (e.findtext(_ATOM + "title") or "").strip()
        link = e.find(_ATOM + "link"); href = link.get("href") if link is not None else ""
        cat = e.find(_ATOM + "category"); form = (cat.get("term") if cat is not None else None) or title.split(" - ")[0]
        m = re.match(r"^(?P<form>[^ ]+(?:/A)?) - (?P<name>.*?) \((?P<cik>\d{10})\) \((?P<role>[^)]+)\)\s*$", title)
        name, cik, role = (m.group("name"), m.group("cik"), m.group("role")) if m else (title, None, None)
        acc = re.search(r"accession-number=([\d-]+)", e.findtext(_ATOM + "id") or "")
        acc = acc.group(1) if acc else (re.search(r"/(\d{10}-\d{2}-\d{6})", href).group(1) if re.search(r"/(\d{10}-\d{2}-\d{6})", href) else None)
        pub = parse_feed_datetime(e.findtext(_ATOM + "updated"), default_tz=timezone.utc)
        summ = re.sub(r"<[^>]+>", " ", e.findtext(_ATOM + "summary") or "")
        summary = "; ".join(x for x in (f"CIK {cik}" if cik else None, f"role {role}" if role else None, summ.strip() or None) if x)
        out.append(_event(source_id, href, f"{form}: {name}", pub, received_at, summary=summary, category=form, entity_text=name, source_event_id=acc))
    return out


def parse_openfda_enforcement(raw: bytes, received_at: datetime, source_id: str) -> list[dict]:
    """openFDA enforcement (recalls): one event per recall_number; report_date YYYYMMDD; the recalling firm is the entity."""
    d = json.loads(raw)
    kind = "device" if "device" in source_id else "food" if "food" in source_id else "drug"
    out = []
    for r in d.get("results", []):
        rn = r.get("recall_number") or ""
        firm = (r.get("recalling_firm") or "").strip()
        pub = parse_feed_datetime(r.get("report_date") or r.get("recall_initiation_date"), default_tz=timezone.utc)
        product = re.sub(r"\s+", " ", r.get("product_description") or "").strip()
        title = f"{r.get('classification') or 'Recall'} recall: {firm} — {product[:80]}"
        summary = "; ".join(x for x in (r.get("reason_for_recall"), product, f"status {r.get('status')}" if r.get("status") else None,
                                        f"{r.get('city') or ''} {r.get('state') or ''} {r.get('country') or ''}".strip() or None) if x)
        out.append(_event(source_id, f"https://api.fda.gov/{kind}/enforcement.json?search=recall_number:%22{rn}%22", title, pub, received_at, summary=summary,
                          category=r.get("classification"), entity_text=firm or None, source_event_id=rn or None))
    return out


def _xlsx_rows(raw: bytes) -> list[list[str]]:
    import io
    import zipfile

    z = zipfile.ZipFile(io.BytesIO(raw))
    strings = []
    if "xl/sharedStrings.xml" in z.namelist():
        ss = z.read("xl/sharedStrings.xml").decode("utf-8", "replace")
        strings = [unescape(re.sub(r"<[^>]+>", "", s)) for s in re.findall(r"<si>(.*?)</si>", ss, flags=re.S)]
    sheet = next((n for n in z.namelist() if n.startswith("xl/worksheets/sheet")), None)
    if not sheet:
        return []
    sh = z.read(sheet).decode("utf-8", "replace")
    rows = []
    for r in re.findall(r"<row[^>]*>(.*?)</row>", sh, flags=re.S):
        cells = []
        for m in re.finditer(r'<c r="[A-Z]+\d+"([^>]*)>(?:<v>(.*?)</v>)?(?:<is><t>(.*?)</t></is>)?', r):
            attrs, v, t = m.groups()
            cells.append(strings[int(v)] if 't="s"' in attrs and v is not None and v.isdigit() and int(v) < len(strings) else (v if v is not None else (t or "")))
        rows.append(cells)
    return rows


def parse_fda_warning_letters_xlsx(raw: bytes, received_at: datetime, source_id: str) -> list[dict]:
    """The warning-letters DataTables export (xlsx): Posted Date | Letter Issue Date | Company Name | Issuing Office | Subject | ...
    Partial (first 1,000 rows, index order) — the source is registered as degraded for that reason."""
    rows = _xlsx_rows(raw)
    if not rows:
        return []
    head = [c.strip().lower() for c in rows[0]]
    def col(name):
        return next((i for i, c in enumerate(head) if name in c), None)
    ip, ii, ic, io_, isub = col("posted"), col("issue"), col("company"), col("office"), col("subject")
    if ic is None or ip is None:
        return []
    page = "https://www.fda.gov/inspections-compliance-enforcement-and-criminal-investigations/compliance-actions-and-activities/warning-letters"
    out = []
    for r in rows[1:]:
        if len(r) <= max(ip, ic):
            continue
        try:
            posted = datetime.strptime(r[ip].strip(), "%m/%d/%Y").replace(tzinfo=timezone.utc)
        except ValueError:
            continue
        company = r[ic].strip()
        issued = r[ii].strip() if ii is not None and ii < len(r) else ""
        subject = r[isub].strip() if isub is not None and isub < len(r) else ""
        office = r[io_].strip() if io_ is not None and io_ < len(r) else ""
        slug = re.sub(r"[^a-z0-9]+", "-", f"{company} {issued}".lower()).strip("-")
        out.append(_event(source_id, f"{page}#{slug}", f"FDA warning letter: {company} — {subject[:90]}", posted, received_at,
                          summary=f"issued {issued}; {office}; {subject}", category=subject or None, entity_text=company or None, source_event_id=slug))
    return out
