"""Acceptance runner for the SURAKSHA prototype — executes TEST_CASES.md T01..T16.

Drives the REAL HTTP API of a running `app.py` (stdlib only, no test deps).

    .venv/bin/python app.py &        # terminal 1
    python3 acceptance.py            # terminal 2

Exits non-zero if any case fails.
"""

import json
import os
import sqlite3
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

BASE_URL = os.environ.get("SURAKSHA_URL", "http://127.0.0.1:8000").rstrip("/")
UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/126.0 Safari/537.36")
DB_PATH = Path(__file__).resolve().parent / "suraksha.db"

results: list[tuple[str, bool, str]] = []


def call(method: str, path: str, body: dict | None = None) -> tuple[int, dict]:
    data = json.dumps(body).encode() if body is not None else None
    headers = {"User-Agent": UA}          # Cloudflare 1010s a bare urllib UA
    if data:
        headers["Content-Type"] = "application/json"
    req = urllib.request.Request(BASE_URL + path, data=data, method=method, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=20) as r:
            return r.status, json.loads(r.read())
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read())


def check(tid: str, ok: bool, note: str) -> bool:
    results.append((tid, bool(ok), note))
    print(f"  {'PASS' if ok else 'FAIL'}  {tid}  {note}")
    return bool(ok)


def paper_text(paper: dict) -> str:
    """Byte-identical to the terminal's 'Copy paper text' (leak) output."""
    blocks = [f"{i + 1}. {q['stem']}\n" +
              "\n".join(f"   {'ABCD'[j]}) {o}" for j, o in enumerate(q["options"]))
              for i, q in enumerate(paper["questions"])]
    return f"SURAKSHA EXAM PAPER — {paper['watermark']}\n\n" + "\n\n".join(blocks)


def main() -> int:
    print("\n== T01 seed / candidate roster ==")
    st, cands = call("GET", "/api/candidates")
    check("T01", st == 200 and [c["id"] for c in cands] == [f"C{i}" for i in range(1, 7)]
          and all("passphrase" not in c for c in cands),
          f"HTTP {st}, {len(cands)} candidates, no passphrase leaked: {cands}")

    print("\n== T02/T03 pre-window key request is refused and ledgered ==")
    call("POST", "/api/admin/set_window", {"minutes_from_now": 5, "duration_minutes": 30})
    st, d = call("POST", "/api/exam/open", {"candidate_id": "C1", "passphrase": "finger1"})
    check("T02", st == 403 and d.get("reason") == "REFUSED_EARLY" and "questions" not in d,
          f"HTTP {st} {d.get('reason')} — {d.get('detail')}")
    _, led = call("GET", "/api/ledger")
    check("T03", any(r["action"] == "REFUSED_EARLY" and r["actor"] == "C1" for r in led),
          "REFUSED_EARLY row present for C1")

    print("\n== open the window ==")
    _, w = call("POST", "/api/admin/set_window", {"minutes_from_now": 0, "duration_minutes": 30})
    time.sleep(0.3)
    print(f"  window now {w['start']} .. {w['end']}")

    print("\n== T04 wrong biometric ==")
    st, d = call("POST", "/api/exam/open", {"candidate_id": "C1", "passphrase": "wrong-finger"})
    check("T04", st == 403 and d.get("reason") == "REFUSED_AUTH" and "questions" not in d,
          f"HTTP {st} {d.get('reason')} — {d.get('detail')}")

    print("\n== T05/T06 key release + per-candidate uniqueness ==")
    papers = {}
    for cid, pw in [("C1", "finger1"), ("C2", "finger2"), ("C3", "finger3"),
                    ("C4", "finger4"), ("C5", "finger5"), ("C6", "finger6")]:
        st, p = call("POST", "/api/exam/open", {"candidate_id": cid, "passphrase": pw})
        assert st == 200, (cid, st, p)
        papers[cid] = p
    c1, c2 = papers["C1"], papers["C2"]
    check("T05", c1["watermark"] == "CANDIDATE-C1" and len(c1["questions"]) == 10,
          f"C1 watermark={c1['watermark']} questions={len(c1['questions'])}")
    s1 = [q["item_id"] for q in c1["questions"]]
    s2 = [q["item_id"] for q in c2["questions"]]
    check("T06", s1 != s2, f"C1={s1}\n              C2={s2}")

    print("\n== T07 difficulty parity ==")
    _, dash = call("GET", "/api/dashboard")
    means = {c["id"]: c["mean_b"] for c in dash["candidates"]}
    check("T07", all(abs(m) < 0.15 for m in means.values())
          and dash["max_pairwise_delta_mean_b"] < 0.15,
          f"mean_b={means} max_pairwise_delta={dash['max_pairwise_delta_mean_b']} tol=0.15")

    print("\n== T08 uniqueness gate ==")
    seqs = {cid: [q["item_id"] for q in p["questions"]] for cid, p in papers.items()}
    no_dupe_within = all(len(set(s)) == 10 for s in seqs.values())
    all_unique = len({tuple(s) for s in seqs.values()}) == len(seqs)
    overlap = len(set(seqs["C1"]) & set(seqs["C2"]))
    check("T08", no_dupe_within and all_unique,
          f"6 distinct ordered variants, no repeat inside a variant "
          f"(C1∩C2 share {overlap} items — set alone does not identify)")

    print("\n== T09 forensics on a real leak (C2) ==")
    t0 = time.perf_counter()
    st, f = call("POST", "/api/forensics", {"text": paper_text(c2)})
    wall = (time.perf_counter() - t0) * 1000
    check("T09", f["verdict"] == "IDENTIFIED" and f["candidate_id"] == "C2"
          and f["order_match"] >= 6 and wall < 5000,
          f"{f['verdict']} {f['candidate_id']} ({f['name']}) order={f['confidence']} "
          f"options={f['option_match']}/{f['total']} in {f['elapsed_ms']}ms "
          f"(wall {wall:.0f}ms); runner-up {f['runner_up']['candidate_id']} "
          f"order={f['runner_up']['order_match']}/{f['runner_up']['total']}")

    print("\n== T10 fabricated artifact ==")
    st, f = call("POST", "/api/forensics", {"text":
        "Lorem ipsum dolor sit amet, consectetur adipiscing elit. Q99: leaked NEET paper "
        "about optics? A) 42 m/s B) 7 J C) 13 N D) 88 V. Trust me bro."})
    check("T10", f["verdict"] == "FABRICATED" and f["candidate_id"] is None,
          f"{f['verdict']} (best {f['confidence']}, threshold {f['threshold']}) {f['elapsed_ms']}ms")

    print("\n== T11 partial leak (first 6 questions only) ==")
    partial = "\n\n".join(paper_text(c2).split("\n\n")[:7])
    st, f = call("POST", "/api/forensics", {"text": partial})
    check("T11", f["verdict"] == "IDENTIFIED" and f["candidate_id"] == "C2",
          f"{f['verdict']} {f['candidate_id']} order={f['confidence']} from {len(partial)} chars")

    print("\n== T12 same items, different order -> must NOT be C2 ==")
    head, *blocks = paper_text(c2).split("\n\n")
    st, f = call("POST", "/api/forensics", {"text": head + "\n\n" + "\n\n".join(reversed(blocks))})
    check("T12", not (f["verdict"] == "IDENTIFIED" and f["candidate_id"] == "C2"),
          f"{f['verdict']} (best {f['candidate_id']} {f['confidence']}) — order IS the watermark")

    print("\n== T13 no assembled paper in plaintext at rest ==")
    raw = DB_PATH.read_bytes()
    wm_hits = raw.count(b"CANDIDATE-C")
    _, ct_rows = 0, sqlite3.connect(DB_PATH).execute(
        "SELECT candidate_id, ciphertext FROM variants").fetchall()
    ct_clean = all(b"mock physics question" not in blob for _, blob in ct_rows)
    check("T13", wm_hits == 0 and ct_clean,
          f"watermark string occurrences in {DB_PATH.name}: {wm_hits}; "
          f"{len(ct_rows)} variant blobs, none containing readable stems "
          f"(the item BANK is plaintext by design — assembled papers are not)")

    print("\n== T14 ledger chain intact ==")
    st, v = call("GET", "/api/ledger/verify")
    check("T14", v["ok"] is True, f"ok={v['ok']} rows={v['rows']} head={v.get('head', '')[:16]}…")

    print("\n== T15 tamper one ledger row -> detected at that exact row ==")
    conn = sqlite3.connect(DB_PATH)
    victim = conn.execute(
        "SELECT id, detail FROM ledger WHERE action='KEY_RELEASED' ORDER BY id LIMIT 1").fetchone()
    vid, original = victim
    conn.execute("UPDATE ledger SET detail=? WHERE id=?", ("biometric=SKIPPED (edited)", vid))
    conn.commit()
    st, v = call("GET", "/api/ledger/verify")
    tampered_ok = v["ok"] is False and v["broken_at"] == vid
    conn.execute("UPDATE ledger SET detail=? WHERE id=?", (original, vid))
    conn.commit()
    conn.close()
    st, v2 = call("GET", "/api/ledger/verify")
    check("T15", tampered_ok and v2["ok"] is True,
          f"edited row {vid} -> broken_at={v['broken_at']} ({v.get('reason')}); "
          f"restored -> ok={v2['ok']}")

    print("\n== T16 answer autosave + submit ==")
    for i in range(10):
        call("POST", "/api/exam/answer", {"candidate_id": "C1", "q_index": i, "choice": i % 4})
    st, s = call("POST", "/api/exam/submit", {"candidate_id": "C1"})
    _, led = call("GET", "/api/ledger")
    check("T16", st == 200 and s["answered"] == 10 and 0 <= s["score"] <= 10
          and any(r["action"] == "EXAM_SUBMITTED" and r["actor"] == "C1" for r in led),
          f"score={s['score']}/{s['total']} answered={s['answered']}, EXAM_SUBMITTED ledgered")

    failed = [t for t, ok, _ in results if not ok]
    print("\n" + "=" * 62)
    print(f"  {len(results) - len(failed)}/{len(results)} cases passed"
          + (f" — FAILED: {failed}" if failed else " — ALL PASS"))
    print("=" * 62)
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
