"""Append-only, concurrency-safe archive (ARC-01..05).

- Records: <root>/<kind>.jsonl.gz, one canonical-JSON line per record, appended as gzip members under an exclusive
  flock, so concurrent writers never interleave or truncate. Existing lines are never rewritten.
- Artifacts: <root>/artifacts/<sha256[:2]>/<sha256><suffix>, write-once. Re-storing identical bytes is a no-op;
  a hash collision with different bytes raises.
"""
from __future__ import annotations

import fcntl
import gzip
import json
import os
from typing import Iterable, Iterator

from contracts import canonical_json, sha256_bytes

DEFAULT_ROOT = "/app/research/pit_audit/nse"


class Archive:
    def __init__(self, root: str = DEFAULT_ROOT):
        self.root = os.path.abspath(root)
        os.makedirs(os.path.join(self.root, "artifacts"), exist_ok=True)

    def _path(self, kind: str) -> str:
        if not kind.replace("_", "").isalnum():
            raise ValueError(f"invalid archive kind {kind!r}")  # no path traversal through the kind
        return os.path.join(self.root, f"{kind}.jsonl.gz")

    def append(self, kind: str, records: Iterable[dict]) -> int:
        lines = [canonical_json(r) + "\n" for r in records]
        if not lines:
            return 0
        lock = self._path(kind) + ".lock"
        with open(lock, "a") as lf:
            fcntl.flock(lf, fcntl.LOCK_EX)
            try:
                with gzip.open(self._path(kind), "at", encoding="utf-8") as f:
                    f.writelines(lines)
                    f.flush()
            finally:
                fcntl.flock(lf, fcntl.LOCK_UN)
        return len(lines)

    def read(self, kind: str) -> Iterator[dict]:
        p = self._path(kind)
        if not os.path.exists(p):
            return
        with gzip.open(p, "rt", encoding="utf-8") as f:
            for line in f:
                if line.strip():
                    yield json.loads(line)

    def artifact_path(self, sha256: str, suffix: str = "") -> str:
        if len(sha256) != 64 or any(c not in "0123456789abcdef" for c in sha256):
            raise ValueError(f"invalid artifact hash {sha256!r}")
        return os.path.join(self.root, "artifacts", sha256[:2], sha256 + suffix)

    def store_artifact(self, data: bytes, suffix: str = "") -> tuple[str, str]:
        """Write-once content-addressed storage; returns (sha256, path)."""
        if suffix and (not suffix.startswith(".") or "/" in suffix or ".." in suffix):
            raise ValueError(f"invalid artifact suffix {suffix!r}")
        h = sha256_bytes(data)
        d = os.path.join(self.root, "artifacts", h[:2])
        os.makedirs(d, exist_ok=True)
        path = os.path.join(d, h + suffix)
        if os.path.exists(path):
            with open(path, "rb") as f:
                if sha256_bytes(f.read()) != h:
                    raise RuntimeError(f"artifact {path} is corrupt (hash mismatch)")
            return h, path
        tmp = f"{path}.tmp.{os.getpid()}"
        with open(tmp, "wb") as f:
            f.write(data)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, path)  # atomic: a reader never sees a partial artifact
        return h, path

    def verify_artifacts(self) -> list[str]:
        """Paths whose content no longer matches their name (should always be empty)."""
        bad = []
        for dp, _, fs in os.walk(os.path.join(self.root, "artifacts")):
            for fn in fs:
                if ".tmp." in fn:
                    bad.append(os.path.join(dp, fn))
                    continue
                with open(os.path.join(dp, fn), "rb") as f:
                    if sha256_bytes(f.read()) != fn.split(".")[0]:
                        bad.append(os.path.join(dp, fn))
        return bad
