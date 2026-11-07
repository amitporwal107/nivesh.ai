"""Strategy ideas for the realtime scan dashboard's stocks (docs/scan_builder/DESIGN.md §8; owner 3 Nov 2026 ~12:58 IST:
"provide the best AI recommended strategies for each of the stocks wherever the risk reward are favorable").

    await ideas_for(symbols) -> IdeasResult      values[symbol] = the idea (a compact dict) or None

Nothing new is ranked here. Each stock gets the desk's own Strategy Builder plan (services/strategy_plan: plan.build_plan over
sources.collect_snapshots, exactly as POST /api/desk/strategy/ideas builds one), for a bullish view over the positional horizon
(the view the desk's AI-scanner ideas use), cash, futures, options and combinations. A stock shows an idea only when a structure
is FAVORABLE under the builder's own rules, never relaxed:
  * the builder lists it as a viable candidate (its gates: liquidity, evidence, events, the reward : risk minimum), and
  * its shown reward : risk (net of estimated costs, else gross) reaches the plan's min_reward_risk (ideas.meets_min_reward_risk:
    an audited case labelled 0.19 : 1 viable is refused there), and
  * a defined-risk credit structure also opens for a net credit of at least 1/3 of its strike width (the risk service's
    credit rule, universal-risk-v2; checked here before costs, the risk service checks it again after costs).
Among the favorable structures the plan's `preferred` one is shown (the builder orders viable structures by net reward : risk),
else the one with the best ratio. Otherwise the stock shows none, with a short reason.

Data: every source of a plan is END OF DAY (the last close, NSE F&O bhavcopy option chain and futures, scanner, filings);
ideas never read a broker (live_broker_reads off). So a plan is built once per trading day per stock and refreshed after
FRESH_S (new filings, events), not every refresh: one plan reads 20–50 DaaS calls (measured on staging, 3 Nov), and the
dashboard can list ~300 stocks. Plans are built with the builder's defaults by a system caller (no account, so not sized to
anyone's capital; "unsized" ratios are judged before costs, as the builder says) and shared by every viewer.

Never in the way of the dashboard's 10-second refresh: an answer comes from cache at once; missing or stale stocks are built in
the background, CONCURRENCY at a time; `pending` lists the stocks still without an idea or a verdict. Across the 4 uvicorn
workers the verdicts are shared through Redis (intraday.RedisStore; LocalStore without Redis):
  nivesh:sb:ideas:v:<IST day>:<SYMBOL>      the verdict (JSON), TTL one day
  nivesh:sb:ideas:claim:<IST day>:<SYMBOL>  SET NX for CLAIM_S: one worker builds a stock at a time
Never raises: a failed build is that stock's "no idea" verdict for RETRY_S, with a logged warning.
Read-only: the TradePlans the builder attaches are not stored, and nothing is sent to a broker.
"""
from __future__ import annotations

import asyncio
import json
import logging
import re
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Awaitable, Callable, Dict, List, Optional, Sequence, Tuple

from services.kite_live_feed import config as cfg

from . import intraday

logger = logging.getLogger(__name__)

PREFIX = "nivesh:sb:ideas:"
TTL_S = 86400
FRESH_S = 3 * 3600.0          # a verdict is rebuilt after this (its data is end of day; new filings and events can change it)
RETRY_S = 600.0               # a failed build is retried after this
CLAIM_S = 180                 # one build can take a minute under load
CONCURRENCY = 3
SHARED_TTL_S = 600.0          # the market regime, sector returns and scanner buckets are read once per this, for every plan
SYSTEM_USER = {"user_id": "system:scan-dashboard-ideas", "name": "Scan dashboard strategy ideas", "email": None, "role": "user"}
VIEW = "bullish"
CREDIT_MIN_WIDTH_FRACTION = 1.0 / 3.0
SOURCE = ("Strategy Builder plans (services/strategy_plan) on end-of-day data: the last close, the NSE F&O bhavcopy option "
          "chain and futures, the AI scanner, filings and events")

BARRED = re.compile(r"\b(buy\w*|sell\w*|target\w*|stop ?loss|sl|pick\w*|recommend\w*|entry|exit)\b", re.I)

WHY = {
    "wait": "The builder says wait: the setup or the evidence is not there yet.",
    "no_trade": "No structure clears the builder's gates.",
    "insufficient_data": "The builder could not read enough data for this stock.",
    "unfavorable": "A structure exists, but its reward : risk is under the minimum.",
    "credit": "The only structures are credit spreads whose credit is under a third of their width.",
    "failed": "The plan could not be built just now; it is tried again shortly.",
}


@dataclass
class IdeasResult:
    values: Dict[str, Optional[Dict[str, Any]]] = field(default_factory=dict)   # symbol -> idea, or None (no favorable idea)
    pending: List[str] = field(default_factory=list)                            # still being built: no verdict yet
    warnings: List[str] = field(default_factory=list)
    source: str = SOURCE
    note: str = ""
    as_of: Optional[str] = None                                                  # the latest end-of-day price day the ideas use
    reasons: Dict[str, str] = field(default_factory=dict)                       # symbol -> why it has no idea


def note_text(min_rr: Optional[float] = None) -> str:
    from services.strategy_plan.rules import RULES, STRATEGY_RULES_VERSION
    m = min_rr if min_rr is not None else RULES["defaults"]["min_reward_risk"]
    return (f"Strategy ideas from the desk's Strategy Builder ({STRATEGY_RULES_VERSION}), for a {VIEW} view over the positional "
            f"horizon ({RULES['defaults']['horizon_days']['positional']} sessions). A stock shows one only when a structure passes "
            f"the builder's gates and its reward : risk is at least {m:g} : 1 (net of estimated costs when the plan is sized, "
            "otherwise before costs), and a credit spread also collects at least a third of its strike width. Built from "
            "end-of-day data (the last close and the NSE option chain), not live prices, and not sized to your account. "
            "Ideas for your own research, not advice; nothing is sent to a broker.")


# ── one plan -> one idea ────────────────────────────────────────────────────────────────────────────────────────────

def _day(v: Any) -> str:
    try:
        return datetime.strptime(str(v)[:10], "%Y-%m-%d").strftime("%-d %b")
    except ValueError:
        return str(v)


def legs_text(legs: Sequence[Dict[str, Any]]) -> str:
    """'Long 1 lot 700 CE + Short 1 lot 730 CE, 23 Nov' / 'Long 250 shares' — the builder's own legs, in neutral words."""
    parts: List[str] = []
    for leg in legs:
        side = "Long" if leg.get("side") == "buy" else "Short"
        q = leg.get("quantity") or 0
        if leg.get("kind") == "cash":
            parts.append(f"{side} {q:g} shares")
        elif leg.get("kind") == "future":
            parts.append(f"{side} {q:g} lot{'' if q == 1 else 's'} future")
        else:
            ot = {"call": "CE", "put": "PE"}.get(leg.get("option_type"), str(leg.get("option_type") or ""))
            parts.append(f"{side} {q:g} lot{'' if q == 1 else 's'} {float(leg.get('strike') or 0):g} {ot}")
    days = sorted({leg["expiry"] for leg in legs if leg.get("expiry")})
    text = " + ".join(parts)
    if days:
        text += ", " + " / ".join(_day(d) for d in days)
    return text


def credit_ok(legs: Sequence[Dict[str, Any]]) -> bool:
    """False for a defined-risk credit structure whose net credit is under a third of its strike width (before costs);
    True for every other structure. Decided from the legs by the risk service's own credit_terms."""
    from services.risk_gate import estimate as est
    gate_legs = [{"kind": leg.get("kind"), "side": leg.get("side"), "lots": leg.get("quantity"), "lot_size": leg.get("lot_size"),
                  "entry_price": leg.get("entry_price"), "expiry": leg.get("expiry"), "strike": leg.get("strike"),
                  "option_type": leg.get("option_type")} for leg in legs]
    try:
        terms = est.credit_terms(gate_legs)
    except Exception as e:  # noqa: BLE001 — not decidable: not shown as favorable
        logger.warning("scan dashboard ideas: credit terms failed (%s)", type(e).__name__)
        return False
    if terms is None:
        return True
    return float(terms["net_credit_rs"]) >= float(terms["width_rs"]) * CREDIT_MIN_WIDTH_FRACTION - 1e-9


def _safe(text: Any, fallback: str) -> str:
    t = str(text or "").strip()
    return t if t and not BARRED.search(t) else fallback


def summarize(plan: Dict[str, Any], symbol: str) -> Tuple[Optional[Dict[str, Any]], Optional[str]]:
    """(idea, None) when a structure is favorable, else (None, why)."""
    from services.strategy_plan import ideas as ideas_mod
    rows = ideas_mod.strategies_of(plan, symbol)
    cands = {c["id"]: c for c in plan.get("candidates") or []}
    viable = [r for r in rows if r.get("status") == "candidate"]
    rr_ok = [r for r in viable if r.get("meets_min_reward_risk") is True]
    good = [r for r in rr_ok if credit_ok((cands.get(r["id"]) or {}).get("legs") or [])]
    if not good:
        if rr_ok:
            return None, WHY["credit"]
        if viable:
            return None, WHY["unfavorable"]
        return None, WHY.get(plan.get("status") or "", WHY["no_trade"])
    pref = plan.get("preferred")

    def ratio(r: Dict[str, Any]) -> float:
        v = r.get("reward_risk_net") if r.get("reward_risk_net") is not None else r.get("reward_risk_gross")
        return float(v) if v is not None else -1e9
    best = next((r for r in good if r["id"] == pref), None) or max(good, key=ratio)
    c = cands.get(best["id"]) or {}
    net, gross = best.get("reward_risk_net"), best.get("reward_risk_gross")
    inputs = plan.get("inputs") or {}
    das = plan.get("data_as_of") or {}
    max_loss = best.get("max_loss")
    idea = {
        "structure": _safe(best.get("label"), str(best.get("family") or "Strategy").replace("_", " ").capitalize()),
        "family": best.get("family"), "segment": best.get("segment"),
        "horizon": f"{inputs.get('horizon') or 'positional'}, {inputs.get('horizon_days')} sessions",
        # The lower, net figure whenever the builder has one (it is what decided "favorable" via meets_min_reward_risk, and
        # what the desk's cards show); the gross one only when no cost estimate exists.
        "reward_risk": round(float(net if net is not None else gross), 2),
        "reward_risk_basis": "net of estimated costs" if net is not None else "before costs",
        "max_loss_inr": round(abs(float(max_loss)), 2) if max_loss is not None else None,
        "max_loss_basis": _safe(best.get("max_loss_basis"), "the builder's max loss"),
        "capital_at_risk_inr": round(float(best["capital_at_risk"]), 2) if best.get("capital_at_risk") is not None else None,
        "legs_text": legs_text(c.get("legs") or []),
        "data_as_of": das.get("price"), "fno_as_of": das.get("fno"),
        "plan_id": plan.get("plan_id"), "trade_plan_id": best.get("trade_plan_id"),
        "other_favorable": len(good) - 1,
        "plan_inputs": plan_body(symbol),
    }
    return idea, None


def plan_body(symbol: str) -> Dict[str, Any]:
    """The exact body that rebuilds this plan through POST /api/desk/strategy/plan."""
    return {"underlying": symbol, "direction": VIEW, "instrument": "all", "include_chartink": False}


# ── the real builder (one batch context per SHARED_TTL_S) ───────────────────────────────────────────────────────────

class PlanBuilder:
    """Builds one stock's plan the way POST /api/desk/strategy/ideas does, as the system caller (deps.system_caller) with an
    internal request: the market regime, sector returns and the scanner's watchlist + picks are read once per SHARED_TTL_S."""

    def __init__(self) -> None:
        self._shared: Optional[Dict[str, Any]] = None
        self._buckets: Dict[str, Any] = {}
        self._at = -1e18
        self._lock = asyncio.Lock()

    async def _context(self) -> Tuple[Any, Dict[str, Any], Dict[str, Any]]:
        from services.ai_watchlist_build import internal_request
        from services.strategy_plan.sources import shared_for_ideas
        req = internal_request()
        async with self._lock:
            if self._shared is None or time.monotonic() - self._at > SHARED_TTL_S:
                self._shared = await shared_for_ideas(SYSTEM_USER["user_id"], None)
                self._buckets = await self._scanner_buckets(req)
                self._at = time.monotonic()
        return req, self._shared, self._buckets

    @staticmethod
    async def _scanner_buckets(req: Any) -> Dict[str, Any]:
        """{symbol: scanner snapshot} for every stock the scanner lists, from ONE watchlist and ONE picks read (the same
        snapshot sources._scanner_bucket builds per stock). A stock not listed gets the per-stock read inside the plan."""
        from routes import positional
        from services.strategy_plan.sources import scanner_snapshot
        try:
            body, picks = await asyncio.gather(positional.get_watchlist(req, limit=300),
                                               positional.get_picks(req, date=None, min_score=0.55, stage=None, limit=300),
                                               return_exceptions=True)
        except Exception as e:  # noqa: BLE001
            logger.warning("scan dashboard ideas: scanner read failed (%s)", type(e).__name__)
            return {}
        if isinstance(body, BaseException):
            logger.warning("scan dashboard ideas: scanner watchlist read failed (%s)", type(body).__name__)
            return {}
        pick_by = {} if isinstance(picks, BaseException) else {
            str(p.get("nse_symbol") or "").upper(): p for p in picks.get("picks") or []}
        out: Dict[str, Any] = {}
        for bucket, items in (body.get("buckets") or {}).items():
            for it in items:
                sym = str(it.get("nse_symbol") or "").upper()
                if sym and sym not in out:
                    out[sym] = scanner_snapshot(sym, bucket, it, pick_by.get(sym), body.get("as_of_date"),
                                                body.get("_classifier_version"))
        for sym, p in pick_by.items():
            if sym and sym not in out:
                out[sym] = scanner_snapshot(sym, None, None, p, body.get("as_of_date"), body.get("_classifier_version"))
        return out

    async def __call__(self, symbol: str) -> Dict[str, Any]:
        from services.strategy_plan.plan import build_plan, normalise_inputs
        from services.strategy_plan.sources import collect_snapshots
        req, shared, buckets = await self._context()
        pin, probs = normalise_inputs(plan_body(symbol))
        if probs:
            raise ValueError("; ".join(p["code"] for p in probs))
        pin["live_broker_reads"] = False                     # ideas never call a broker
        extra = {"scanner_bucket": {symbol: buckets[symbol]}} if symbol in buckets else {}
        now = datetime.now(timezone.utc)
        today = now.astimezone(cfg.IST).date()
        snaps = await collect_snapshots(req, SYSTEM_USER["user_id"], pin, today, {**shared, **extra})
        return await asyncio.to_thread(build_plan, pin, snaps, now, today)


# ── the shared, non-blocking cache ──────────────────────────────────────────────────────────────────────────────────

@dataclass
class Verdict:
    built_at: float
    idea: Optional[Dict[str, Any]]
    why: Optional[str]
    failed: bool = False


def _encode(v: Verdict) -> str:
    return json.dumps({"built_at": v.built_at, "idea": v.idea, "why": v.why, "failed": v.failed}, separators=(",", ":"))


def _decode(raw: Optional[str]) -> Optional[Verdict]:
    if not raw:
        return None
    try:
        d = json.loads(raw)
        return Verdict(float(d["built_at"]), d.get("idea"), d.get("why"), bool(d.get("failed")))
    except (ValueError, KeyError, TypeError):
        return None


class IdeasService:
    def __init__(self, *, store: Any = None, builder: Optional[Callable[[str], Awaitable[Dict[str, Any]]]] = None,
                 wall: Callable[[], float] = time.time, now: Optional[Callable[[], datetime]] = None,
                 concurrency: int = CONCURRENCY, system_user: Optional[Dict[str, Any]] = None):
        self._store = store if store is not None else intraday.RedisStore()
        self._builder = builder
        self._wall = wall
        self._now = now or (lambda: datetime.now(timezone.utc))
        self._concurrency = max(1, int(concurrency))
        self._user = system_user if system_user is not None else SYSTEM_USER
        self._local: Dict[str, Verdict] = {}
        self._queue: Dict[str, None] = {}                     # ordered set of keys waiting to be built
        self._task: Optional[asyncio.Task] = None
        self.builds = 0                                      # plans built by this process (tests and the live check read it)
        self.failures = 0

    def _key(self, day: str, sym: str) -> str:
        return f"{day}:{sym}"

    def _fresh(self, v: Optional[Verdict]) -> bool:
        if v is None:
            return False
        age = self._wall() - v.built_at
        return age < (RETRY_S if v.failed else FRESH_S)

    async def ideas_for(self, symbols: Sequence[str]) -> IdeasResult:
        day = self._now().astimezone(cfg.IST).date().isoformat()
        syms = [s for s in dict.fromkeys(str(x).strip().upper() for x in symbols) if s]
        keys = {s: self._key(day, s) for s in syms}
        need = [keys[s] for s in syms if not self._fresh(self._local.get(keys[s]))]
        if need:
            got = await self._store.get_many([PREFIX + "v:" + k for k in need])
            for k in need:
                v = _decode(got.get(PREFIX + "v:" + k))
                if v is not None and (self._local.get(k) is None or v.built_at > self._local[k].built_at):
                    self._local[k] = v
        stale = [s for s in syms if not self._fresh(self._local.get(keys[s]))]
        if stale:
            self._schedule([keys[s] for s in stale])
        out = IdeasResult(note=note_text())
        days: List[str] = []
        for s in syms:
            v = self._local.get(keys[s])
            if v is None:
                out.pending.append(s)
                continue
            out.values[s] = v.idea
            if v.idea is None:
                out.reasons[s] = v.why or WHY["no_trade"]
            elif v.idea.get("data_as_of"):
                days.append(str(v.idea["data_as_of"]))
        out.as_of = max(days) if days else None
        if out.pending:
            out.warnings.append(f"Strategy ideas are still being built for {len(out.pending)} of {len(syms)} stocks.")
        return out

    def _schedule(self, keys: Sequence[str]) -> None:
        for k in keys:
            self._queue.setdefault(k, None)
        if self._queue and (self._task is None or self._task.done()):
            from deps import system_caller
            # The routes a plan reads check the signed-in user: the background task runs as the system caller. The context
            # is copied when the task is created, so only this task carries it.
            with system_caller(self._user):
                self._task = asyncio.get_running_loop().create_task(self._run())

    async def _run(self) -> None:
        sem = asyncio.Semaphore(self._concurrency)
        running: List[asyncio.Task] = []

        async def one(k: str) -> None:
            async with sem:
                await self._build(k)
        while self._queue or running:
            while self._queue and len(running) < self._concurrency * 2:
                k = next(iter(self._queue))
                self._queue.pop(k)
                running.append(asyncio.ensure_future(one(k)))
            done, _ = await asyncio.wait(running, return_when=asyncio.FIRST_COMPLETED)
            running = [t for t in running if t not in done]

    async def _build(self, k: str) -> None:
        if self._fresh(self._local.get(k)):
            return
        got = _decode((await self._store.get_many([PREFIX + "v:" + k])).get(PREFIX + "v:" + k))
        if got is not None:
            self._local[k] = got
            if self._fresh(got):
                return                                  # another worker built it meanwhile
        if not await self._store.claim(PREFIX + "claim:" + k, CLAIM_S):
            return                                      # another worker is building it now
        sym = k.split(":", 1)[1]
        try:
            builder = self._builder or _default_builder()
            plan = await builder(sym)
            idea, why = summarize(plan, sym)
            v = Verdict(self._wall(), idea, why)
            self.builds += 1
        except asyncio.CancelledError:
            raise
        except Exception as e:  # noqa: BLE001 — that stock shows no idea for RETRY_S; the others are unaffected
            self.failures += 1
            logger.warning("scan dashboard ideas: plan for %s failed (%s: %s)", sym, type(e).__name__, str(e)[:160])
            v = Verdict(self._wall(), None, WHY["failed"], failed=True)
        self._local[k] = v
        await self._store.put(PREFIX + "v:" + k, _encode(v), TTL_S)


_BUILDER: Optional[PlanBuilder] = None
_SERVICE: Optional[IdeasService] = None


def _default_builder() -> PlanBuilder:
    global _BUILDER
    if _BUILDER is None:
        _BUILDER = PlanBuilder()
    return _BUILDER


def get_service() -> IdeasService:
    global _SERVICE
    if _SERVICE is None:
        _SERVICE = IdeasService()
    return _SERVICE


async def ideas_for(symbols: Sequence[str], *, user_id: Optional[str] = None) -> IdeasResult:
    """See the module docstring. `user_id` is accepted for the dashboard's call but not used: the ideas are built once for
    every viewer by the system caller (not sized to an account), because the dashboard itself is one shared computation."""
    return await get_service().ideas_for(symbols)
