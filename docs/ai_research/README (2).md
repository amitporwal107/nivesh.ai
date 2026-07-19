# Nivesh Copilot

**Filings-first AI stock research for Indian markets.** Every insight traces to
an authenticated exchange filing — if it isn't filed, it's a rumor.

Nivesh Copilot ingests corporate disclosures from BSE/NSE in near real time and
delivers two core experiences:

1. **Live corporate events feed** — categorized, AI-summarized, sentiment-badged
   and materiality-ranked filings (order wins, M&A, results, defaults, pledges…)
   within minutes of filing.
2. **Ask-anything Q&A with citations** — natural-language questions answered
   strictly from filed documents, every claim stamped to document + page, with
   "View Source" links to the original PDF on the exchange.

Signature feature: **rumor verification** — "no filing found; under SEBI LODR
Reg 30 a material event must be disclosed within 24 hours" is an answer no
WhatsApp forward can survive.

---

## Repository layout

```
docs/
  nivesh-copilot-prd.md                  # Product requirements (v1.0)
  nivesh-copilot-event-source-matrix.md  # Every event type -> primary source + URL
  nivesh-copilot-events-taxonomy-v2.md   # 12 families, 70+ event types, rubrics
  nivesh-copilot-question-bank.md        # 120 eval/suggested questions, routed
  nivesh-copilot-sample-answers.md       # Golden answer formats + behaviors
  nivesh-copilot-prompts.md              # Router + grounded-answerer prompts
  nivesh-copilot-design.html             # Product UI design (FILED-stamp system)

ingestion/
  bse-announcements-suite/               # Poller: all BSE categories/subcats,
                                         #   Nifty 500 filter, PDF download
  doctype-fix-pack/                      # Content-based doc classifier,
                                         #   backfill, annual-report feed

rag/
  filing-rag-starter/                    # Parse -> page chunks -> FTS5 + vectors
                                         #   hybrid search (RRF), query CLI
  embed-drain/                           # Backlog drainer: token-aware batches,
                                         #   SKIP LOCKED workers, TPM budget
  embedding-bakeoff/                     # Model selection harness (recall@5,
                                         #   MRR, judge sheet)

intelligence/
  sentiment-pack/
    announcement_analysis.py            # Summary + sentiment + materiality_score
    family_prompts.py                   # 12 family rubrics + trap-case few-shots
    transcript_tone.py                  # Tone records, hedging, QoQ deltas
```

## Architecture (5 layers)

```
[BSE/NSE pollers] -> [PDF store + Postgres metadata]
       -> [doctype classifier] -> [parse/chunk (page-anchored) + OCR fallback]
       -> [FTS5/BM25 + embeddings -> hybrid retrieval (RRF)]
       -> [router -> {RAG answerer | events DB | XBRL | verification}]
       -> [feed UI + chat UI with FILED-stamp citations]
Intelligence side-channel: sentiment/materiality per announcement,
tone records per transcript, lifecycle linking via linked_entity.
```

## Quick start (pipeline order)

```bash
# 1. Poll announcements + download filing PDFs (Nifty 500)
cd ingestion/bse-announcements-suite
pip install requests
python run_poller.py --priority-only --download-pdfs

# 2. Type the documents (transcripts / presentations / annual reports)
cd ../doctype-fix-pack
python backfill_doctypes.py --db ../../rag/filings.db --pdf-root ../bse-announcements-suite/out/pdfs --dry-run

# 3. Parse, chunk, index
cd ../../rag/filing-rag-starter
pip install pymupdf numpy requests
python rag.py ingest --pdf-dir ../../ingestion/bse-announcements-suite/out/pdfs \
                     --csv ../../ingestion/bse-announcements-suite/out/announcements.csv

# 4. Choose the embedding model ON YOUR DATA, then embed
cd ../embedding-bakeoff && python bakeoff.py --chunks chunks.jsonl \
    --questions questions.jsonl --a st:BAAI/bge-small-en-v1.5 --b st:Qwen/Qwen3-Embedding-0.6B
cd ../filing-rag-starter && python rag.py embed     # or embed-drain for backlogs

# 5. Test retrieval before any UI exists
python rag.py query          # '$SCRIPCODE your question' filters by company

# 6. Sentiment on new announcements (piggybacks the summarization call)
#    -> intelligence/sentiment-pack/announcement_analysis.py + family_prompts.py
```

## Design principles (non-negotiable)

1. **Citation or silence.** No excerpt supporting a claim -> the claim doesn't
   appear. Post-validate every [n] programmatically; retry once; fail to
   not_found. Zero tolerance for fabricated citations.
2. **Judge the event, not the tone.** All filings sound positive. Sentiment
   rubrics are per-family; a missing badge beats a wrong badge (badges only on
   valid + high-confidence + non-neutral).
3. **Pages are the citation unit.** Chunks never cross pages — that's what makes
   "Presentation, slide 14" links possible.
4. **Direct vs inferred, always badged.** A company filing and a sector
   inference (GST change -> affected companies) never look the same.
5. **No advice, ever.** No buy/sell, targets, or predictions — including
   advice-questions smuggled inside valid questions. Verification answers are
   deterministic DB checks; the LLM stays out of them.
6. **One embedding model for the whole corpus.** Mixed vector spaces silently
   ruin retrieval. Decide via the bake-off before draining.
7. **Monitor deltas and ages, not success counts.** A green cron embedding
   200/200 hid a 640K backlog. Alert on backlog delta/hour and oldest-item age.

## Operational notes

- **Exchange APIs are unofficial.** Endpoints verified against the maintained
  BseIndiaApi library (AnnSubCategoryGetData/w, strscrip lowercase, the
  Corp`.`Action backtick quirk) but can change without notice. Browser-like
  headers required; datacenter IPs may be blocked; keep >=1s throttle.
- **Licensing (pre-launch gate):** commercial redistribution of exchange data
  may require BSE/NSE agreements. Get a legal opinion; licensed vendor feeds
  are the fallback. See PRD Section 9.
- **SEBI positioning:** factual, cited, event-anchored sentiment with visible
  basis; never aggregated into stock-level ratings. Disclaimer everywhere.
- **Calibration before badges ship:** hand-label ~300 filings across families;
  suppress badges for any family under ~85% model-human agreement (expect
  mna and capital to need iteration).

## Status

| Piece | State |
|---|---|
| PRD, source matrix, taxonomy, question bank, prompts, UI design | ✅ docs complete |
| BSE poller (all categories/subcategories, Nifty 500) | ✅ code, live-verified endpoints |
| Doc-type classifier + backfill + AR feed | ✅ code, tested (AR endpoint needs one Network-tab check) |
| Parse/chunk/index + hybrid search | ✅ code, tested end-to-end |
| Embedding: drain worker + model bake-off | ✅ code, tested offline |
| Sentiment: 12-family analyzer + tone engine | ✅ code, tested; needs 300-label calibration |
| Answer layer (router + answerer) | 📝 prompts done; service wiring pending |
| Chat/feed frontend | 🎨 design done; build pending |
| XBRL results engine, shareholding parser, lifecycle linker | 🔜 backlog |

## Roadmap (from the PRD)

- **Phase 1 (wks 1–3):** poller + live feed, rule-based categories — no AI
- **Phase 2 (wks 3–6):** LLM summaries + sentiment badges + MATERIAL sort
- **Phase 3 (wks 6–12):** RAG Q&A with citations (Nifty 500, 8-quarter
  backfill), watchlists, alerts, Pro tier
- **Post-launch:** universe expansion, annual reports, guidance tracking,
  policy/tariff monitoring, APPROVALS / PLEDGE / DISTRESS chips

---

*Nivesh Copilot cites filed documents only. It does not provide investment
advice, price targets, or predictions.*
