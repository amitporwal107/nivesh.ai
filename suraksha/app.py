"""
SURAKSHA — 1-hour working prototype of the leak-proof examination system.

Single FastAPI process, SQLite, vanilla HTML/JS. Run:

    .venv/bin/python app.py        # then open http://127.0.0.1:8000

What it demonstrates (and nothing more — see README "Simplifications"):
  D1  every candidate gets a DIFFERENT paper of statistically equal difficulty
  D2  a paper is unreadable ciphertext until (window open) AND (biometric passes)
  D3  a leaked paper names its leaker; a fabricated one is stamped FABRICATED

Security model of the prototype:
  * MASTER_KEY lives only in this process's memory (os.urandom, never written).
  * Per-candidate key = HKDF-SHA256(MASTER_KEY, info=candidate_id).
  * Each assembled paper is AES-256-GCM sealed; ONLY the ciphertext reaches SQLite.
  * The watermark (question order + option order) is part of that sealed plaintext,
    so forensics has to go through the key service too.
"""

from __future__ import annotations

import hashlib
import json
import os
import random
import sqlite3
import time
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path

from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.hkdf import HKDF
from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, JSONResponse
from pydantic import BaseModel

BASE = Path(__file__).resolve().parent
STATIC = BASE / "static"
DB_PATH = BASE / "suraksha.db"

BANK_SEED = 20260727          # fixed -> the item bank is reproducible
ITEMS_PER_VARIANT = 10
TARGET_MEAN_B = 0.0
MEAN_B_TOLERANCE = 0.15
HOST = os.environ.get("SURAKSHA_HOST", "127.0.0.1")
PORT = int(os.environ.get("SURAKSHA_PORT", "8000"))

DEFAULT_WINDOW_DELAY_MIN = float(os.environ.get("SURAKSHA_WINDOW_DELAY_MIN", "1.0"))
DEFAULT_WINDOW_DURATION_MIN = 30.0
FORENSICS_THRESHOLD = 6            # >= 6 of 10 positions in matching order

# ---------------------------------------------------------------------------
# Key service (simulated HSM). Process memory only — never persisted.
# ---------------------------------------------------------------------------
MASTER_KEY = os.urandom(32)


def candidate_key(candidate_id: str) -> bytes:
    return HKDF(
        algorithm=hashes.SHA256(),
        length=32,
        salt=b"suraksha-prototype-v0",
        info=candidate_id.encode(),
    ).derive(MASTER_KEY)


def seal(candidate_id: str, payload: dict) -> bytes:
    nonce = os.urandom(12)
    ct = AESGCM(candidate_key(candidate_id)).encrypt(
        nonce, json.dumps(payload).encode(), candidate_id.encode()
    )
    return nonce + ct


def unseal(candidate_id: str, blob: bytes) -> dict:
    plain = AESGCM(candidate_key(candidate_id)).decrypt(
        blob[:12], blob[12:], candidate_id.encode()
    )
    return json.loads(plain)


# ---------------------------------------------------------------------------
# Storage
# ---------------------------------------------------------------------------
def db() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


SCHEMA = """
CREATE TABLE IF NOT EXISTS items (
    id TEXT PRIMARY KEY, subject TEXT, topic TEXT, stem TEXT,
    options TEXT, correct INTEGER, b REAL, author_id TEXT
);
CREATE TABLE IF NOT EXISTS candidates (
    id TEXT PRIMARY KEY, name TEXT, passphrase TEXT
);
CREATE TABLE IF NOT EXISTS variants (
    candidate_id TEXT PRIMARY KEY, ciphertext BLOB, mean_b REAL, n_items INTEGER
);
CREATE TABLE IF NOT EXISTS answers (
    candidate_id TEXT, q_index INTEGER, choice INTEGER, ts TEXT,
    PRIMARY KEY (candidate_id, q_index)
);
CREATE TABLE IF NOT EXISTS ledger (
    id INTEGER PRIMARY KEY AUTOINCREMENT, ts TEXT, actor TEXT,
    action TEXT, detail TEXT, prev_hash TEXT, hash TEXT
);
CREATE TABLE IF NOT EXISTS config (key TEXT PRIMARY KEY, value TEXT);
"""

GENESIS = "0" * 64


def row_hash(prev_hash: str, ts: str, actor: str, action: str, detail: str) -> str:
    return hashlib.sha256(
        f"{prev_hash}|{ts}|{actor}|{action}|{detail}".encode()
    ).hexdigest()


def ledger_append(conn: sqlite3.Connection, actor: str, action: str, detail: str) -> None:
    prev = conn.execute("SELECT hash FROM ledger ORDER BY id DESC LIMIT 1").fetchone()
    prev_hash = prev["hash"] if prev else GENESIS
    ts = datetime.now(timezone.utc).isoformat()
    conn.execute(
        "INSERT INTO ledger (ts, actor, action, detail, prev_hash, hash) VALUES (?,?,?,?,?,?)",
        (ts, actor, action, detail, prev_hash, row_hash(prev_hash, ts, actor, action, detail)),
    )
    conn.commit()


# ---------------------------------------------------------------------------
# Seeding: 60 items, 6 candidates
# ---------------------------------------------------------------------------
TOPICS = ["optics", "kinematics", "thermodynamics", "electrostatics",
          "waves", "magnetism", "gravitation", "modern physics"]
UNITS = ["m/s", "J", "N", "V", "Hz", "T", "W", "eV"]
SETTERS = [f"SETTER-{i}" for i in range(1, 6)]

CANDIDATES = [
    ("C1", "priya", "finger1"), ("C2", "rohan", "finger2"), ("C3", "aisha", "finger3"),
    ("C4", "vikram", "finger4"), ("C5", "meera", "finger5"), ("C6", "arjun", "finger6"),
]


def seed_bank(conn: sqlite3.Connection) -> None:
    if conn.execute("SELECT COUNT(*) c FROM items").fetchone()["c"]:
        return
    rng = random.Random(BANK_SEED)
    for i in range(1, 61):
        topic, unit = TOPICS[i % len(TOPICS)], UNITS[i % len(UNITS)]
        # 4 distinct option values so option-order decoding is unambiguous
        vals = rng.sample(range(10, 990), 4)
        conn.execute(
            "INSERT INTO items VALUES (?,?,?,?,?,?,?,?)",
            (f"I{i:03d}", "Physics", topic,
             f"Q{i}: mock physics question about {topic}?",
             json.dumps([f"{v/10:.1f} {unit}" for v in vals]),
             rng.randrange(4), round(rng.uniform(-2, 2), 3), rng.choice(SETTERS)),
        )
    for cid, name, passphrase in CANDIDATES:
        conn.execute("INSERT INTO candidates VALUES (?,?,?)", (cid, name, passphrase))
    conn.commit()
    ledger_append(conn, "system", "BANK_SEEDED",
                  f"60 items / {len(CANDIDATES)} candidates / bank_seed={BANK_SEED}")


# ---------------------------------------------------------------------------
# Assembly: greedy pick + swap optimisation, then seeded permutation watermark
# ---------------------------------------------------------------------------
def mean_b(sel: list[dict]) -> float:
    return sum(i["b"] for i in sel) / len(sel)


def assemble(items: list[dict], candidate_id: str) -> list[dict]:
    """Pick ITEMS_PER_VARIANT items whose mean difficulty sits on TARGET_MEAN_B."""
    rng = random.Random(f"assembly::{candidate_id}")
    pool = list(items)
    rng.shuffle(pool)
    chosen, rest = pool[:ITEMS_PER_VARIANT], pool[ITEMS_PER_VARIANT:]
    for _ in range(200):
        cur = abs(mean_b(chosen) - TARGET_MEAN_B)
        if cur < 0.02:
            break
        best = None
        for ci in range(len(chosen)):
            for ri in range(len(rest)):
                trial = chosen[:ci] + [rest[ri]] + chosen[ci + 1:]
                d = abs(mean_b(trial) - TARGET_MEAN_B)
                if d < cur - 1e-9 and (best is None or d < best[0]):
                    best = (d, ci, ri)
        if best is None:
            break
        _, ci, ri = best
        chosen[ci], rest[ri] = rest[ri], chosen[ci]
    return chosen


def build_variant(items: list[dict], candidate_id: str) -> dict:
    """Assemble + apply the permutation watermark. Returns the paper PLAINTEXT."""
    chosen = assemble(items, candidate_id)
    if len({i["id"] for i in chosen}) != ITEMS_PER_VARIANT:
        raise RuntimeError(f"duplicate item inside variant for {candidate_id}")

    rng = random.Random(f"watermark::{candidate_id}")
    rng.shuffle(chosen)                                  # watermark channel 1: question order
    questions = []
    for it in chosen:
        opts = json.loads(it["options"])
        perm = list(range(4))
        rng.shuffle(perm)                                # watermark channel 2: option order
        questions.append({
            "item_id": it["id"],
            "stem": it["stem"],
            "topic": it["topic"],
            "b": it["b"],
            "options": [opts[p] for p in perm],
            "correct": perm.index(it["correct"]),
            "option_perm": perm,
        })
    return {
        "candidate_id": candidate_id,
        "watermark": f"CANDIDATE-{candidate_id}",
        "mean_b": round(mean_b(chosen), 4),
        "questions": questions,
    }


def rebuild_variants(conn: sqlite3.Connection) -> None:
    """Re-assemble + re-seal every paper under THIS process's master key.

    Assembly is deterministic (seeded by candidate id), so the papers are identical
    across restarts; only the ciphertext changes, because MASTER_KEY is ephemeral.
    """
    items = [dict(r) for r in conn.execute("SELECT * FROM items")]
    for row in conn.execute("SELECT id FROM candidates ORDER BY id").fetchall():
        cid = row["id"]
        paper = build_variant(items, cid)
        conn.execute(
            "INSERT OR REPLACE INTO variants VALUES (?,?,?,?)",
            (cid, seal(cid, paper), paper["mean_b"], len(paper["questions"])),
        )
        ledger_append(conn, "assembly-engine", "VARIANT_SEALED",
                      f"{cid} items={len(paper['questions'])} mean_b={paper['mean_b']:+.4f} "
                      f"alg=AES-256-GCM watermark_seed=watermark::{cid}")
    conn.commit()


# ---------------------------------------------------------------------------
# Exam window
# ---------------------------------------------------------------------------
def set_window(conn: sqlite3.Connection, minutes_from_now: float, duration_min: float,
               actor: str = "system") -> tuple[datetime, datetime]:
    start = datetime.now(timezone.utc) + timedelta(minutes=minutes_from_now)
    end = start + timedelta(minutes=duration_min)
    conn.execute("INSERT OR REPLACE INTO config VALUES ('window_start', ?)", (start.isoformat(),))
    conn.execute("INSERT OR REPLACE INTO config VALUES ('window_end', ?)", (end.isoformat(),))
    conn.commit()
    ledger_append(conn, actor, "WINDOW_SET", f"start={start.isoformat()} end={end.isoformat()}")
    return start, end


def get_window(conn: sqlite3.Connection) -> tuple[datetime, datetime]:
    rows = {r["key"]: r["value"] for r in conn.execute("SELECT * FROM config")}
    return (datetime.fromisoformat(rows["window_start"]),
            datetime.fromisoformat(rows["window_end"]))


# ---------------------------------------------------------------------------
# App
# ---------------------------------------------------------------------------
@asynccontextmanager
async def lifespan(_app: FastAPI):
    conn = db()
    conn.executescript(SCHEMA)
    seed_bank(conn)
    rebuild_variants(conn)          # fresh seal under this process's ephemeral master key
    start, end = set_window(conn, DEFAULT_WINDOW_DELAY_MIN, DEFAULT_WINDOW_DURATION_MIN)
    conn.close()
    banner = [
        "=" * 66,
        f"  SURAKSHA prototype ready — http://{HOST}:{PORT}",
        f"  exam window opens at {start.astimezone().strftime('%H:%M:%S')} "
        f"(closes {end.astimezone().strftime('%H:%M:%S')})",
        "  candidates: " + ", ".join(f"{c}/{n}/{p}" for c, n, p in CANDIDATES),
        "=" * 66,
    ]
    print("\n" + "\n".join(banner) + "\n", flush=True)
    yield


app = FastAPI(title="SURAKSHA prototype", version="0.1", lifespan=lifespan)


def page(name: str) -> FileResponse:
    return FileResponse(STATIC / name)


@app.get("/")
def index():
    return page("index.html")


@app.get("/terminal")
def terminal():
    return page("terminal.html")


@app.get("/dashboard")
def dashboard():
    return page("dashboard.html")


@app.get("/api/candidates")
def api_candidates():
    conn = db()
    try:  # passphrases are deliberately NOT returned
        return [{"id": r["id"], "name": r["name"]}
                for r in conn.execute("SELECT id, name FROM candidates ORDER BY id")]
    finally:
        conn.close()


@app.get("/api/window")
def api_window():
    conn = db()
    try:
        start, end = get_window(conn)
    finally:
        conn.close()
    now = datetime.now(timezone.utc)
    return {
        "start": start.isoformat(), "end": end.isoformat(), "now": now.isoformat(),
        "open": start <= now <= end,
        "seconds_until_open": max(0, int((start - now).total_seconds())),
        "seconds_until_close": max(0, int((end - now).total_seconds())),
    }


class WindowReq(BaseModel):
    minutes_from_now: float = 0.0
    duration_minutes: float = DEFAULT_WINDOW_DURATION_MIN


@app.post("/api/admin/set_window")
def api_set_window(req: WindowReq):
    conn = db()
    try:
        start, end = set_window(conn, req.minutes_from_now, req.duration_minutes, actor="admin")
    finally:
        conn.close()
    return {"start": start.isoformat(), "end": end.isoformat()}


class OpenReq(BaseModel):
    candidate_id: str
    passphrase: str


def refuse(conn: sqlite3.Connection, candidate_id: str, reason: str, detail: str):
    ledger_append(conn, candidate_id, reason, detail)
    return JSONResponse(status_code=403, content={"reason": reason, "detail": detail})


@app.post("/api/exam/open")
def api_exam_open(req: OpenReq):
    """The 3-condition key release: valid window + biometric match -> decrypt."""
    conn = db()
    try:
        cand = conn.execute("SELECT * FROM candidates WHERE id=?", (req.candidate_id,)).fetchone()
        if cand is None:
            return refuse(conn, req.candidate_id, "REFUSED_AUTH", "unknown candidate")

        now = datetime.now(timezone.utc)
        start, end = get_window(conn)
        if now < start:
            return refuse(conn, cand["id"], "REFUSED_EARLY",
                          f"key requested {int((start - now).total_seconds())}s before window open")
        if now > end:
            return refuse(conn, cand["id"], "REFUSED_LATE", "key requested after window close")
        if req.passphrase != cand["passphrase"]:
            return refuse(conn, cand["id"], "REFUSED_AUTH", "biometric mismatch")

        blob = conn.execute("SELECT ciphertext FROM variants WHERE candidate_id=?",
                            (cand["id"],)).fetchone()["ciphertext"]
        paper = unseal(cand["id"], blob)
        ledger_append(conn, cand["id"], "KEY_RELEASED",
                      f"biometric=OK window=OK bytes={len(blob)}")
        saved = {r["q_index"]: r["choice"]
                 for r in conn.execute("SELECT q_index, choice FROM answers WHERE candidate_id=?",
                                       (cand["id"],))}
    finally:
        conn.close()

    return {
        "candidate_id": cand["id"], "name": cand["name"], "watermark": paper["watermark"],
        "saved_answers": saved,
        # `correct` and `option_perm` stay server-side; the client never sees the key
        "questions": [{"item_id": q["item_id"], "stem": q["stem"], "options": q["options"]}
                      for q in paper["questions"]],
    }


class AnswerReq(BaseModel):
    candidate_id: str
    q_index: int
    choice: int


@app.post("/api/exam/answer")
def api_answer(req: AnswerReq):
    conn = db()
    try:
        conn.execute("INSERT OR REPLACE INTO answers VALUES (?,?,?,?)",
                     (req.candidate_id, req.q_index, req.choice,
                      datetime.now(timezone.utc).isoformat()))
        conn.commit()
    finally:
        conn.close()
    return {"saved": True}


class SubmitReq(BaseModel):
    candidate_id: str


@app.post("/api/exam/submit")
def api_submit(req: SubmitReq):
    conn = db()
    try:
        row = conn.execute("SELECT ciphertext FROM variants WHERE candidate_id=?",
                           (req.candidate_id,)).fetchone()
        if row is None:
            raise HTTPException(404, "unknown candidate")
        paper = unseal(req.candidate_id, row["ciphertext"])
        saved = {r["q_index"]: r["choice"]
                 for r in conn.execute("SELECT q_index, choice FROM answers WHERE candidate_id=?",
                                       (req.candidate_id,))}
        score = sum(1 for i, q in enumerate(paper["questions"]) if saved.get(i) == q["correct"])
        total = len(paper["questions"])
        ledger_append(conn, req.candidate_id, "EXAM_SUBMITTED",
                      f"answered={len(saved)}/{total} score={score}")
    finally:
        conn.close()
    return {"candidate_id": req.candidate_id, "score": score, "total": total,
            "answered": len(saved)}


@app.get("/api/dashboard")
def api_dashboard():
    conn = db()
    try:
        rows = []
        for r in conn.execute(
            "SELECT c.id, c.name, v.mean_b, v.n_items, LENGTH(v.ciphertext) AS ct_bytes "
            "FROM candidates c LEFT JOIN variants v ON v.candidate_id=c.id ORDER BY c.id"
        ):
            acts = {a["action"] for a in conn.execute(
                "SELECT DISTINCT action FROM ledger WHERE actor=?", (r["id"],))}
            status = ("SUBMITTED" if "EXAM_SUBMITTED" in acts else
                      "IN EXAM" if "KEY_RELEASED" in acts else
                      "REFUSED" if acts else "WAITING")
            rows.append({"id": r["id"], "name": r["name"], "mean_b": r["mean_b"],
                         "n_items": r["n_items"], "ciphertext_bytes": r["ct_bytes"],
                         "status": status})
    finally:
        conn.close()
    means = [r["mean_b"] for r in rows if r["mean_b"] is not None]
    return {"candidates": rows,
            "max_pairwise_delta_mean_b": round(max(means) - min(means), 4) if means else 0.0,
            "tolerance": MEAN_B_TOLERANCE}


class ForensicsReq(BaseModel):
    text: str


@app.post("/api/forensics")
def api_forensics(req: ForensicsReq):
    """Recover the permutation watermark from a leaked artifact's plain text.

    The item SET does not identify anyone — candidates share items. The ORDER does.
    """
    t0 = time.perf_counter()
    text = req.text
    conn = db()
    try:
        scores = []
        for row in conn.execute("SELECT candidate_id, ciphertext FROM variants ORDER BY candidate_id"):
            cid = row["candidate_id"]
            paper = unseal(cid, row["ciphertext"])
            qs = paper["questions"]

            # Where does each of this variant's stems appear in the leaked text?
            hits = [(text.find(q["stem"]), idx) for idx, q in enumerate(qs)]
            present = sorted((pos, idx) for pos, idx in hits if pos >= 0)
            recovered = [idx for _, idx in present]           # variant indices, in leak order
            order_match = sum(1 for slot, idx in enumerate(recovered) if slot == idx)

            # Second channel: within each question's slice of the leak, are the four
            # options in this candidate's permuted order?
            bounds = [pos for pos, _ in present] + [len(text)]
            option_match = 0
            for n, (_, idx) in enumerate(present):
                slice_ = text[bounds[n]:bounds[n + 1]]
                pos = [slice_.find(o) for o in qs[idx]["options"]]
                if all(p >= 0 for p in pos) and pos == sorted(pos):
                    option_match += 1

            scores.append({"candidate_id": cid, "items_found": len(recovered),
                           "order_match": order_match, "option_match": option_match,
                           "total": len(qs)})
    finally:
        conn.close()

    scores.sort(key=lambda s: (s["order_match"], s["option_match"]), reverse=True)
    best = scores[0]
    runner_up = scores[1] if len(scores) > 1 else None
    identified = best["order_match"] >= FORENSICS_THRESHOLD

    conn = db()
    try:
        name = None
        if identified:
            name = conn.execute("SELECT name FROM candidates WHERE id=?",
                                (best["candidate_id"],)).fetchone()["name"]
        ledger_append(conn, "forensics", "FORENSICS_RUN",
                      f"verdict={'IDENTIFIED:' + best['candidate_id'] if identified else 'FABRICATED'} "
                      f"order_match={best['order_match']}/{best['total']} chars={len(text)}")
    finally:
        conn.close()

    return {
        "verdict": "IDENTIFIED" if identified else "FABRICATED",
        "candidate_id": best["candidate_id"] if identified else None,
        "name": name,
        "confidence": f"{best['order_match']}/{best['total']}",
        "order_match": best["order_match"], "option_match": best["option_match"],
        "items_found": best["items_found"], "total": best["total"],
        "runner_up": runner_up,
        "elapsed_ms": round((time.perf_counter() - t0) * 1000, 1),
        "threshold": FORENSICS_THRESHOLD,
        "scores": scores,
    }


@app.get("/api/ledger")
def api_ledger(limit: int = 200):
    conn = db()
    try:
        return [dict(r) for r in conn.execute(
            "SELECT * FROM ledger ORDER BY id DESC LIMIT ?", (limit,))]
    finally:
        conn.close()


@app.get("/api/ledger/verify")
def api_ledger_verify():
    conn = db()
    try:
        rows = [dict(r) for r in conn.execute("SELECT * FROM ledger ORDER BY id")]
    finally:
        conn.close()
    prev = GENESIS
    for r in rows:
        expected = row_hash(prev, r["ts"], r["actor"], r["action"], r["detail"])
        if r["prev_hash"] != prev:
            return {"ok": False, "rows": len(rows), "broken_at": r["id"],
                    "reason": "prev_hash does not match the preceding row (row inserted/removed)"}
        if r["hash"] != expected:
            return {"ok": False, "rows": len(rows), "broken_at": r["id"],
                    "reason": f"row {r['id']} content was modified after it was written"}
        prev = r["hash"]
    return {"ok": True, "rows": len(rows), "broken_at": None, "head": prev}


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host=HOST, port=PORT, log_level="warning")
