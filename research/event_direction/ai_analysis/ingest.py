"""Post analysis documents to the backend's ingest API (Mongo event_ai_analysis).

    POST <app>/api/internal/event-ai-analysis/bulk     header X-Event-AI-Key

The key is read from the EVENT_AI_INGEST_KEY environment variable and is never printed. Upserts
are idempotent, so a re-send is harmless; <work>/ingested.txt only saves the repeat traffic.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.error
import urllib.request
from pathlib import Path

BATCH = 200                     # the API's MAX_DOCS
APP_URL = "https://staging.niveshcopilot.com"


def post(url: str, key: str, docs: list[dict]) -> dict:
    req = urllib.request.Request(
        url, data=json.dumps({"docs": docs}).encode(), method="POST",
        headers={"Content-Type": "application/json", "X-Event-AI-Key": key, "User-Agent": "nivesh-event-ai/1"})
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            return json.loads(r.read())
    except urllib.error.HTTPError as e:
        raise RuntimeError(f"ingest API returned HTTP {e.code}: {e.read()[:200].decode(errors='replace')}") from e


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description="Post event AI analysis documents to the backend")
    p.add_argument("--work", required=True, type=Path)
    p.add_argument("--app-url", default=os.environ.get("EVENT_AI_APP_URL", APP_URL))
    a = p.parse_args(argv)

    key = os.environ.get("EVENT_AI_INGEST_KEY", "")
    if not key:
        print("EVENT_AI_INGEST_KEY is not set — nothing posted", file=sys.stderr)
        return 3
    docs_path, sent_path = a.work / "docs.jsonl", a.work / "ingested.txt"
    docs = [json.loads(line) for line in docs_path.read_text().splitlines() if line.strip()] if docs_path.exists() else []
    sent = set(sent_path.read_text().split()) if sent_path.exists() else set()
    todo = [d for d in docs if d["_id"] not in sent]
    tally = {"docs": len(docs), "to_post": len(todo), "posted": 0, "rejected": 0}

    url = a.app_url.rstrip("/") + "/api/internal/event-ai-analysis/bulk"
    for i in range(0, len(todo), BATCH):
        batch = todo[i:i + BATCH]
        res = post(url, key, batch)
        bad = {r.get("_id") for r in res.get("rejected") or []}
        for r in res.get("rejected") or []:
            print(f"rejected by the API — {r.get('_id')}: {r.get('reason')}", file=sys.stderr)
        ok = [d["_id"] for d in batch if d["_id"] not in bad]
        with open(sent_path, "a") as fh:
            fh.write("".join(f"{i}\n" for i in ok))
        tally["posted"] += len(ok)
        tally["rejected"] += len(bad)
    print(json.dumps(tally))
    return 1 if tally["rejected"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
