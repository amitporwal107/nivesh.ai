"""Calendar-day source monitor: fetch every runnable source through its routes, store new raw events, keep per-source
health, queue browser jobs for what HTTP cannot reach, and write a run manifest with an honest coverage score.

    python -m nidp.services.catalyst_intel.monitor --home /app/research/tpd3_forward/events [--only rbi_press,...] [--back 5]

Runs on every calendar day (cron, 7 days a week); the exchange day APIs are re-queried over a rolling window of
calendar days and deduplicated, so late publication, outages and holidays cannot lose a filing silently.

Routes are tried in order (PRIMARY egress → SECONDARY egress → BROWSER job). A source served only through the secondary
egress is recorded as live_secondary, never live; SOURCE_COVERAGE_SCORE gives it partial credit. A source that no HTTP
route can reach gets a browser job in <home>/browser_jobs/pending and keeps its most specific failure as its status.
"""
from __future__ import annotations

import argparse
import json
import logging
import time as _time
from collections import Counter
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Callable, Optional

from ..tpd_model.event_gate import IST
from . import adapters
from .browser_jobs import ADAPTER_NEEDS_BASE_URL, enqueue, ingest_results
from .registry import RUNNABLE, SOURCES, Route, Source, get_source, routes_for
from .transports import HttpTransport, classify, multipart

logger = logging.getLogger(__name__)
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36"   # kept for callers that import it
OK_OBSERVED = ("live", "live_secondary", "live_browser", "empty")
NOT_FAILURES = OK_OBSERVED + ("stale", "degraded", "queued")
FAIL_PRECEDENCE = ("waf_blocked", "captcha_gated", "session_required", "blocked_temporary", "forbidden", "unauthorized", "not_found", "server_error",
                   "http_error", "adapter_error", "empty_response", "unreachable", "queued")
WEIGHTS = {"P0": 4.0, "P1": 2.0, "P2": 1.0, "P3": 0.5}
CREDIT = {"live": 1.0, "live_browser": 1.0, "empty": 1.0, "live_secondary": 0.75, "degraded": 0.5, "stale": 0.25}


def window_days(today: date, back: int = 5) -> list[date]:
    """The last `back` calendar days ending today — weekends and holidays included, on purpose."""
    return [today - timedelta(days=k) for k in range(back - 1, -1, -1)]


class RouteFailed(Exception):
    def __init__(self, observed: str, detail: str = ""):
        super().__init__(f"{observed}: {detail}" if detail else observed); self.observed, self.detail = observed, detail


@dataclass
class FetchResult:
    events: list = field(default_factory=list)
    route: Optional[Route] = None
    observed: str = "unreachable"
    attempts: list = field(default_factory=list)
    error: Optional[str] = None


def _ok(transport, route: Route, url: str, **kw):
    r = transport.request(route, url, **kw)
    obs = classify(r)
    if obs != "ok":
        raise RouteFailed(obs, f"HTTP {r.status} {url[:120]}")
    return r


def _parse(route: Route, raw: bytes, received_at: datetime, source: Source, **kw) -> list[dict]:
    fn = getattr(adapters, route.adapter)
    if route.adapter in ADAPTER_NEEDS_BASE_URL:
        kw.setdefault("base_url", route.url)
    try:
        return fn(raw, received_at=received_at, source_id=source.id, **kw)
    except Exception as e:  # noqa: BLE001 — a parse failure is a route failure, reported as such
        raise RouteFailed("adapter_error", f"{type(e).__name__}: {str(e)[:160]}") from e


def _run_route(source: Source, route: Route, days: list[date], received_at: datetime, transport) -> list[dict]:
    if route.fetch == "get":
        return _parse(route, _ok(transport, route, route.url, headers={"Referer": route.url}).body, received_at, source)
    if route.fetch == "nse_api_days":
        try:
            transport.request(route, "https://www.nseindia.com/", timeout=20)
        except Exception:  # noqa: BLE001 — the API answers without the cookie from this host
            pass
        out = []
        for d in days:
            r = _ok(transport, route, route.url.format(d=d.strftime("%d-%m-%Y")), headers={"Referer": "https://www.nseindia.com/companies-listing/corporate-filings-announcements"})
            out += _parse(route, r.body, received_at, source); _time.sleep(1.0)
        return out
    if route.fetch == "cci_datatable":
        q = ("?draw=1&columns%5B0%5D%5Bdata%5D=DT_RowIndex&columns%5B1%5D%5Bdata%5D=title&columns%5B2%5D%5Bdata%5D=order_date&columns%5B3%5D%5Bdata%5D=files"
             "&order%5B0%5D%5Bcolumn%5D=0&order%5B0%5D%5Bdir%5D=desc&start=0&length=50&searchString=&fromdate=&todate=")
        r = _ok(transport, route, route.url + q, headers={"Referer": route.url, "X-Requested-With": "XMLHttpRequest", "Accept": "application/json, text/javascript, */*; q=0.01"})
        return _parse(route, r.body, received_at, source)
    if route.fetch == "bse_subcat_days":
        out = []
        for d in days:
            for page in range(1, 40):
                r = _ok(transport, route, route.url.format(d=d.strftime("%Y%m%d"), page=page), headers={"Referer": "https://www.bseindia.com/corporates/ann.html"})
                rows = _parse(route, r.body, received_at, source); out += rows
                if len(rows) < 50:
                    break
                _time.sleep(0.5)
        return out
    if route.fetch == "pib_days":
        form = _ok(transport, route, route.url, headers={"Referer": route.url})
        state = adapters.pib_form_state(form.body)
        if not state.get("__VIEWSTATE"):
            raise RouteFailed("adapter_error", "no __VIEWSTATE on the PIB form page")
        out = []
        for d in days:
            r = _ok(transport, route, route.url, data=adapters.pib_postback_body(state, d), headers={"Referer": route.url, "Content-Type": "application/x-www-form-urlencoded"})
            out += _parse(route, r.body, received_at, source, day=d)
            state = adapters.pib_form_state(r.body) or state; _time.sleep(1.0)
        return out
    if route.fetch == "nhai_api":
        body, ctype = multipart({"language": "en", "index": "0", "totalrecord": "50"})
        r = _ok(transport, route, route.url, data=body, headers={"Content-Type": ctype, "Referer": "https://nhai.gov.in/", "Origin": "https://nhai.gov.in", "Accept": "application/json, text/plain, */*"})
        return _parse(route, r.body, received_at, source)
    if route.fetch == "cppp_pages":
        out = []
        for page in range(1, max(1, route.pages) + 1):
            r = _ok(transport, route, adapters.cppp_page_url(route.url, page), headers={"Referer": route.url})
            out += _parse(route, r.body, received_at, source)
            if page < route.pages:
                _time.sleep(1.5)
        return out
    raise ValueError(f"unknown fetch mode {route.fetch}")


def most_specific(attempts: list[dict]) -> str:
    seen = [a["observed"] for a in attempts]
    for o in FAIL_PRECEDENCE:
        if o in seen:
            return o
    return seen[-1] if seen else "unreachable"


def _naive(dt: Optional[datetime]) -> Optional[datetime]:
    if dt is None:
        return None
    return dt.astimezone(IST).replace(tzinfo=None) if dt.tzinfo else dt


def observe(fetched: int, http_ok: bool, route_egress: str, last_ok_at: Optional[datetime], now: datetime, sla_hours: float) -> str:
    """What a successful route means: rows → live (or live_secondary through the proxy); no rows → empty while the
    last non-empty fetch is within the SLA, stale beyond it (or when the source has never delivered a row)."""
    if not http_ok:
        return "unreachable"
    if fetched > 0:
        return "live_secondary" if route_egress == "secondary" else "live_browser" if str(route_egress).startswith("browser") else "live"
    if last_ok_at is not None and (_naive(now) - _naive(last_ok_at)) <= timedelta(hours=sla_hours):
        return "empty"
    return "stale"


class Health:
    """Per-source memory across runs: <home>/health.json."""

    def __init__(self, home: Path):
        self.path = Path(home) / "health.json"
        self.data: dict = json.loads(self.path.read_text()) if self.path.exists() else {}

    def get(self, source_id: str) -> dict:
        return self.data.get(source_id, {})

    def last_ok_at(self, source_id: str) -> Optional[datetime]:
        v = self.get(source_id).get("last_ok_at")
        return datetime.fromisoformat(v) if v else None

    def record(self, source_id: str, observed: str, fetched: int, at: datetime, route: Optional[str], error: Optional[str] = None) -> dict:
        h = self.data.setdefault(source_id, {"consecutive_failures": 0, "last_ok_at": None})
        h.update(last_observed=observed, last_run_at=at.isoformat(), last_fetched=fetched, last_route=route, last_error=error)
        if observed in OK_OBSERVED or observed in ("stale", "degraded"):
            h["consecutive_failures"] = 0
            if fetched > 0:
                h["last_ok_at"] = at.isoformat()
        elif observed != "queued":
            h["consecutive_failures"] = int(h.get("consecutive_failures", 0)) + 1
        return h

    def observed_map(self) -> dict[str, str]:
        return {k: v.get("last_observed") for k, v in self.data.items() if v.get("last_observed")}

    def save(self) -> None:
        self.path.write_text(json.dumps(self.data, indent=1, sort_keys=True))


REPROBE_HOURS = 6.0     # how often a browser-only source's HTTP routes are re-tried (recovery without hammering the host)


def due_for_reprobe(health: Health, source_id: str, now: datetime) -> bool:
    last = health.get(source_id).get("last_probe_at")
    return last is None or (_naive(now) - _naive(datetime.fromisoformat(last))) >= timedelta(hours=REPROBE_HOURS)


def coverage_score(sources, observed: dict[str, str]) -> dict:
    """SOURCE_COVERAGE_SCORE: priority-weighted credit over EVERY registered source (not only the ones that ran), so
    leaving a source off the run — or proxying it and calling it live — cannot inflate the number."""
    num = den = 0.0
    by_status: Counter = Counter()
    per = {}
    for s in sources:
        st = observed.get(s.id) or (s.status if s.status not in RUNNABLE else "unobserved")
        w = WEIGHTS.get(s.priority, 1.0); c = CREDIT.get(st, 0.0)
        num += w * c; den += w; by_status[st] += 1; per[s.id] = {"status": st, "weight": w, "credit": c}
    return {"score": (num / den) if den else 0.0, "numerator": num, "denominator": den, "by_status": dict(by_status), "sources": per}


def fetch_source(source: Source, days: list[date], received_at: datetime, transport=None, home: Optional[Path] = None, op=None, health: Optional[Health] = None) -> FetchResult:
    """Try the source's routes in order. HTTP routes that fail are classified and recorded; a browser route enqueues a
    job (idempotent) carrying the most specific failure seen so far as its reason."""
    transport = transport or HttpTransport()
    res = FetchResult()
    for route in routes_for(source):
        t0 = _time.time()
        if route.mode == "browser":
            if home is None:
                res.attempts.append({"route": "browser", "observed": "queued", "error": "no home for the job queue"}); continue
            reason = most_specific(res.attempts) if res.attempts else source.status
            kw = {"day": days[-1].isoformat()} if route.adapter == "parse_pib_day" else {}
            p = enqueue(home, source, route, reason=reason, at=received_at, adapter_kwargs=kw)
            res.attempts.append({"route": "browser", "observed": "queued", "job": p.name}); continue
        try:
            events = _run_route(source, route, days, received_at, transport)
            last_ok = health.last_ok_at(source.id) if health else None
            obs = observe(len(events), True, route.egress, last_ok, received_at, source.sla_hours)
            if source.status == "degraded" and obs in ("live", "live_secondary"):
                obs = "degraded"                         # partial or stale data by construction: never promoted to live
            res.attempts.append({"route": route.egress, "observed": obs, "fetched": len(events), "seconds": round(_time.time() - t0, 1)})
            res.events, res.route, res.observed = events, route, obs
            return res
        except RouteFailed as e:
            res.attempts.append({"route": route.egress, "observed": e.observed, "error": e.detail[:200], "seconds": round(_time.time() - t0, 1)})
        except ConnectionError as e:
            res.attempts.append({"route": route.egress, "observed": "unreachable", "error": str(e)[:200], "seconds": round(_time.time() - t0, 1)})
        except Exception as e:  # noqa: BLE001 — one route must never stop the next
            res.attempts.append({"route": route.egress, "observed": "adapter_error", "error": f"{type(e).__name__}: {str(e)[:160]}", "seconds": round(_time.time() - t0, 1)})
    res.observed = most_specific([a for a in res.attempts if a["observed"] != "queued"]) if any(a["observed"] != "queued" for a in res.attempts) else ("queued" if res.attempts else "not_built")
    res.error = next((a.get("error") for a in reversed(res.attempts) if a.get("error")), None)
    return res


def run_sources(sources: list[Source], store, fetchers: Optional[dict[str, Callable]] = None, today: Optional[date] = None, back: int = 5,
                transport=None, health: Optional[Health] = None) -> dict:
    today = today or datetime.now(IST).date()
    days = window_days(today, back)
    received_at = datetime.now(IST)
    home = Path(store.home)
    health = health or Health(home)
    transport = transport or HttpTransport()
    manifest = {"run_at": received_at.isoformat(), "days": [str(d) for d in days], "sources": {}, "ok": 0, "failed": 0, "queued": 0, "new_total": 0}
    manifest["browser_ingest"] = ingest_results(home, store, health, registry={s.id: s for s in SOURCES})
    run_observed = {}
    for s in sources:
        t0 = _time.time(); rec = {"status": s.status}
        try:
            fn = (fetchers or {}).get(s.id)
            if fn is not None:
                events = fn(s, days, received_at)
                obs = observe(len(events), True, "primary", health.last_ok_at(s.id), received_at, s.sla_hours)
                res = FetchResult(events=events, route=Route("http", "get", s.url, s.adapter or ""), observed=obs)
            elif s.status not in RUNNABLE and any(r.mode == "browser" for r in routes_for(s)):
                if due_for_reprobe(health, s.id, received_at):
                    res = fetch_source(s, days, received_at, transport=transport, home=home, health=health)   # PRIMARY → SECONDARY → BROWSER job
                else:
                    for r in routes_for(s):
                        if r.mode == "browser":
                            enqueue(home, s, r, reason=health.get(s.id).get("last_observed") or s.status, at=received_at, adapter_kwargs={"day": days[-1].isoformat()} if r.adapter == "parse_pib_day" else {})
                    res = FetchResult(observed="queued", attempts=[{"route": "browser", "observed": "queued"}])
            else:
                res = fetch_source(s, days, received_at, transport=transport, home=home, health=health)
            new = store.add(res.events) if res.events else 0
            rec.update(observed=res.observed, route=(res.route.egress if res.route else None), fetched=len(res.events), new=new, seconds=round(_time.time() - t0, 1))
            if res.attempts and (len(res.attempts) > 1 or res.observed not in OK_OBSERVED):
                rec["attempts"] = res.attempts
            if res.error:
                rec["error"] = res.error
            manifest["new_total"] += new
        except Exception as e:  # noqa: BLE001 — one source must never stop the others
            obs = "unreachable" if isinstance(e, ConnectionError) else "adapter_error"
            rec.update(observed=obs, route=None, fetched=0, new=0, error=f"{type(e).__name__}: {str(e)[:200]}", seconds=round(_time.time() - t0, 1))
            logger.warning("source %s failed: %s", s.id, rec["error"])
        if rec["observed"] == "queued":
            manifest["queued"] += 1
        elif rec["observed"] in NOT_FAILURES:
            manifest["ok"] += 1
        else:
            manifest["failed"] += 1
        h = health.record(s.id, rec["observed"], rec.get("fetched", 0), received_at, rec.get("route"), rec.get("error"))
        if rec["observed"] != "queued":
            h["last_probe_at"] = received_at.isoformat()
        run_observed[s.id] = rec["observed"]
        manifest["sources"][s.id] = rec
    health.save()
    manifest["coverage"] = coverage_score(SOURCES, {**health.observed_map(), **run_observed})
    runs = home / "runs"; runs.mkdir(exist_ok=True)
    (runs / f"{received_at.strftime('%Y-%m-%dT%H%M%S')}.json").write_text(json.dumps(manifest, indent=1, default=str))
    return manifest


def main(argv=None) -> int:
    from .store import EventStore

    ap = argparse.ArgumentParser()
    ap.add_argument("--home", type=Path, required=True); ap.add_argument("--only", default=None); ap.add_argument("--back", type=int, default=5)
    ap.add_argument("--no-browser-queue", action="store_true", help="do not enqueue browser jobs for browser-only sources")
    a = ap.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    if a.only:
        ids = a.only.split(",")
    else:
        ids = [s.id for s in SOURCES if s.status in RUNNABLE or (not a.no_browser_queue and s.status not in RUNNABLE and any(r.mode == "browser" for r in routes_for(s)))]
    m = run_sources([get_source(i) for i in ids], EventStore(a.home), back=a.back)
    cov = m["coverage"]
    logger.info("run: %d ok, %d failed, %d queued for a browser worker, %d new events; SOURCE_COVERAGE_SCORE %.3f (%s)",
                m["ok"], m["failed"], m["queued"], m["new_total"], cov["score"], ", ".join(f"{k}={v}" for k, v in sorted(cov["by_status"].items())))
    for sid, r in m["sources"].items():
        logger.info("  %-26s %-16s %s", sid, r["observed"], r.get("error") or f"fetched {r.get('fetched', 0):5d} new {r.get('new', 0):5d} via {r.get('route')} ({r.get('seconds')}s)")
    return 0 if m["failed"] == 0 else 2


if __name__ == "__main__":
    raise SystemExit(main())
