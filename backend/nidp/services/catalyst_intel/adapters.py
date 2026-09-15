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

_FORMATS = ("%a, %d %b %Y %H:%M:%S", "%d %b, %Y", "%d-%b-%Y %H:%M:%S", "%d-%b-%Y", "%a, %d %b %Y %H:%M:%S %z", "%Y-%m-%dT%H:%M:%S.%f", "%Y-%m-%dT%H:%M:%S",
            "%Y-%m-%d %H:%M:%S", "%Y-%m-%d", "%d-%m-%Y", "%d/%m/%Y", "%d.%m.%Y", "%b %d, %Y", "%d %b %Y", "%d %B %Y", "%d %B, %Y", "%B %d, %Y", "%Y-%b-%d", "%d-%b-%y")


def parse_feed_datetime(text: Optional[str], default_tz=IST) -> Optional[datetime]:
    if not text:
        return None
    t = re.sub(r"\s+", " ", text.strip()).replace("Sept ", "Sep ")
    t = re.sub(r"(\d)(st|nd|rd|th)\b", r"\1", t)
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
