"""Run the importance filter and the full impact analysis over collected filings.

Every model call goes through the Claude Code CLI in print mode with no tools, no MCP servers and
no settings, from an empty directory: the model sees the prompt and the filing and nothing else,
and cannot act on anything a filing says. That is what `tool_isolation = tools_off+isolated`
records, and the backend's readers ignore documents without it.

Reads  <work>/filings/<id>.json   (written by collect.py)
Writes <work>/docs.jsonl          (appended after every call; ingest.py posts it)
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path

import ea_core as core

HERE = Path(__file__).resolve().parent
MODEL = "claude-sonnet-5-5"
CLAUDE = shutil.which("claude") or os.path.expanduser("~/.local/bin/claude")
CALL_TIMEOUT = 600


# Running totals for the whole run, so the cost of a run is measured rather than estimated.
USAGE = {"calls": 0, "cost_usd": 0.0, "input_tokens": 0, "cache_read_tokens": 0,
         "cache_write_tokens": 0, "output_tokens": 0}


def _record_usage(out: dict) -> None:
    u = out.get("usage") or {}
    USAGE["calls"] += 1
    USAGE["cost_usd"] += float(out.get("total_cost_usd") or 0)
    USAGE["input_tokens"] += int(u.get("input_tokens") or 0)
    USAGE["cache_read_tokens"] += int(u.get("cache_read_input_tokens") or 0)
    USAGE["cache_write_tokens"] += int(u.get("cache_creation_input_tokens") or 0)
    USAGE["output_tokens"] += int(u.get("output_tokens") or 0)


def run_claude(system: str, user: str, schema: dict) -> dict:
    """One isolated, tool-less model call returning the schema-shaped answer. Raises RuntimeError.
    The filing text goes in on stdin, never argv."""
    cwd = tempfile.mkdtemp(prefix="event-ai-")
    cmd = [CLAUDE, "-p", "--model", MODEL, "--tools", "", "--strict-mcp-config", "--setting-sources", "",
           "--no-session-persistence", "--system-prompt", system, "--output-format", "json",
           "--json-schema", json.dumps(schema)]
    try:
        r = subprocess.run(cmd, input=user, capture_output=True, text=True, cwd=cwd, timeout=CALL_TIMEOUT)
    except subprocess.TimeoutExpired as e:
        raise RuntimeError(f"model call timed out after {CALL_TIMEOUT}s") from e
    finally:
        shutil.rmtree(cwd, ignore_errors=True)
    if r.returncode != 0:
        raise RuntimeError(f"claude exited {r.returncode}: {r.stderr.strip()[:300]}")
    try:
        out = json.loads(r.stdout)
    except ValueError as e:
        raise RuntimeError(f"claude returned non-JSON output: {r.stdout[:200]!r}") from e
    _record_usage(out)
    if out.get("is_error"):
        raise RuntimeError(f"claude reported an error: {str(out.get('result'))[:300]}")
    answer = out.get("structured_output")
    if not isinstance(answer, dict):
        raise RuntimeError("claude returned no structured answer")
    if MODEL not in (out.get("modelUsage") or {}):
        raise RuntimeError(f"answer did not come from {MODEL}: {sorted(out.get('modelUsage') or {})}")
    return answer


def load_filings(work: Path) -> dict[str, dict]:
    out = {}
    for p in sorted((work / "filings").glob("*.json")):
        f = json.loads(p.read_text())
        out[f["id"]] = f
    return out


def load_docs(work: Path) -> list[dict]:
    p = work / "docs.jsonl"
    return [json.loads(line) for line in p.read_text().splitlines() if line.strip()] if p.exists() else []


def _append(work: Path, doc: dict) -> None:
    with open(work / "docs.jsonl", "a") as fh:
        fh.write(json.dumps(doc, ensure_ascii=False) + "\n")


def _filter_input(f: dict) -> dict:
    return {"id": f["id"], "company": f.get("company"), "symbol": f.get("symbol"), "subject": f.get("title"),
            "summary": f.get("summary"), "text": (f.get("text") or "")[:core.FILTER_TEXT_CHARS]}


def _analysis_input(f: dict) -> str:
    return json.dumps({"company": f.get("company"), "symbol": f.get("symbol"), "subject": f.get("title"),
                       "summary": f.get("summary"), "filed_at": f.get("when"),
                       "document_text": (f.get("text") or "")[:core.ANALYSIS_TEXT_CHARS]}, ensure_ascii=False)


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description="Filter and analyse collected filings with Claude (tools off)")
    p.add_argument("--work", required=True, type=Path)
    p.add_argument("--max-filter", type=int, default=250, help="filings sent to the filter this run")
    p.add_argument("--max-analyses", type=int, default=40, help="full analyses this run")
    a = p.parse_args(argv)

    filter_prompt = (HERE / "prompts" / "filter_v1.md").read_text()
    analysis_prompt = (HERE / "prompts" / "analysis_v1.md").read_text()
    f_sha, a_sha = core.prompt_sha(filter_prompt), core.prompt_sha(analysis_prompt)
    filings, docs = load_filings(a.work), load_docs(a.work)
    verdicts = {d["announcement_id"]: d for d in docs if d.get("mode") == core.FILTER_MODE and d.get("prompt_sha256") == f_sha}
    analysed = {d["announcement_id"] for d in docs if d.get("mode") == core.ANALYSIS_MODE and d.get("prompt_sha256") == a_sha}
    tally = {"filings": len(filings), "filter_calls": 0, "filtered": 0, "kept": 0, "filter_problems": 0,
             "analysed": 0, "analysis_failed": 0, "call_errors": 0, "model": MODEL}

    todo = core.candidates(sorted(filings.values(), key=lambda f: str(f.get("when")), reverse=True), set(verdicts))
    todo = todo[:a.max_filter]
    for i in range(0, len(todo), core.BATCH):
        batch = todo[i:i + core.BATCH]
        tally["filter_calls"] += 1
        try:
            raw = run_claude(filter_prompt, json.dumps([_filter_input(f) for f in batch], ensure_ascii=False),
                             core.FILTER_SCHEMA)
        except RuntimeError as e:
            tally["call_errors"] += 1
            print(f"filter batch {i // core.BATCH + 1} failed: {e}", file=sys.stderr)
            continue
        good, problems = core.clean_filter(raw, [f["id"] for f in batch])
        tally["filter_problems"] += len(problems)
        for line in problems:
            print(f"filter verdict rejected — {line}", file=sys.stderr)
        now = datetime.now(timezone.utc)
        for f in batch:
            if f["id"] in good:
                d = core.filter_doc(f, good[f["id"]], f_sha, MODEL, now)
                _append(a.work, d)
                verdicts[f["id"]] = d
                tally["filtered"] += 1
                tally["kept"] += int(d["include"])

    pending = [v for v in verdicts.values() if v.get("include") and v["announcement_id"] not in analysed
               and (filings.get(v["announcement_id"]) or {}).get("text")]
    pending.sort(key=lambda v: v["event_importance_score"], reverse=True)
    # The same document is often filed more than once (a revised press release, the same PDF on
    # both exchanges). An analysis already made of identical text for the same company is reused.
    by_text = {}
    for d in docs:
        if d.get("mode") == core.ANALYSIS_MODE and d.get("prompt_sha256") == a_sha and d.get("text_sha256"):
            by_text[(d.get("symbol"), d["text_sha256"])] = d
    tally["analyses_reused"] = 0
    for v in pending[:a.max_analyses]:
        f = filings[v["announcement_id"]]
        key = (f.get("symbol"), core.text_sha(f.get("text") or ""))
        if key in by_text:
            d = core.reuse_analysis(by_text[key], f, datetime.now(timezone.utc))
            _append(a.work, d)
            tally["analyses_reused"] += 1
            continue
        try:
            clean = core.clean_analysis(run_claude(analysis_prompt, _analysis_input(f), core.ANALYSIS_SCHEMA))
        except (RuntimeError, ValueError) as e:
            tally["analysis_failed"] += 1
            print(f"analysis of {f['id']} ({f.get('symbol')}) failed: {e}", file=sys.stderr)
            continue
        d = core.analysis_doc(f, clean, a_sha, MODEL, datetime.now(timezone.utc))
        _append(a.work, d)
        by_text[key] = d
        tally["analysed"] += 1

    tally["kept_awaiting_analysis"] = max(0, len(pending) - a.max_analyses)
    tally["usage"] = {k: (round(v, 4) if isinstance(v, float) else v) for k, v in USAGE.items()}
    print(json.dumps(tally))
    return 1 if tally["call_errors"] and not tally["filtered"] and not tally["analysed"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
