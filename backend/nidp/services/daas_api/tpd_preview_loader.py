"""Load a `forward_v4 score --preview` snapshot into nidp.tpd_preview_* (migration 158). Insert-only and idempotent
(snapshot_sha256 is unique). Refuses anything that is not a preview that does NOT count toward the verdict: this loader can
never put a counted-looking run anywhere, and it never touches nidp.tpd_runs.

    python -m nidp.services.daas_api.tpd_preview_loader --snapshot <dir> --label "NEW-UNIVERSE PREVIEW" [--apply]
Without --apply it prints the SQL. With --apply it pipes it to the staging Postgres container."""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import subprocess
import sys
from pathlib import Path

CONTAINER, DB, USER = "nidp-postgres-staging", "nidp_staging", "nidp_staging"
HEADS = ("p_up5_1d", "p_down5_1d", "p_up10_1d", "p_down10_1d")


def lit(v) -> str:
    return "'" + str(v).replace("'", "''") + "'"


def build_sql(snap: Path, label: str, note: str) -> str:
    man = json.loads((snap / "manifest.json").read_text())
    if not man.get("preview") or man.get("counts_toward_verdict"):
        raise SystemExit(f"{snap}: refused, this loader takes only preview snapshots that do not count toward the verdict")
    sha = hashlib.sha256((snap / "manifest.json").read_bytes()).hexdigest()
    rows = [r for r in csv.DictReader(open(snap / "tpd3_predictions.csv")) if r["head"] in HEADS]
    syms = {r["symbol"] for r in rows}
    vals = ",".join(f"({lit(r['head'])},{lit(r['symbol'])},{float(r['p_tpd3'])!r})" for r in rows)
    return (
        "BEGIN;\n"
        "INSERT INTO nidp.tpd_preview_runs (label, target_session, data_as_of, snapshot_sha256, git_sha, universe_size, scored, note) VALUES ("
        f"{lit(label)},{lit(man['target_session'])},{lit(man['data_as_of'])},{lit(sha)},{lit(man['git_sha'])},{int(man['universe_size'])},{len(syms)},{lit(note)}) "
        "ON CONFLICT (snapshot_sha256) DO NOTHING;\n"
        f"WITH r AS (SELECT preview_id FROM nidp.tpd_preview_runs WHERE snapshot_sha256 = {lit(sha)}),\n"
        f"v(head, symbol, p) AS (VALUES {vals})\n"
        "INSERT INTO nidp.tpd_preview_estimates (preview_id, head, symbol, p) SELECT r.preview_id, v.head, v.symbol, v.p FROM r, v ON CONFLICT DO NOTHING;\n"
        "COMMIT;\n")


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--snapshot", type=Path, required=True)
    ap.add_argument("--label", default="NEW-UNIVERSE PREVIEW")
    ap.add_argument("--note", default="Scored with newer model code than the frozen nightly. Not graded, never counts toward the verdict.")
    ap.add_argument("--apply", action="store_true")
    a = ap.parse_args(argv)
    sql = build_sql(a.snapshot, a.label, a.note)
    if not a.apply:
        sys.stdout.write(sql[:600] + "\n... (dry run; pass --apply)\n")
        return 0
    p = subprocess.run(["docker", "exec", "-i", CONTAINER, "psql", "-U", USER, "-d", DB, "-v", "ON_ERROR_STOP=1"], input=sql, text=True, capture_output=True)
    sys.stdout.write(p.stdout[-400:]); sys.stderr.write(p.stderr[-400:])
    return p.returncode


if __name__ == "__main__":
    raise SystemExit(main())
