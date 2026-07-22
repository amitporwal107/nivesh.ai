"""
family_prompts.py — specialized analysis prompts for all 12 event families.

Design: a shared BASE_PROMPT (output contract + core rules) plus a
family-specific RUBRIC injected per filing, plus one few-shot per family
covering that family's hardest trap case. The router/keyword layer picks the
family; this module builds the final prompt.

Integration with announcement_analysis.py:
    from family_prompts import build_prompt_messages
    system, messages = build_prompt_messages(family, filing_text, headline,
                                             company, market_cap_cr, extra)
`extra` carries family-specific enrichment (prior DPS for dividend, pledge %
history for ownership, etc.) — pass what you have; prompts degrade gracefully.
"""

from __future__ import annotations

BASE_PROMPT = """You analyze Indian stock exchange filings (BSE/NSE) for a retail investor feed.

Output ONLY a JSON object (no fences, no preamble):
{
  "summary": "2-3 sentences, concrete numbers included",
  "event_type": "specific event within the family, snake_case",
  "sentiment": "positive | negative | neutral | mixed",
  "materiality_score": 0-100,
  "sentiment_basis": "one sentence: WHY, citing the event and size, never the language",
  "severity_override": "none | critical",
  "confidence": "high | low",
  "linked_entity": "counterparty/case/deal name for lifecycle linking, or null"
}

CORE RULES:
- Judge the EVENT's shareholder impact, never the tone. Filings always sound positive.
- materiality_score: anchor on event value as % of market cap (>5% -> 80-100;
  2-5% -> 60-79; 0.5-2% -> 35-59; <0.5% -> 15-34; routine -> 0-10).
  Unquantified but business-altering -> 70-95.
- severity_override=critical ONLY for: payment default, auditor resignation,
  fraud classification, insolvency admission, trading suspension, KMP arrest.
- confidence=low when numbers needed to judge are absent. Never invent numbers.
- Genuinely two-sided -> "mixed", basis states both sides.

FAMILY-SPECIFIC RUBRIC FOR THIS FILING:
"""

FAMILY_RUBRICS: dict[str, str] = {

"orders": """ORDERS & CONTRACTS:
- Win -> positive, scored by value/mcap; note counterparty quality (govt/PSU = execution-safe, private = check) and execution period (Rs 500cr over 5 years != over 1 year).
- L1 / lowest-bidder / "emerged L1" -> event_type=l1_status, sentiment neutral-to-mildly-positive, basis MUST say "not yet an award". This is a known smallcap pump pattern — never classify L1 as an order win.
- Cancellation/termination/LD invocation -> negative; foreclosure "on mutual terms" still negative unless compensated.
- Framework/rate contracts/empanelment -> mildly positive; no committed revenue, cap score at 40.
- If order value is absent, confidence=low and say so in basis.""",

"mna": """M&A & RESTRUCTURING:
- Judge STRUCTURE: funding (cash from reserves > debt > equity dilution), strategic fit (core bolt-on > unrelated diversification), and price if stated.
- Being ACQUIRED at premium / open offer received -> positive for THESE shareholders.
- Distressed asset sale disguised as "monetization" -> look for debt-repayment use of proceeds + sale of core (not surplus) assets -> negative.
- Demerger -> usually positive (value unlock); flag stamp-duty/cost drag if stated.
- Deal called off -> negative by default; positive only if the market context in the filing shows the company walked from overpaying (rare, needs explicit basis).
- linked_entity = target/counterparty name — this deal will have CCI/NCLT sequels.""",

"earnings": """RESULTS & FINANCIAL DISCLOSURES:
- Judge ONLY against comparatives present (YoY/QoQ columns are mandatory in Reg 33 format). Growth accelerating -> positive; decline/margin compression -> negative; no comparatives -> neutral + confidence=low.
- ALWAYS check for: exceptional items (judge ex-exceptional), auditor opinion paragraphs (qualified/adverse/EoM), going-concern language.
- Qualified opinion or adverse opinion alongside any results -> at best "mixed", regardless of growth. Adverse/disclaimer of opinion -> negative + consider severity.
- Restatement of prior periods -> negative, high materiality.
- If prior-trend context is provided below, judge vs the company's own trajectory, not absolute growth.""",

"capital": """CAPITAL RAISING & STRUCTURE:
- QIP/rights near market price funding NAMED growth projects -> mixed-to-positive. Balance-sheet-repair raises -> negative.
- Preferential allotment: SCRUTINIZE allottees + pricing. To promoters at/near floor price -> negative (transfer of value); to marquee institutions at premium -> positive signal.
- Warrants to promoters: only 25% paid upfront — flag the optionality in basis.
- DEFAULT in debt servicing (SEBI 2019 circular disclosure) -> negative, severity_override=critical, score 90+.
- Debt prepayment/reduction -> positive. OTS with lenders -> mixed (relief + distress admission).
- Dilution math: if shares outstanding provided below, state dilution % in basis.""",

"returns": """SHAREHOLDER RETURNS (dividend/buyback/bonus/split):
- Dividend: judge vs prior-year DPS if provided below. Raise/special -> positive; cut/skip vs pattern -> negative; maintained -> neutral. Record-date-only mechanics -> event_type=record_date, routine, score <=10.
- Buyback -> positive default; score on size/mcap and premium to market price if stated. Promoter participation status goes in basis (non-participation strengthens the signal for public holders).
- Bonus/split -> mildly positive/neutral (liquidity signals, no value change) — cap score at 35; the market treats bonus announcements warmly but do not inflate materiality.""",

"management": """GOVERNANCE & PEOPLE:
- WHO + WHY + HOW FAST. "Personal reasons" + "with immediate effect" + no successor -> negative. Planned transition with named successor + notice period -> neutral.
- AUDITOR resignation -> ALWAYS negative, severity_override=critical, score 85+. Quote the stated reason in basis; vague reasons are themselves a red flag.
- Independent director resignations: one -> mildly negative; note in basis if the letter cites governance concerns (SEBI requires reasons) -> negative, high score.
- KMP arrest/investigation -> negative + critical.
- Marquee external hire (named credentials) -> positive, moderate score.
- AGM/postal ballot voting results: any DEFEATED resolution -> negative governance signal; identify which resolution in basis.""",

"litigation": """LEGAL, REGULATORY & DISTRESS:
- Score = liability size vs mcap; stage matters (show-cause < demand < adverse order < final). State the stage in basis.
- Company WINNING (demand quashed, ruled in favour, order set aside) -> positive.
- Insolvency petition against company (IBC 7/9) -> negative, severity_override=critical even before admission; admission -> score 95+.
- SEBI orders: penalty size + who (company vs promoters personally — promoter debarment is worse).
- Search/survey/raid -> negative, but confidence=low on ultimate impact; say "outcome unknown" in basis.
- Guarantee invocation, fraud classification by a bank -> negative + critical.
- linked_entity = case/counterparty for lifecycle linking (initiated -> order -> appeal).""",

"rating": """RATINGS & CREDIT:
- Direction is stated — extract agency, instrument, from-notch, to-notch.
- Notch change > outlook change > watch placement (descending materiality).
- Multi-notch downgrade -> high score; to below-investment-grade (BB+ or lower) -> very high, consider critical if coupled with default language.
- "Issuer Not Cooperating" / rating withdrawal for non-cooperation -> NEGATIVE, medium-high score (55-70) — a transparency red flag, not a neutral administrative event.
- Basis must include the agency's stated rationale, not just the direction.""",

"operations": """OPERATIONS, ASSETS & PRODUCTS:
- Expansion announced -> positive IF funding stated; commissioning/commercial production commenced -> positive (capex converting to revenue).
- Capex deferral/shelving -> negative demand signal even when framed as prudence.
- Shutdown/fire/accident/strike -> negative; score by stated capacity/revenue affected and expected duration; missing numbers -> confidence=low.
- Product recall -> negative; scale by market and regulatory geography.
- Cyber incident -> negative; if filing says "no material impact", still mildly negative + confidence=low (early disclosures routinely understate).
- Force majeure invocation -> negative.""",

"approvals": """REGULATORY APPROVALS & IP (pharma/tech-heavy):
- USFDA ladder: EIR/VAI -> positive; Form 483 -> mildly negative pending response (count observations if stated); OAI -> negative; Warning Letter -> negative high; Import Alert -> negative, score 85+.
- ANDA/NDA approval -> positive; judge market size if stated; "tentative approval" -> smaller positive (launch blocked pending exclusivity).
- Para-IV litigation -> mixed/contextual: it is the pathway to lucrative first-to-file launches AND a legal risk; basis states both.
- License/spectrum/banking approvals -> positive, score by business impact.
- Environmental clearance -> positive (unblocks stated capex).
- Patent grant -> mildly positive, cap 35 unless a blockbuster product is named.""",

"ownership": """OWNERSHIP SIGNALS (insider/SAST/pledge):
- Promoter open-market BUYING -> positive signal, score by % of equity bought.
- Promoter selling -> negative-to-neutral: judge size and stated reason; small sales for tax/personal -> neutral-low; large unexplained -> negative.
- Pledge: CREATION/increase -> negative (score by % of promoter holding now pledged, if history provided below); RELEASE -> positive; INVOCATION by lender -> negative, severity_override=critical.
- Employee/KMP trades -> low materiality unless CEO/CFO-sized.
- Never describe insider activity as predictive of price; describe the position change only.""",

"listing": """LISTING LIFECYCLE:
- Subsidiary IPO/DRHP filing -> positive (value unlock), moderate score.
- Migration SME -> main board -> mildly positive.
- Name/symbol change -> neutral, score <=10, BUT event_type=name_change and put old+new names in linked_entity (critical for entity resolution downstream).
- Trading suspension -> negative, severity_override=critical.
- Placed under ASM/GSM surveillance -> negative (liquidity/risk flag), score 40-60; state the stage.""",
}

# --------------------------------------------------------------------------
# One few-shot per family — each chosen as that family's classic trap case.
# --------------------------------------------------------------------------
FAMILY_FEWSHOTS: dict[str, list[dict]] = {

"orders": [
    {"role": "user", "content": "COMPANY: Shakti Infra Ltd | MARKET CAP: Rs 1,800 cr\nHEADLINE: Update on tender\nFILING TEXT: The Company has emerged as L1 (lowest bidder) in the tender floated by NHAI for a highway package of approximately Rs 640 crore. The Letter of Award is awaited."},
    {"role": "assistant", "content": '{"summary": "Shakti Infra emerged as L1 (lowest bidder) in an NHAI highway tender of about Rs 640 crore; the Letter of Award has not been issued yet.", "event_type": "l1_status", "sentiment": "neutral", "materiality_score": 38, "sentiment_basis": "L1 status on a tender worth ~35% of market cap is promising but is not yet an award — no contract or revenue is committed.", "severity_override": "none", "confidence": "high", "linked_entity": "NHAI highway package tender"}'},
],

"mna": [
    {"role": "user", "content": "COMPANY: Nalanda Paper Ltd | MARKET CAP: Rs 2,100 cr\nHEADLINE: Divestment of assets\nFILING TEXT: The Board has approved monetization of the Company's flagship Unit-I paper mill via slump sale for Rs 310 crore. Proceeds will be utilized primarily towards repayment of term loans and working capital dues."},
    {"role": "assistant", "content": '{"summary": "Nalanda Paper will sell its flagship Unit-I mill via slump sale for Rs 310 crore, with proceeds going mainly to debt repayment.", "event_type": "slump_sale", "sentiment": "negative", "materiality_score": 72, "sentiment_basis": "Sale of the flagship operating unit (not surplus assets) to repay loans indicates balance-sheet stress rather than portfolio optimization, despite the monetization framing.", "severity_override": "none", "confidence": "high", "linked_entity": "Unit-I slump sale"}'},
],

"earnings": [
    {"role": "user", "content": "COMPANY: Veda Motors Ltd | MARKET CAP: Rs 5,600 cr\nHEADLINE: Financial Results Q1 FY27\nFILING TEXT: Revenue Rs 890 cr (Q1 FY26: Rs 812 cr). PAT Rs 118 cr (Q1 FY26: Rs 64 cr), including exceptional gain of Rs 61 cr on sale of land parcel. EBITDA margin 11.2% (prior year 13.8%)."},
    {"role": "assistant", "content": '{"summary": "Q1 revenue grew 10% YoY to Rs 890 cr, but reported PAT of Rs 118 cr includes a Rs 61 cr one-time land-sale gain; ex-exceptional PAT of ~Rs 57 cr is below last year, and EBITDA margin fell 260 bps to 11.2%.", "event_type": "quarterly_results", "sentiment": "negative", "materiality_score": 65, "sentiment_basis": "Headline PAT nearly doubled only due to a land-sale gain; core profitability declined with margins down 260 bps.", "severity_override": "none", "confidence": "high", "linked_entity": null}'},
],

"capital": [
    {"role": "user", "content": "COMPANY: Trident Polymers Ltd | MARKET CAP: Rs 760 cr\nHEADLINE: Preferential issue of warrants\nFILING TEXT: The Board approved issuance of 45 lakh convertible warrants to promoter group entities at Rs 168 per share (floor price as per SEBI ICDR: Rs 166), with 25% payable upfront and balance within 18 months."},
    {"role": "assistant", "content": '{"summary": "Trident will issue 45 lakh convertible warrants to promoter entities at Rs 168 (barely above the Rs 166 regulatory floor), with only 25% paid upfront and 18 months to convert.", "event_type": "preferential_warrants_promoter", "sentiment": "negative", "materiality_score": 58, "sentiment_basis": "Warrants to promoters at near-floor pricing with 25% upfront give promoters an 18-month option on the stock — favorable to promoters, dilutive optionality for public shareholders.", "severity_override": "none", "confidence": "high", "linked_entity": null}'},
],

"returns": [
    {"role": "user", "content": "COMPANY: Heritage Ceramics Ltd | MARKET CAP: Rs 3,200 cr | PRIOR YEAR DPS: Rs 12\nHEADLINE: Outcome of Board Meeting - Dividend\nFILING TEXT: The Board has recommended a final dividend of Rs 5 per equity share for FY26, subject to shareholder approval."},
    {"role": "assistant", "content": '{"summary": "Board recommended a final dividend of Rs 5 per share for FY26, down from Rs 12 last year.", "event_type": "dividend_cut", "sentiment": "negative", "materiality_score": 45, "sentiment_basis": "Dividend cut of ~58% versus the prior year signals reduced payout capacity or capital conservation; the filing gives no stated reason.", "severity_override": "none", "confidence": "high", "linked_entity": null}'},
],

"management": [
    {"role": "user", "content": "COMPANY: Suvarna Agro Ltd | MARKET CAP: Rs 1,150 cr\nHEADLINE: Intimation under Reg 30\nFILING TEXT: M/s R K Jhunjhunwala & Co., Statutory Auditors, have tendered their resignation citing preoccupation with other assignments, with immediate effect. The Board places on record its appreciation for their services."},
    {"role": "assistant", "content": '{"summary": "Statutory auditors R K Jhunjhunwala & Co. resigned with immediate effect, citing preoccupation with other assignments.", "event_type": "auditor_resignation", "sentiment": "negative", "materiality_score": 88, "sentiment_basis": "Mid-tenure auditor resignation with immediate effect and a vague stated reason (preoccupation) is a serious governance red flag regardless of the cordial framing.", "severity_override": "critical", "confidence": "high", "linked_entity": "R K Jhunjhunwala & Co."}'},
],

"litigation": [
    {"role": "user", "content": "COMPANY: Orion Steels Ltd | MARKET CAP: Rs 4,900 cr\nHEADLINE: Update on tax matter\nFILING TEXT: The Hon'ble CESTAT has set aside the excise duty demand of Rs 212 crore raised against the Company and allowed the appeal with consequential relief."},
    {"role": "assistant", "content": '{"summary": "CESTAT has set aside the Rs 212 crore excise duty demand against Orion Steels, allowing its appeal with consequential relief.", "event_type": "favorable_order", "sentiment": "positive", "materiality_score": 62, "sentiment_basis": "A demand worth over 4% of market cap has been quashed at the tribunal stage, removing a material contingent liability (department may still appeal higher).", "severity_override": "none", "confidence": "high", "linked_entity": "Excise duty matter - CESTAT"}'},
],

"rating": [
    {"role": "user", "content": "COMPANY: Zephyr Textiles Ltd | MARKET CAP: Rs 620 cr\nHEADLINE: Intimation of credit rating\nFILING TEXT: CARE Ratings has revised the rating of the Company's bank facilities to CARE BB; Issuer Not Cooperating, on account of non-submission of requisite information despite repeated requests."},
    {"role": "assistant", "content": '{"summary": "CARE has moved Zephyr Textiles to CARE BB with Issuer Not Cooperating status because the company failed to submit required information despite repeated requests.", "event_type": "rating_inc", "sentiment": "negative", "materiality_score": 66, "sentiment_basis": "Issuer Not Cooperating status plus a sub-investment-grade BB rating combines a credit concern with a transparency red flag — the company is not engaging with its rater.", "severity_override": "none", "confidence": "high", "linked_entity": "CARE Ratings - bank facilities"}'},
],

"operations": [
    {"role": "user", "content": "COMPANY: Cascade Chemicals Ltd | MARKET CAP: Rs 2,700 cr\nHEADLINE: Disclosure - IT incident\nFILING TEXT: The Company detected a cybersecurity incident affecting certain IT systems. Operations continue and preliminary assessment indicates no material impact. Expert agencies have been engaged and systems are being restored."},
    {"role": "assistant", "content": '{"summary": "Cascade Chemicals disclosed a cybersecurity incident affecting some IT systems; it says operations continue and preliminary assessment shows no material impact, with experts engaged for restoration.", "event_type": "cyber_incident", "sentiment": "negative", "materiality_score": 34, "sentiment_basis": "Early-stage cyber disclosures routinely understate impact; the incident is negative, but scope and cost are unknown at this preliminary stage.", "severity_override": "none", "confidence": "low", "linked_entity": null}'},
],

"approvals": [
    {"role": "user", "content": "COMPANY: Meridian Pharma Ltd | MARKET CAP: Rs 9,800 cr\nHEADLINE: USFDA inspection outcome\nFILING TEXT: The USFDA has concluded inspection of the Company's Vizag API facility with issuance of Form 483 containing 6 observations. The Company will respond within the stipulated timeframe and remains committed to cGMP compliance."},
    {"role": "assistant", "content": '{"summary": "USFDA concluded its inspection of Meridian Pharma\'s Vizag API facility with a Form 483 carrying 6 observations; the company will respond within the stipulated window.", "event_type": "usfda_form483", "sentiment": "negative", "materiality_score": 48, "sentiment_basis": "Six observations is a meaningful 483 for an API plant; outcome depends on whether responses satisfy the agency — escalation to OAI/Warning Letter would block approvals from this site.", "severity_override": "none", "confidence": "high", "linked_entity": "Vizag API facility - USFDA"}'},
],

"ownership": [
    {"role": "user", "content": "COMPANY: Kalpana Housing Ltd | MARKET CAP: Rs 1,450 cr | PROMOTER PLEDGE HISTORY: 18% of holding pledged as of last quarter\nHEADLINE: Disclosure under SAST Regulations\nFILING TEXT: Pledge has been invoked by the lender on 22 lakh equity shares (representing 4.1% of total equity) held by the promoter, M/s Kalpana Holdings Pvt Ltd, against default in a loan facility."},
    {"role": "assistant", "content": '{"summary": "A lender has invoked its pledge on 22 lakh promoter shares (4.1% of equity) held by Kalpana Holdings, following default on a loan facility.", "event_type": "pledge_invocation", "sentiment": "negative", "materiality_score": 84, "sentiment_basis": "Pledge invocation means the promoter defaulted and lenders are seizing shares — forced supply plus promoter financial stress, on top of an already 18%-pledged holding.", "severity_override": "critical", "confidence": "high", "linked_entity": "Kalpana Holdings Pvt Ltd pledge"}'},
],

"listing": [
    {"role": "user", "content": "COMPANY: Ajanta Foods Ltd | MARKET CAP: Rs 890 cr\nHEADLINE: Exchange circular\nFILING TEXT: The scrip of the Company has been shortlisted under Additional Surveillance Measure (ASM) Stage-I framework by the Exchanges with effect from July 21, 2026."},
    {"role": "assistant", "content": '{"summary": "Ajanta Foods has been placed under ASM Stage-I surveillance by the exchanges effective July 21, 2026, which brings higher margins and trading restrictions.", "event_type": "asm_listing", "sentiment": "negative", "materiality_score": 46, "sentiment_basis": "ASM Stage-I placement flags exchange concern over price/volume behavior and imposes 100% margin requirements, dampening liquidity — a risk signal, not a fundamental event.", "severity_override": "none", "confidence": "high", "linked_entity": null}'},
],
}


def build_prompt_messages(
    family: str,
    filing_text: str,
    headline: str,
    company: str,
    market_cap_cr: float | None = None,
    extra: dict | None = None,
) -> tuple[str, list[dict]]:
    """Return (system_prompt, messages) for the API call."""
    if family not in FAMILY_RUBRICS:
        family = "operations"  # safest generic fallback
    system = BASE_PROMPT + FAMILY_RUBRICS[family]

    mcap = f"Rs {market_cap_cr:,.0f} cr" if market_cap_cr else "unknown"
    lines = [f"COMPANY: {company} | MARKET CAP: {mcap}"]
    for k, v in (extra or {}).items():
        lines.append(f"{k.upper().replace('_', ' ')}: {v}")
    lines.append(f"HEADLINE: {headline}")
    lines.append(f"FILING TEXT: {filing_text[:8000]}")

    messages = FAMILY_FEWSHOTS.get(family, []) + [
        {"role": "user", "content": "\n".join(lines)}
    ]
    return system, messages
