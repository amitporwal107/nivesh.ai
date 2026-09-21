"""Disk growth fixes (2026-09-17, nidp-stack-vm at 99%): (1) archive_raw writes atomically, so a re-run can never
overwrite a hard-linked older day's copy in place; (2) raw_archive.store gzips large bodies before upload — the
nse_shareholding run body was a 669 MB JSON stored uncompressed, three times a day on retries."""
import gzip
import os
from pathlib import Path

import pytest


def test_archive_raw_writes_atomically_and_never_rewrites_a_hard_linked_inode(tmp_path, monkeypatch):
    import nidp.shared.archive as arc

    monkeypatch.setattr(arc, "ARCHIVE_ROOT", tmp_path)
    old = arc.archive_raw("nse_shareholding", "2026-09-15", "SHP_1.xml", b"<x>filing</x>")
    new = arc.archive_raw("nse_shareholding", "2026-09-16", "SHP_1.xml", b"<x>filing</x>")
    os.link(old, tmp_path / "linked"); os.unlink(new); os.link(old, new)          # what the nightly dedupe does
    assert os.stat(old).st_nlink == 3
    arc.archive_raw("nse_shareholding", "2026-09-16", "SHP_1.xml", b"<x>re-filed</x>")   # a re-run of the 16th
    assert old.read_bytes() == b"<x>filing</x>" and new.read_bytes() == b"<x>re-filed</x>" and os.stat(old).st_nlink == 2
    assert not list(tmp_path.glob("**/*.tmp*"))                                   # no temp file left behind


def test_archive_raw_still_returns_none_on_bad_input(tmp_path, monkeypatch):
    import nidp.shared.archive as arc

    monkeypatch.setattr(arc, "ARCHIVE_ROOT", tmp_path)
    assert arc.archive_raw("../evil", "2026-09-16", "x", b"1") is None
    assert arc.archive_raw("nse_shareholding", "2026-09-16", "", b"1") is None


def test_large_raw_bodies_are_gzipped_before_upload_small_ones_untouched():
    from nidp.shared.storage.raw_archive import COMPRESS_OVER_BYTES, prepare_body

    small = b"{" + b"x" * 1000 + b"}"
    body, key, ctype, meta = prepare_body(small, "nse_shareholding/2026/09/abc.bin", "application/json", {})
    assert body is small and key.endswith(".bin") and ctype == "application/json" and "original_bytes" not in meta
    big = (b'{"manifests": [' + b'{"symbol": "X"}, ' * 400_000 + b"]}")
    assert len(big) > COMPRESS_OVER_BYTES
    body, key, ctype, meta = prepare_body(big, "nse_shareholding/2026/09/abc.bin", "application/json", {"run": 1})
    assert key.endswith(".bin.gz") and ctype == "application/gzip" and gzip.decompress(body) == big
    assert meta == {"run": 1, "original_bytes": len(big), "original_content_type": "application/json", "compression": "gzip"}
    assert len(body) < len(big) / 10
