"""The off-VM BSE fetcher and its replay.

bse_offvm_fetch.py must run on a user's own machine with no nidp imports, so it
carries COPIES of production's request constants. If those copies drift, the
history it fetches would differ from what the live ingester fetched — silently.
These tests import both sides and fail on any divergence.
"""
from __future__ import annotations

import hashlib
import json
from datetime import date

import pytest

from nidp.services.corporate_announcements import bse_offvm_fetch as F
from nidp.services.corporate_announcements import bse_offvm_replay as R
from nidp.services.corporate_announcements import service as S
from nidp.services.corporate_announcements.taxonomy import iter_slices
from nidp.shared.config import DEFAULT_UA


# ── the fetcher asks for exactly what production asked for ─────────────────────
@pytest.mark.parametrize("d,page", [("20240603", 1), ("20251231", 7), ("20260925", 20)])
def test_coarse_url_is_production_url(d, page):
    assert F.coarse_url(d, page) == S._BSE_ANN_URL_TMPL.format(d=d, page=page)


@pytest.mark.parametrize("page", [1, 4, 10])
def test_subcat_url_is_production_url_for_every_slice(page):
    for category, sub in iter_slices():
        assert F.subcat_url(category, sub, "20250115", page) == \
            S._bse_subcat_url(category, sub, "20250115", page)


def test_categories_are_production_slices_in_production_order():
    assert list(F.CATEGORIES) == [c for c, _ in iter_slices()]


def test_page_caps_match_production():
    assert F.COARSE_MAX_PAGES == S._BSE_MAX_PAGES
    assert F.SUBCAT_MAX_PAGES == S._BSE_SUBCAT_MAX_PAGES


def test_headers_match_the_production_session_and_referer():
    assert F.HEADERS["User-Agent"] == DEFAULT_UA
    assert F.HEADERS["Accept"] == "text/html,application/xhtml+xml,application/xml,*/*"
    assert F.HEADERS["Accept-Encoding"] == "gzip, deflate"
    assert F.HEADERS["Referer"] == "https://www.bseindia.com/corporates/ann.html"


@pytest.mark.parametrize("body,coarse_last,subcat_last", [
    (b'{"Table":[],"Table1":[]}', True, True),
    (b'{"Table": [], "Table1": []}' + b" " * 300, False, True),   # the spaced form only subcat checks
    (b"x" * 199, True, True),
    (b'{"Table":[{"NEWSID":"a"}]}' + b" " * 300, False, False),
])
def test_stop_rules_match_production_verbatim(body, coarse_last, subcat_last):
    """Copied, not re-derived: production's coarse loop checks one spelling of the
    empty table, the subcat loop checks two. Matching that exactly is the point."""
    assert F.coarse_page_is_last(body) is coarse_last
    assert F.subcat_page_is_last(body) is subcat_last


# ── what the fetcher saves, the replay loads — and refuses if tampered ─────────
_PAGE = json.dumps({"Table": [{
    "NEWSID": "e5501245-f5cd-45b3-954a-a89c294e2241", "SCRIP_CD": 500493,
    "NEWSSUB": "Bharat Forge Ltd - 500493 - Announcement under Regulation 30 (LODR)-Allotment",
    "HEADLINE": "Allotment of shares", "DT_TM": "2026-09-22T23:58:45.357",
    "NEWS_DT": "2026-09-22T23:58:45.357", "CATEGORYNAME": "Company Update",
    "SUBCATNAME": "Allotment of Equity Shares",
    "ATTACHMENTNAME": "543762e4-c22d-4fb1-9b0f-7f5f91467364.pdf"}]}).encode()


def _fetched_dir(tmp_path):
    F.save_day(tmp_path, "subcat", date(2026, 9, 22), [_PAGE, b'{"Table":[]}'], "u", 200)
    F.write_manifest(tmp_path)
    return tmp_path


def test_saved_body_is_production_joined_format(tmp_path):
    _fetched_dir(tmp_path)
    body = (tmp_path / "subcat" / "2026-09-22.bin").read_bytes()
    assert body == _PAGE + b"\x1e" + b'{"Table":[]}'
    meta = json.loads((tmp_path / "subcat" / "2026-09-22.json").read_text())
    assert meta["sha256"] == hashlib.sha256(body).hexdigest() and meta["rows"] == 1


def test_replay_yields_production_rows_with_real_newsid_ids(tmp_path):
    [(kind, day, body, _)] = R.load(_fetched_dir(tmp_path), ("subcat",), None, None)
    replayed = R.ReplaySubcat(body, "x").parse(body, day)
    produced = S.BseSubcategoryAnnouncementsIngester().parse(body, day)
    assert replayed == produced, "replay must parse exactly as production does"
    [row] = replayed
    assert row["subcategory"] == "Allotment of Equity Shares"
    assert row["raw_payload"]["NEWSID"] == "e5501245-f5cd-45b3-954a-a89c294e2241"


def test_a_tampered_file_is_refused_not_ingested(tmp_path):
    d = _fetched_dir(tmp_path)
    (d / "subcat" / "2026-09-22.bin").write_bytes(_PAGE)          # truncated: second page gone
    with pytest.raises(R.ManifestError):
        R.load(d, ("subcat",), None, None)


def test_coarse_replays_before_subcat_on_the_same_day(tmp_path):
    for kind in ("subcat", "coarse"):
        F.save_day(tmp_path, kind, date(2026, 9, 22), [_PAGE], "u", 200)
    F.write_manifest(tmp_path)
    assert [k for k, *_ in R.load(tmp_path, ("coarse", "subcat"), None, None)] == ["coarse", "subcat"]


# ── the replay must not make a dead live feed look healthy ─────────────────────
def test_replay_never_writes_job_log_under_the_live_ingester_names():
    """Feed health = latest status='OK' per job_log.ingester. Sharing the live name
    would report the blocked feed as healthy — how this outage stayed hidden."""
    assert R.ReplayCoarse.SERVICE_NAME != S.BseAnnouncementsIngester.SERVICE_NAME
    assert R.ReplaySubcat.SERVICE_NAME != S.BseSubcategoryAnnouncementsIngester.SERVICE_NAME
    assert R.ReplayCoarse.SOURCE_NAME == "BSE_ANN" == R.ReplaySubcat.SOURCE_NAME


def test_replay_overrides_only_fetch():
    overridden = {n for n in vars(R._Replay) if not n.startswith("__")}
    assert overridden == {"fetch"}


# ── parallel Cloud Run tasks ────────────────────────────────────────────────────
@pytest.mark.parametrize("count", [1, 2, 3, 7])
def test_shards_partition_every_day_exactly_once(count):
    from datetime import timedelta
    days = [date(2024, 6, 1) + timedelta(n) for n in range(847)]
    shards = [F.shard_of(days, i, count) for i in range(count)]
    flat = [d for s in shards for d in s]
    assert sorted(flat) == days, "a day was dropped or fetched twice"
    assert max(map(len, shards)) - min(map(len, shards)) <= 1, "shards should be balanced"


def test_replay_needs_no_manifest_only_the_sidecars(tmp_path):
    """Parallel tasks race on one manifest.json over GCS; each sidecar has one writer."""
    d = _fetched_dir(tmp_path)
    (d / "manifest.json").unlink()
    assert [k for k, *_ in R.load(d, ("subcat",), None, None)] == ["subcat"]


def test_a_sidecar_without_its_bin_is_refused(tmp_path):
    d = _fetched_dir(tmp_path)
    (d / "subcat" / "2026-09-22.bin").unlink()
    with pytest.raises(R.ManifestError):
        R.load(d, ("subcat",), None, None)


# ── the Cloud Run job's argument list ──────────────────────────────────────────
def _deploy_args(from_, to, delay="1.0"):
    """The ARGS line of deploy_bse_history_fetch.sh, filled in as bash would."""
    import re
    from pathlib import Path
    script = (Path(__file__).parents[2] / "deploy/gcp/deploy_bse_history_fetch.sh").read_text()
    [tmpl] = re.findall(r'^\s*ARGS="(.*--from.*)"$', script, re.M)
    for k, v in {"MNT": "/mnt/hist", "PREFIX": "bse_history", "FROM": from_, "TO": to, "DELAY": delay}.items():
        tmpl = tmpl.replace("${%s}" % k, v)
    return tmpl.split("@@")


def test_a_one_day_job_has_no_repeated_arg_tokens():
    """gcloud run jobs create/update rejects an --args list in which any value
    repeats ("cannot be specified multiple times") — hit for real on 2026-09-25."""
    tokens = _deploy_args("2024-06-03", "2024-06-03")
    assert len(tokens) == len(set(tokens)), tokens


def test_the_fetcher_parses_the_job_args_as_intended():
    a = F.build_parser().parse_args(_deploy_args("2024-06-01", "2026-09-25", "0.5")[1:])
    assert (a.since, a.until) == (date(2024, 6, 1), date(2026, 9, 25))
    assert str(a.out) == "/mnt/hist/bse_history/data" and a.delay == 0.5 and not a.self_test
