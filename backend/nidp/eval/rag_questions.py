"""The 32-question evaluation set (source: /app/data/32_set_questions).

Structured + versioned here so the eval is self-contained and reproducible.
Each entry carries the metadata the harness checks against:

  id            stable identifier
  category      human grouping (matches the source file's sections)
  route         expected router intent (single_company_rag | thematic_rag |
                event_lookup | numeric | policy | verification)
  question      the verbatim question text
  tickers       tickers extracted from the question ($SYMBOL); [] if none
  should_cite   True when a grounded answer must carry [n] citations. Numeric
                (XBRL) answers are stated plainly without citations, so False.
  is_thematic   True for cross-company discovery (retrieval runs without a
                ticker filter and groups findings per company)
  placeholder   True when the ticker is a generic placeholder ($XYZ/$ABC) with
                no real data — the correct answer is "no filing found", which is
                itself a valid grounded response the harness must accept.
  must_include  Key facts/phrases the gold answer contains (from the PRD
                "Appendix B — sample answers"). Populate to enable content
                matching; empty [] means structural checks only.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import List


@dataclass(frozen=True)
class EvalQuestion:
    id: str
    category: str
    route: str
    question: str
    tickers: List[str] = field(default_factory=list)
    should_cite: bool = True
    is_thematic: bool = False
    placeholder: bool = False
    # Populated from the sample answers ("Appendix B") — see match_sample_answers().
    must_include: List[str] = field(default_factory=list)


QUESTIONS: List[EvalQuestion] = [
    # ── Single-company RAG (concall / presentation content) ──────────
    EvalQuestion("SC-1", "single_company", "single_company_rag",
                 "What did $LT say about its order book and pipeline in the latest earnings call?", ["LT"]),
    EvalQuestion("SC-2", "single_company", "single_company_rag",
                 "What is $RRKABEL's capex plan for FY27?", ["RRKABEL"]),
    EvalQuestion("SC-3", "single_company", "single_company_rag",
                 "What guidance did management give for margins next quarter?", []),
    EvalQuestion("SC-4", "single_company", "single_company_rag",
                 "Why did $CUMMINSIND's revenue drop this quarter — what did management attribute it to?", ["CUMMINSIND"]),
    EvalQuestion("SC-5", "single_company", "single_company_rag",
                 "What are the key risks management highlighted in the latest investor presentation?", []),
    EvalQuestion("SC-6", "single_company", "single_company_rag",
                 "Summarize $ADANIENT's latest concall in 5 points.", ["ADANIENT"]),
    EvalQuestion("SC-7", "single_company", "single_company_rag",
                 "What new products or capacity is $ABB adding this year?", ["ABB"]),
    EvalQuestion("SC-8", "single_company", "single_company_rag",
                 "Has $TATAMOTORS given any update on its EV plans?", ["TATAMOTORS"]),

    # ── Cross-company / thematic discovery ───────────────────────────
    EvalQuestion("TH-1", "thematic", "thematic_rag",
                 "Which companies are investing in data centers?", [], is_thematic=True),
    EvalQuestion("TH-2", "thematic", "thematic_rag",
                 "Which companies mentioned raw material cost pressure this quarter?", [], is_thematic=True),
    EvalQuestion("TH-3", "thematic", "thematic_rag",
                 "Which pharma companies talked about US FDA inspections recently?", [], is_thematic=True),
    EvalQuestion("TH-4", "thematic", "thematic_rag",
                 "Who are the beneficiaries of the railway capex push, according to their own filings?", [], is_thematic=True),
    EvalQuestion("TH-5", "thematic", "thematic_rag",
                 "Which companies announced capacity expansion in the last 6 months?", [], is_thematic=True),
    EvalQuestion("TH-6", "thematic", "thematic_rag",
                 "Which smallcaps won defence orders this quarter?", [], is_thematic=True),
    EvalQuestion("TH-7", "thematic", "thematic_rag",
                 "Which companies are talking about AI in their earnings calls?", [], is_thematic=True),

    # ── Event lookups (announcements feed) ───────────────────────────
    EvalQuestion("EV-1", "event", "event_lookup",
                 "What orders did $BEL win this month?", ["BEL"]),
    EvalQuestion("EV-2", "event", "event_lookup",
                 "Any acquisitions announced by $RELIANCE recently?", ["RELIANCE"]),
    EvalQuestion("EV-3", "event", "event_lookup",
                 "Show me all fundraising announcements this week.", []),
    EvalQuestion("EV-4", "event", "event_lookup",
                 "Did $ZOMATO file anything today?", ["ZOMATO"]),
    EvalQuestion("EV-5", "event", "event_lookup",
                 "What was announced in $HDFC's board meeting yesterday?", ["HDFC"]),

    # ── Results and numbers (XBRL + filings) — stated plainly, no [n] ─
    EvalQuestion("NM-1", "numeric", "numeric",
                 "How did $INFY's Q1 results compare to last year?", ["INFY"], should_cite=False),
    EvalQuestion("NM-2", "numeric", "numeric",
                 "Which Nifty 500 companies grew profit more than 30% YoY this quarter?", [], should_cite=False),
    EvalQuestion("NM-3", "numeric", "numeric",
                 "When is $TCS's next results date?", ["TCS"], should_cite=False),
    EvalQuestion("NM-4", "numeric", "numeric",
                 "What one-offs affected $ITC's numbers this quarter?", ["ITC"], should_cite=False),

    # ── Policy, tariff, and legal (Tier 3 sources) ───────────────────
    EvalQuestion("PL-1", "policy", "policy",
                 "How does the latest GST rate change affect auto component makers?", []),
    EvalQuestion("PL-2", "policy", "policy",
                 "Which companies are affected by the new anti-dumping duty on steel imports?", []),
    EvalQuestion("PL-3", "policy", "verification",
                 "Any recent SEBI actions against $XYZ or its promoters?", ["XYZ"], placeholder=True),
    EvalQuestion("PL-4", "policy", "verification",
                 "Is there any insolvency case filed against $ABC?", ["ABC"], placeholder=True),
    EvalQuestion("PL-5", "policy", "policy",
                 "What did the Union Budget change for renewable energy companies?", []),
    EvalQuestion("PL-6", "policy", "policy",
                 "How do the new US tariffs affect Indian pharma exporters?", []),

    # ── Verification (trust-building) ────────────────────────────────
    EvalQuestion("VF-1", "verification", "verification",
                 "Is the rumor about $XYZ winning a ₹5,000 crore order true — did they file anything?", ["XYZ"], placeholder=True),
    EvalQuestion("VF-2", "verification", "verification",
                 "Did $ABC actually announce a bonus issue, or is that fake news?", ["ABC"], placeholder=True),
]

assert len(QUESTIONS) == 32, f"expected 32 questions, got {len(QUESTIONS)}"
