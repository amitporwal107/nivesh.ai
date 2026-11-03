# Corporate-event AI analysis

Reads recent exchange filings, judges which ones matter, analyses those in full, and posts the
results to the backend, where the Research page shows them as the insight line on a filing card
and the tabs in its drawer. It replaces the OpenAI-based `announcement_classifier` and
`filing_insights` jobs for that purpose.

This is a rebuild (2026-10-12). The original pipeline lived only on the old GCP staging VM and was
lost with it, including its prompts. The prompts in `prompts/` are new.

## How it runs

```
DAYS=3 MAX_FILINGS=250 MAX_FILTER=250 MAX_ANALYSES=40 ./pipeline.sh
```

| Stage | File | Where | What it does |
|---|---|---|---|
| collect | `collect.py`, `ocr.py` | backend image (needs httpx, pdfplumber; tesseract + pdftoppm for OCR) | Lists filings from the NIDP data API, downloads each PDF from the exchange archive, OCRs the pages that are scanned images, keeps the first 12,000 characters of text |
| analyse | `analyse.py` | host | Importance filter in batches of 20, then one full analysis per kept filing |
| ingest | `ingest.py` | host | `POST /api/internal/event-ai-analysis/bulk` (Mongo `event_ai_analysis`) |

Every stage skips what it has already done, so a re-run only costs the new filings.

## The model call

Claude Code CLI in print mode, model `claude-sonnet-5-5`, with no tools, no MCP servers and no
settings, started in an empty directory. The model sees the prompt and the filing and nothing else.
Filings are untrusted text; with tools off, nothing a filing says can be acted on. Each stored
document carries `tool_isolation = tools_off+isolated`, and the backend's readers ignore documents
without it.

The calls use the Claude Code login of the user running the pipeline, so they count against that
account's usage. One day of NSE filings is roughly 15 filter calls plus one call per kept filing.

## What gets an insight

- **Skipped without a model call:** the compliance subjects in `ea_core.ROUTINE_SUBJECTS` (about
  half of all filings; mostly the quarterly depository certificate). Their cards show the exchange
  label.
- **Filtered:** everything else gets an importance score (0-100). Below 60 the card reads
  "Assessed as routine (importance N/100): why".
- **Analysed in full:** importance 60 or above, when the document text could be read. The card
  shows the summary, the headline figure and the favourable / unfavourable factors.

Model output is validated before it is stored (`ea_core.clean_filter`, `ea_core.clean_analysis`):
scores outside their range, unknown ids and empty summaries are rejected and reported on stderr,
never stored. The band (`slightly_positive` ...) is derived from the score here, not taken from
the model. The filing text itself is never stored.

## Configuration

- **Data API credentials:** copied at run time from the backend container's environment.
- **Ingest key:** `~/.config/nivesh/event-ai-ingest-key` (owner-only), or `EVENT_AI_INGEST_KEY`.
  It must equal the backend's `EVENT_AI_INGEST_KEY` secret (Admin → Secrets). The backend loads
  secrets at startup, so restart it after changing the secret.
- **Working files:** `work/` (git-ignored): `filings/<id>.json`, `docs.jsonl`, `ingested.txt`.

## Scanned pages (OCR)

Many results filings are a typed cover letter followed by scanned result pages (Bajaj Auto, 27 Oct
2026: 1,446 characters of cover letter and 19 image pages). `ocr.py` reads every page (of the first
eight) with fewer than 200 characters of text through `pdftoppm` (300 dpi, greyscale) and
`tesseract` (`--psm 4`, measured to read results tables correctly; about 5 s a page). Each OCR'd page
is marked in the text as read by OCR, so the model knows its figures can carry recognition errors.
The status is then `OK_OCR`, and the record lists `low_text_pages`, `ocr_pages` and `ocr`.

- **Without tesseract** (the backend image before it was added) the text is the text layer alone,
  as before, and the record still lists the pages with no text. When tesseract arrives, those
  filings (within the run's `DAYS`) are collected again and OCR'd, up to `MAX_OCR` (30) a run.
- **Filings collected before OCR existed** do not list their pages. `REOCR_SINCE=YYYY-MM-DD`
  collects again those from that date with no text, or with under 4,000 characters on a subject
  that carries figures (results, presentations, press releases, call transcripts, business updates).
- **Judged and analysed again:** every verdict and analysis records the hash of the text it was
  made from. When OCR changes a filing's text, the filing is judged and analysed again; the new
  document keeps its `_id`, so the API replaces the old one. `ingested.txt` records versions
  (`_id|analyzed_at`) so the new version is posted; older bare-`_id` lines stand for the first version.

## Changing a prompt

A stored document's id includes the first 12 characters of the prompt's SHA-256, and "already
done" is judged per prompt. Editing a prompt therefore re-judges every collected filing on the
next run, and the new documents sit beside the old ones. Changing `FILTER_TEXT_CHARS` or
`ANALYSIS_TEXT_CHARS` does not change the hash; move `work/docs.jsonl` aside if you want a re-run.

## Not done

- Materiality scores are not written to `nidp.corporate_announcements`, so the "material" sort and
  the top signal cards are still ordered by time. The original pipeline did this with
  `to_pg_scores.py`, which is also lost.
- No schedule. Nothing runs this until someone does.
- The Research page labels these insights "claude-sonnet-5 (corporate-event analysis)"
  (`backend/services/event_ai_insight.py`); the runs use `claude-sonnet-5-5`.
- `work/filings/` is never pruned.

## Tests

```
sudo docker run --rm --network none -v "$PWD":/work:ro -w /work -e PYTHONDONTWRITEBYTECODE=1 \
  --entrypoint python nivesh/backend:staging -m pytest research/event_direction/ai_analysis/tests -q -p no:cacheprovider
```
