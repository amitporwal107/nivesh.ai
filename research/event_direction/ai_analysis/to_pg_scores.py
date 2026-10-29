"""Write the filter's category, impact and sentiment onto the filings table.

The Research page's category chips, its "material" order and the "Read for you" cards all read
three columns of nidp.corporate_announcements: event_category, impact_score, sentiment. This turns
the filter verdicts in <work>/docs.jsonl into a psql script that fills them.

    python3 to_pg_scores.py --work work > scores.sql        # then run it against the NIDP database

It prints SQL and touches nothing itself. The script it prints:
  1. copies the previous values of every row it is about to change into
     nidp.event_ai_score_rollback (one batch id per run), so a run can be undone;
  2. updates the scored filings, matched on (announcement_id, source);
  3. gives every still-uncategorised filing in the window the category its subject line implies
     (ea_core.SUBJECT_CATEGORY), tagged 'subject-rule:v1'. To undo that step:
       UPDATE nidp.corporate_announcements SET event_category = NULL, impact_score = NULL,
              sentiment = NULL, classifier_version = NULL, classified_at = NULL
        WHERE classifier_version = 'subject-rule:v1';
     The data API leaves 'regulatory' and 'other' rows out of the default feed.
"""
from __future__ import annotations

import argparse
import csv
import io
import json
import re
import sys
from pathlib import Path

import ea_core as core

ID_RE = re.compile(r"^[0-9a-f]{40}$")
SOURCE_RE = re.compile(r"^[A-Z_]{1,20}$")
RULE_VERSION = "subject-rule:v1"
COLS = "announcement_id, source, event_category, impact_score, sentiment, classifier_version"


def score_rows(docs: list[dict], filter_sha: str) -> list[tuple]:
    """One (announcement_id, source, category, impact, sentiment, classifier_version) per filing
    judged under the current filter prompt. The latest verdict wins; a full analysis's net score
    decides the sentiment when there is one."""
    verdicts: dict[str, dict] = {}
    net: dict[str, tuple[str, int]] = {}
    for d in docs:
        aid = d.get("announcement_id") or ""
        if not ID_RE.match(aid):
            continue
        when = str(d.get("analyzed_at") or "")
        if d.get("mode") == core.ANALYSIS_MODE and isinstance(d.get("net_impact_score"), int):
            if aid not in net or when > net[aid][0]:
                net[aid] = (when, d["net_impact_score"])
        elif (d.get("mode") == core.FILTER_MODE and d.get("prompt_sha256") == filter_sha
              and d.get("category") in core.EVENT_CATEGORIES and SOURCE_RE.match(d.get("source") or "")):
            if aid not in verdicts or when > str(verdicts[aid].get("analyzed_at") or ""):
                verdicts[aid] = d
    rows = []
    for aid, v in sorted(verdicts.items()):
        n = net[aid][1] if aid in net else v["positive_impact_score"] - v["negative_impact_score"]
        rows.append((aid, v["source"], v["category"], core.impact_level(v["event_importance_score"]),
                     core.sentiment(n), f"{v['model_tag']}:{core.FILTER_MODE}:{filter_sha[:12]}"))
    return rows


def build_sql(rows: list[tuple], days: int) -> str:
    buf = io.StringIO()
    csv.writer(buf, lineterminator="\n").writerows(rows)
    q = lambda v: "'" + v.replace("'", "''") + "'"  # noqa: E731 — values are constants from ea_core
    subject_map = ",\n       ".join(f"({q(subj)}, {q(cat)})" for subj, cat in sorted(core.SUBJECT_CATEGORY.items()))
    return f"""\\set ON_ERROR_STOP on
BEGIN;
CREATE TABLE IF NOT EXISTS nidp.event_ai_score_rollback (
    batch_id text NOT NULL, saved_at timestamptz NOT NULL DEFAULT now(),
    announcement_id text NOT NULL, source text NOT NULL,
    event_category text, impact_score text, sentiment text, classifier_version text, classified_at timestamptz);
CREATE TEMP TABLE t_scores (announcement_id text, source text, event_category text, impact_score text,
                            sentiment text, classifier_version text) ON COMMIT DROP;
COPY t_scores ({COLS}) FROM STDIN WITH (FORMAT csv);
{buf.getvalue()}\\.
SELECT 'event-ai-' || to_char(now(), 'YYYYMMDD"T"HH24MISS') AS batch \\gset
INSERT INTO nidp.event_ai_score_rollback (batch_id, announcement_id, source, event_category, impact_score,
                                          sentiment, classifier_version, classified_at)
SELECT :'batch', c.announcement_id, c.source, c.event_category, c.impact_score, c.sentiment,
       c.classifier_version, c.classified_at
  FROM nidp.corporate_announcements c
  JOIN t_scores t ON c.announcement_id = t.announcement_id AND c.source = t.source
 WHERE (c.event_category, c.impact_score, c.sentiment, c.classifier_version)
       IS DISTINCT FROM (t.event_category, t.impact_score, t.sentiment, t.classifier_version);
UPDATE nidp.corporate_announcements c
   SET event_category = t.event_category, impact_score = t.impact_score, sentiment = t.sentiment,
       classifier_version = t.classifier_version, classified_at = now()
  FROM t_scores t
 WHERE c.announcement_id = t.announcement_id AND c.source = t.source
   AND (c.event_category, c.impact_score, c.sentiment, c.classifier_version)
       IS DISTINCT FROM (t.event_category, t.impact_score, t.sentiment, t.classifier_version);
-- subject rule: category from the exchange's own subject line, only where nothing is set yet.
-- It cannot judge impact or sentiment, so those stay NULL except for compliance paperwork.
CREATE TEMP TABLE t_subject (subject text PRIMARY KEY, event_category text) ON COMMIT DROP;
INSERT INTO t_subject VALUES
       {subject_map};
UPDATE nidp.corporate_announcements c
   SET event_category = m.event_category,
       impact_score = CASE WHEN m.event_category = 'regulatory' THEN 'low' END,
       sentiment = CASE WHEN m.event_category = 'regulatory' THEN 'neutral' END,
       classifier_version = '{RULE_VERSION}', classified_at = now()
  FROM t_subject m
 WHERE c.filed_at >= current_date - {int(days)} AND c.event_category IS NULL
   AND lower(btrim(c.subject)) = m.subject;
COMMIT;
SELECT coalesce(classifier_version, 'unclassified') AS classifier, count(*) AS filings
  FROM nidp.corporate_announcements WHERE filed_at >= current_date - {int(days)} GROUP BY 1 ORDER BY 2 DESC;
"""


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description="Print the SQL that writes event AI scores to nidp.corporate_announcements")
    p.add_argument("--work", required=True, type=Path)
    p.add_argument("--days", type=int, default=7, help="window for the subject rule and the summary")
    a = p.parse_args(argv)
    here = Path(__file__).resolve().parent
    sha = core.prompt_sha((here / "prompts" / "filter_v1.md").read_text())
    docs_path = a.work / "docs.jsonl"
    docs = [json.loads(line) for line in docs_path.read_text().splitlines() if line.strip()] if docs_path.exists() else []
    rows = score_rows(docs, sha)
    print(f"{len(rows)} filings scored under the current filter prompt", file=sys.stderr)
    sys.stdout.write(build_sql(rows, a.days))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
