"""fetch_screener_quarters must not judge a page that rendered its quarters section as a block wall.

CMPDI's consolidated page (quarters section, no dated columns yet) reached the rate-limit check,
was judged blocked, and halted three historical backfill runs before the standalone page was tried.
"""
import asyncio
import os
import sys
from datetime import date, timedelta

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from nidp.services.nse_financials import ir_scraper as S  # noqa: E402

PAD = "<!-- pad -->" * 120   # pages under 1,000 chars are treated as empty

# The rate-limit check fires on a login-looking title even without block keywords.
UNDATED = f"<html><head><title>Login - Screener</title></head><body>{PAD}" \
          '<section id="quarters"><table><tr><td>Sales</td></tr></table></section></body></html>'


def _page(*quarters):
    cols = "".join(f'<th data-date-key="{q}">{q}</th>' for q in quarters)
    return (f"<html><head><title>share price</title></head><body>{PAD}"
            f'<section id="quarters">{cols}</section></body></html>')


def _ago(days):
    return (date.today() - timedelta(days=days)).isoformat()


DATED = _page(_ago(170), _ago(80))
WALL = f"<html><head><title>Login - Screener</title></head><body>{PAD}please sign in</body></html>"


def _fetch(monkeypatch, pages):
    seen = []

    async def get(url):
        seen.append(url)
        return pages[url.rstrip("/").rsplit("/", 1)[-1]]

    monkeypatch.setattr(S, "_get_text", get)
    return asyncio.run(S.fetch_screener_quarters("CMPDI")), seen


def test_undated_consolidated_page_falls_through_to_standalone(monkeypatch):
    got, seen = _fetch(monkeypatch, {"consolidated": UNDATED, "CMPDI": DATED})
    assert got == (DATED, False)
    assert seen == ["https://www.screener.in/company/CMPDI/consolidated/",
                    "https://www.screener.in/company/CMPDI/"]


def test_undated_on_both_pages_is_not_found_not_a_rate_limit(monkeypatch):
    got, _ = _fetch(monkeypatch, {"consolidated": UNDATED, "CMPDI": UNDATED})
    assert got is None


def test_a_real_block_wall_still_raises(monkeypatch):
    try:
        _fetch(monkeypatch, {"consolidated": WALL, "CMPDI": WALL})
    except RuntimeError as e:
        assert "rate-limit" in str(e)
    else:
        raise AssertionError("a login wall without a quarters section must raise")


# ── A consolidated page that stopped updating must not hide the current standalone page ──
def test_frozen_consolidated_page_yields_to_current_standalone(monkeypatch):
    frozen = _page("2024-03-31", "2024-06-30")          # 3MINDIA consolidated ends 2024-06
    got, seen = _fetch(monkeypatch, {"consolidated": frozen, "CMPDI": DATED})
    assert got == (DATED, False)
    assert len(seen) == 2


def test_current_consolidated_page_is_used_without_fetching_standalone(monkeypatch):
    got, seen = _fetch(monkeypatch, {"consolidated": DATED, "CMPDI": _page("2024-06-30")})
    assert got == (DATED, True)
    assert seen == ["https://www.screener.in/company/CMPDI/consolidated/"]


def test_when_both_pages_are_stale_the_newer_one_is_returned(monkeypatch):
    older, newer = _page("2023-09-30"), _page("2025-03-31")
    got, _ = _fetch(monkeypatch, {"consolidated": older, "CMPDI": newer})
    assert got == (newer, False)
    got, _ = _fetch(monkeypatch, {"consolidated": newer, "CMPDI": older})
    assert got == (newer, True)
