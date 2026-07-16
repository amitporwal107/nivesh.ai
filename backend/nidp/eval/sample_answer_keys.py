"""Benchmark keys derived from the PRD "Appendix B — sample answers"
(source: /app/data/nivesh-copilot-sample-answers.md).

Appendix B's figures/dates are ILLUSTRATIVE PLACEHOLDERS ("₹X.X lakh crore",
"XX%"), so these are the STABLE, matchable expectations a correct answer must
contain — topic anchors, ticker→name entity resolutions, and defining
behaviours — not numbers. Substring-matched (case-insensitive) by
rag_eval.answer_covers.

Empty lists ([]) mark questions whose defining behaviour isn't a substring
(e.g. "ask for the missing ticker") — those are covered by the structural
checks (coverage / refusal / no-advice) instead. Refine as the live corpus and
answers settle.

Strongest checks here are the entity resolutions the doc calls out explicitly:
  EV-4  $ZOMATO → "Eternal"   (renamed entity)
  EV-5  $HDFC   → "bank"      ($HDFC parent merged into HDFC Bank)
"""

SAMPLE_ANSWER_KEYS = {
    # A. Single-company deep dives
    "SC-1": ["order book"],       # order book + pipeline, management-attributed
    "SC-2": ["capex"],            # capex plan, presentation + transcript
    "SC-3": [],                   # no ticker → must ask which company (structural)
    "SC-4": ["management"],       # "why" → management's own attribution only
    "SC-5": [],                   # no ticker → must ask which company (structural)
    "SC-6": ["adani"],            # 5-point cited summary; names the company
    "SC-7": ["abb"],              # names ABB; fiscal-year (Jan–Dec) note
    "SC-8": ["tata"],             # names Tata Motors; EV updates

    # B. Cross-company / thematic (each company its own citation + coverage note)
    "TH-1": ["data cent"],        # matches data center / data centre
    "TH-2": ["cost"],             # raw material cost pressure
    "TH-3": ["fda"],              # US FDA inspections
    "TH-4": ["railway"],          # railway capex beneficiaries (disclosed exposure)
    "TH-5": ["capacity"],         # capacity expansion
    "TH-6": ["defence"],          # smallcap defence orders
    "TH-7": [],                   # "AI" is too short to substring safely

    # C. Event lookups (announcements feed)
    "EV-1": ["order"],            # BEL order wins
    "EV-2": ["acquisition"],      # RELIANCE acquisitions (empty case states window)
    "EV-3": ["fundrais"],         # fundraising (fundraise/fundraising)
    "EV-4": ["eternal"],          # entity resolution: Zomato → Eternal
    "EV-5": ["bank"],             # entity resolution: HDFC → HDFC Bank

    # D. Results and numbers (XBRL + filings)
    "NM-1": ["q1"],               # Q1 vs Q1 comparison
    "NM-2": ["profit"],           # profit-growth screen (results-season caveat)
    "NM-3": ["board"],            # results date = board-meeting intimation
    "NM-4": ["exceptional"],      # one-offs = exceptional items (notes to accounts)

    # E. Policy, tariff, legal (Tier 3, sector-inference badge)
    "PL-1": ["gst"],
    "PL-2": ["dumping"],          # anti-dumping duty
    "PL-3": ["sebi"],             # SEBI actions (placeholder ticker → neutral)
    "PL-4": ["insolvency"],       # IBC/NCLT
    "PL-5": ["budget"],
    "PL-6": ["tariff"],

    # F. Verification (binary filed / not-filed; Reg 30 24-hour rule)
    "VF-1": ["filing"],           # rumor order → filed or not
    "VF-2": ["bonus"],            # bonus issue → confirmed or no such filing
}
