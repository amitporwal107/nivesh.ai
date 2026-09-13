"""fetch_screener_quarters must not judge a page that rendered its quarters section as a block wall.

CMPDI's consolidated page (quarters section, no dated columns yet) reached the rate-limit check,
was judged blocked, and halted three historical backfill runs before the standalone page was tried.
"""
import asyncio
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from nidp.services.nse_financials import ir_scraper as S  # noqa: E402

PAD = "<!-- pad -->" * 120   # pages under 1,000 chars are treated as empty

# The rate-limit check fires on a login-looking title even without block keywords.
UNDATED = f"<html><head><title>Login - Screener</title></head><body>{PAD}" \
          '<section id="quarters"><table><tr><td>Sales</td></tr></table></section></body></html>'
DATED = f"<html><head><title>CMPDI share price</title></head><body>{PAD}" \
        '<section id="quarters"><th data-date-key="2026-06-30">Jun 2026</th></section></body></html>'
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
