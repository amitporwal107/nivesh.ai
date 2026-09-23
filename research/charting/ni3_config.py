"""Loader for the frozen NI-3 v1.0 predicate configuration.

NI-3's own header states the rule this module exists to enforce:

    "Detector check: the detector code must reproduce this fingerprint from its own
     configuration, or it is not this table."

So loading is not a plain `json.load`: `load()` recomputes the SHA-256 of the canonical JSON and
raises unless it equals the frozen fingerprint. A detector that silently ran against an edited
config would produce results that look like NI-3 and are not, which is the one failure the
fingerprint exists to prevent.

This is deliberately SEPARATE from `research/charting/config.py`. That module holds the frozen v1
configuration (`config_hash 05167d3a…`) which governs the three live families; this one holds the
NI-3 table (`de86626c…`) which governs the sixteen new families. §37.7 keeps them apart on purpose —
the ATR rules stay with the P0 families and the percentage rules apply to the new ones — and merging
them would change frozen v1 behaviour.
"""
from __future__ import annotations

import hashlib
import json
from functools import lru_cache
from pathlib import Path
from typing import Any

#: NI-3 v1.0, frozen 2026-09-22. Any change is a new version, never an edit to the file.
NI3_FINGERPRINT = "de86626c6f15e5f2d41708e92f8b66367394eb1c8e52ed2534ecfd8e0ded44a8"

NI3_CONFIG_PATH = Path(__file__).resolve().parents[2] / "docs" / "ai_research" / "charting_ni3_config_v1.json"


class NI3FingerprintMismatch(RuntimeError):
    """The configuration on disk is not NI-3 v1.0."""


def fingerprint(cfg: dict[str, Any]) -> str:
    """SHA-256 of the canonical JSON, computed exactly as the v1 `config_hash` is
    (`json.dumps(sort_keys=True, separators=(",", ":"))`) so the two are comparable."""
    return hashlib.sha256(json.dumps(cfg, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


@lru_cache(maxsize=1)
def load() -> dict[str, Any]:
    """The NI-3 configuration, verified against `NI3_FINGERPRINT`.

    Cached because it is read-only and every P-1/P-2 candidate would otherwise re-read and re-hash
    it. Returns the live dict; callers must not mutate it (see `p1()` / `shared()`, which return
    copies for exactly that reason)."""
    cfg = json.loads(NI3_CONFIG_PATH.read_text())
    got = fingerprint(cfg)
    if got != NI3_FINGERPRINT:
        raise NI3FingerprintMismatch(
            f"{NI3_CONFIG_PATH} hashes to {got}, not NI-3 v1.0 ({NI3_FINGERPRINT}). "
            "A detector running against it would not be implementing the frozen table."
        )
    return cfg


def p1() -> dict[str, Any]:
    """The P-1 geometry block (NI-3 §2): G1–G13."""
    return dict(load()["p1_geometry"])


def shared() -> dict[str, Any]:
    """The shared parameter block (NI-3 §1.7): S1–S10."""
    return dict(load()["shared"])
