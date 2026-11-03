"""One switch for where market data comes from: our own feeds today, TrueData once it is plugged in.

Owner decision (29 Oct 2026): ONE switch for everything, flipped by editing backend/config/market_data_source.json in a
pull request to dev ("once TrueData is plugged we can switch off the remaining"). Both servers read the same file:
the NIDP jobs (cron on the NIDP VM, from its dev checkout) and the app backend (its bind-mounted backend/ directory).

Modes
    current   our own feeds serve: NSE files through the NIDP ingesters, Kite for live quotes.
    shadow    our feeds still serve; TrueData runs beside them so the two can be compared before anyone relies on it.
    truedata  TrueData serves, and OUR feeds that it replaces are switched off (REPLACED_FEEDS). Everything else keeps
              running whatever the switch says: NSE's own equity and F&O bhavcopies (the record, see below) and the feeds
              TrueData does not offer (index constituents, FII/DII, bulk/block deals, delivery, shareholding, the event
              calendar, mutual funds, ...).

NSE's daily equity and F&O files stay on (owner, 29 Oct 2026, after the TrueData trial): TrueData's prices matched them
exactly on 28 Oct, but TrueData has no raw (unadjusted) history (even a past day's bhavcopy comes back adjusted), no
delisted securities, no F&O settlement price, previous close or series, and no open interest for untraded contracts.
Option strikes and paper-trade history need the raw prices, so the NSE files remain the record and the cross-check.

Safety: the switch never turns our feeds off unless TrueData can actually take over. `resolve()` turns the CONFIGURED
mode into the EFFECTIVE one, and each step down is recorded as a reason:
    1. MARKET_DATA_SOURCE_FORCE_CURRENT=1 in the environment → current (an emergency way back that needs no PR).
    2. truedata while TrueData is not integrated (TRUEDATA_INTEGRATED below) → shadow. Shadow does not need this gate:
       it never switches our feeds off, it only runs TrueData beside them for the data-quality comparison.
    3. shadow / truedata without TRUEDATA_USERNAME and TRUEDATA_PASSWORD configured → current.
    4. truedata without truedata_licence_confirmed in the file → shadow. TrueData's terms exclude simulation and
       display to third parties without SEBI/exchange approval; the owner sets the flag after their written answer.
A missing or unreadable file is `current`, with the reason.

    python -m nidp.shared.market_data_source        prints the resolution as JSON (what each server will do).
"""
from __future__ import annotations

import json
import os
import sys
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Mapping, Optional

CONFIG_PATH = Path(__file__).resolve().parents[2] / "config" / "market_data_source.json"
MODES = ("current", "shadow", "truedata")

# Our feeds that TrueData replaces when it serves (the names our jobs run under). Everything else keeps running —
# deliberately including NSE's equity and F&O bhavcopies (`bhavcopy`, `fno_bhavcopy`): see the module docstring.
REPLACED_FEEDS: frozenset[str] = frozenset({
    "index_close",         # NIDP: NSE index closes → nidp.index_eod
    "corporate_actions",   # NIDP: NSE corporate actions → nidp.corporate_actions
    "kite_live_feed",      # app: Kite live quotes (services/kite_live_feed)
})

# TrueData can SERVE (our replaced feeds switched off) only once its ingesters and live feed are verified. Until then
# this stays False, so the switch cannot switch our feeds off by mistake whatever the file says. Shadow mode does not
# depend on it (see resolve()).
TRUEDATA_INTEGRATED = False

_TRUTHY = {"1", "true", "yes", "on"}


@dataclass(frozen=True)
class Resolution:
    configured: str                      # what the file asks for
    effective: str                       # what will actually happen
    serve_from: str                      # "current" | "truedata": whose data users see
    our_feeds_on: bool                   # our replaced feeds run
    truedata_feeds_on: bool              # TrueData feeds run (shadow or serving)
    reasons: tuple[str, ...] = ()        # why effective differs from configured, or why the file was not used
    changed_on: Optional[str] = None
    changed_by: Optional[str] = None
    reason: Optional[str] = None
    replaced_feeds: tuple[str, ...] = field(default_factory=lambda: tuple(sorted(REPLACED_FEEDS)))

    def as_dict(self) -> dict:
        return asdict(self)


def load_config(path: Optional[Path] = None) -> tuple[dict, list[str]]:
    """The switch file as a dict, and the reasons it could not be used ([] when fine)."""
    path = CONFIG_PATH if path is None else path
    try:
        data = json.loads(Path(path).read_text())
    except FileNotFoundError:
        return {}, [f"CONFIG_MISSING: {path}"]
    except (OSError, ValueError) as exc:
        return {}, [f"CONFIG_UNREADABLE: {type(exc).__name__}"]
    if not isinstance(data, dict):
        return {}, ["CONFIG_UNREADABLE: not a JSON object"]
    return data, []


def truedata_credentials_present(env: Mapping[str, str]) -> bool:
    return bool((env.get("TRUEDATA_USERNAME") or "").strip()) and bool((env.get("TRUEDATA_PASSWORD") or "").strip())


def resolve(config: Optional[dict] = None, env: Optional[Mapping[str, str]] = None,
            *, integrated: Optional[bool] = None) -> Resolution:
    """Turn the configured mode into the effective one (see the module docstring for the order of the checks)."""
    reasons: list[str] = []
    if config is None:
        config, reasons = load_config()
    env = os.environ if env is None else env
    integrated = TRUEDATA_INTEGRATED if integrated is None else integrated

    configured = str(config.get("source", "current")).strip().lower()
    if configured not in MODES:
        reasons.append(f"INVALID_SOURCE: {configured!r}")
        configured = "current"
    effective = configured

    if (env.get("MARKET_DATA_SOURCE_FORCE_CURRENT") or "").strip().lower() in _TRUTHY and effective != "current":
        reasons.append("FORCED_CURRENT_BY_ENV")
        effective = "current"
    if effective == "truedata" and not integrated:
        reasons.append("TRUEDATA_NOT_INTEGRATED")
        effective = "shadow"
    if effective in ("shadow", "truedata") and not truedata_credentials_present(env):
        reasons.append("TRUEDATA_NOT_CONFIGURED")
        effective = "current"
    if effective == "truedata" and config.get("truedata_licence_confirmed") is not True:
        reasons.append("TRUEDATA_LICENCE_NOT_CONFIRMED")
        effective = "shadow"

    return Resolution(
        configured=configured,
        effective=effective,
        serve_from="truedata" if effective == "truedata" else "current",
        our_feeds_on=effective != "truedata",
        truedata_feeds_on=effective in ("shadow", "truedata"),
        reasons=tuple(reasons),
        changed_on=config.get("changed_on"),
        changed_by=config.get("changed_by"),
        reason=config.get("reason"),
    )


def feed_is_on(feed: str, resolution: Optional[Resolution] = None) -> bool:
    """Should OUR feed `feed` run? Always True for a feed TrueData does not replace."""
    if feed not in REPLACED_FEEDS:
        return True
    return (resolution or resolve()).our_feeds_on


def truedata_is_on(resolution: Optional[Resolution] = None) -> bool:
    """May anything call TrueData (shadow or serving)? Every TrueData entry point asks this first, so `current` (in the
    file, or forced by MARKET_DATA_SOURCE_FORCE_CURRENT=1) is a complete way back to our own feeds."""
    return (resolution or resolve()).truedata_feeds_on


def truedata_off_message(resolution: Optional[Resolution] = None) -> str:
    r = resolution or resolve()
    why = f" ({', '.join(r.reasons)})" if r.reasons else ""
    return (f"TrueData is switched off: market data source is '{r.effective}'{why} "
            f"(backend/config/market_data_source.json)")


def switched_off_message(feed: str) -> str:
    return (f"{feed} switched off: market data source is TrueData "
            f"(backend/config/market_data_source.json); this feed is served by TrueData")


def main() -> int:
    print(json.dumps(resolve().as_dict(), indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
