"""Deterministic first-pass classifier. Works without any LLM: the source class, the exchange category and keyword
dictionaries (English and a small Hindi set) give event_type, subtype, direction, a materiality prior, named
authorities and stated quantities. The LLM pass, when funded, may refine within bounds; it never replaces this."""
from __future__ import annotations

import re

AUTHORITIES = {
    "RBI": ["reserve bank of india", r"\brbi\b"], "SEBI": ["securities and exchange board", r"\bsebi\b"], "NHAI": ["national highways authority", r"\bnhai\b"],
    "MoRTH": [r"\bmorth\b", "ministry of road transport"], "CCI": ["competition commission", r"\bcci\b"], "CDSCO": [r"\bcdsco\b", "drugs controller"],
    "USFDA": [r"\busfda\b", r"\bus fda\b", r"\bfda\b", "food and drug administration"], "GLEIF": [r"\bgleif\b", "global legal entity identifier"],
    "MoD": ["ministry of defence", r"\bdac\b"], "NCLT": [r"\bnclt\b"], "IBBI": [r"\bibbi\b"], "DGFT": [r"\bdgft\b"], "MCA": ["ministry of corporate affairs"],
    "Supreme Court": ["supreme court"], "High Court": ["high court"], "GST": [r"\bgst\b"], "Income Tax": ["income tax"], "MNRE": [r"\bmnre\b", "new and renewable energy"],
}
# (event_type, subtype, direction, materiality prior, patterns)
RULES = [
    ("regulatory_decision", "debarment", "negative", 90, [r"\bdebar", r"\bblacklist", r"bidding restriction", r"barred from"]),
    ("regulatory_decision", "ban", "negative", 85, [r"\bban(?:ned|s)?\b", r"prohibit(?:ed|ion)", r"restrain(?:ed|s)?\b"]),
    ("regulatory_decision", "rejection", "negative", 80, [r"reject(?:ed|s|ion)", r"declin(?:ed|es)", r"not approved", r"refus(?:ed|al)"]),
    ("regulatory_decision", "penalty", "negative", 60, [r"\bpenalt", r"\bfine of\b", r"monetary penalty", r"show[- ]cause", r"adjudicat"]),
    ("regulatory_decision", "licence_cancellation", "negative", 85, [r"cancel(?:led|lation) of (?:the )?(?:licen[cs]e|registration|certificate)", r"licen[cs]e (?:cancel|suspend|revok)", r"withdraw(?:al|n) of (?:the )?(?:licen[cs]e|registration)"]),
    ("regulatory_decision", "approval", "positive", 65, [r"\bapprov(?:al|ed|es)\b", r"\bgrant(?:ed|s)\b", r"\bauthori[sz]ed\b", r"in-principle", r"licen[cs]e (?:granted|received|obtained)", r"registration (?:granted|received)"]),
    ("regulatory_decision", "restriction", "negative", 70, [r"\brestrict(?:ion|ed)\b", r"embargo", r"cease and desist", r"directions? (?:issued|imposed)"]),
    ("operations", "warning_letter", "negative", 75, [r"warning letter"]),
    ("operations", "import_alert", "negative", 85, [r"import alert"]),
    ("operations", "inspection_observations", "negative", 50, [r"form 483", r"\b483\b", r"observations? (?:issued|received)", r"official action indicated", r"\boai\b"]),
    ("operations", "recall", "negative", 60, [r"\brecall(?:ed|s)?\b", r"clinical hold"]),
    ("operations", "product_approval", "positive", 60, [r"\banda\b", r"\bnda\b", r"tentative approval", r"final approval", r"\beir\b", r"establishment inspection report", r"\bvai\b", r"\bnai\b", r"marketing authori[sz]ation", r"\bdcgi\b approval"]),
    ("operations", "capacity", "positive", 45, [r"commission(?:ed|ing)", r"capacity (?:expansion|addition)", r"new plant", r"greenfield", r"brownfield"]),
    ("operations", "disruption", "negative", 60, [r"\bfire\b", r"explosion", r"accident", r"shut ?down", r"suspension of (?:operations|production)", r"strike\b", r"cyber ?attack", r"ransomware"]),
    ("order_win", "government", "positive", 55, [r"letter of award", r"\bloa\b", r"appointed date", r"concession agreement", r"work order", r"\bawarded\b", r"\bbagg?ed\b", r"emerged (?:as )?(?:l1|lowest bidder)", r"\bl1 bidder\b"]),
    ("order_win", "contract", "positive", 50, [r"\border(?:s)? (?:worth|of|valued|aggregating)", r"secures? (?:an? )?(?:order|contract)", r"receiv(?:ed|es) (?:an? )?(?:order|contract|purchase order)", r"contract (?:worth|of|valued)", r"\bmou\b signed", r"supply agreement"]),
    ("order_win", "cancellation", "negative", 65, [r"(?:order|contract) (?:cancel|terminat)", r"termination of (?:the )?(?:contract|agreement|concession)", r"foreclos"]),
    ("m_and_a", "acquisition", "positive", 55, [r"acqui(?:re|sition|red)", r"\bmerger\b", r"amalgamation", r"scheme of arrangement", r"demerger", r"stake (?:sale|purchase)", r"open offer", r"takeover"]),
    ("capital", "buyback", "positive", 45, [r"buy[- ]?back"]), ("capital", "bonus_split", "positive", 35, [r"bonus (?:issue|shares)", r"stock split", r"sub-?division"]),
    ("capital", "dividend", "positive", 20, [r"\bdividend\b"]), ("capital", "fund_raise", "mixed", 40, [r"\bqip\b", r"preferential (?:issue|allotment)", r"rights issue", r"fund ?rais", r"\bfpo\b", r"\bipo\b", r"\bncd\b"]),
    ("credit", "downgrade", "negative", 65, [r"downgrad", r"\bdefault(?:ed|s)?\b", r"negative outlook", r"rating watch with negative"]), ("credit", "upgrade", "positive", 55, [r"upgrad", r"positive outlook", r"reaffirm"]),
    ("credit", "insolvency", "negative", 80, [r"insolvency", r"\bcirp\b", r"resolution plan", r"liquidation", r"\bibc\b", r"admitted (?:by|under) nclt"]),
    ("legal", "litigation", "negative", 45, [r"litigation", r"arbitration", r"petition", r"lawsuit", r"demand notice", r"\bsuit\b", r"tax demand", r"attach(?:ed|ment) of (?:property|assets|bank)"]),
    ("management", "exit", "negative", 40, [r"resign(?:ation|ed|s)", r"cessation", r"steps? down", r"\barrest", r"\bfraud\b", r"embezzl"]),
    ("management", "appointment", "neutral", 20, [r"appoint(?:ment|ed|s)\b", r"re-?appoint"]),
    ("results", "quarterly", "mixed", 60, [r"financial results", r"unaudited (?:financial )?results", r"audited (?:financial )?results", r"outcome of board meeting.*results", r"results for the quarter"]),
    ("institution", "appointment", "positive", 55, [r"validation agent", r"accredit(?:ed|ation)", r"empanel(?:led|ment)", r"appointed as (?:an? )?(?:agent|partner|distributor|authori[sz]ed)", r"recogni[sz]ed as", r"selected as"]),
    ("regulatory_policy", "policy", "neutral", 40, [r"master direction", r"circular", r"notification", r"amendment", r"guidelines", r"\bpli\b", r"scheme", r"policy", r"duty (?:on|for)", r"safeguard duty", r"anti-?dumping", r"tender", r"निविदा", r"योजना", r"अधिसूचना", r"नीति"]),
    ("routine", "routine", "neutral", 5, [r"trading window", r"investor meet", r"con\.? ?call", r"analyst", r"newspaper publication", r"scrutini[sz]er", r"\bagm\b", r"annual general meeting", r"\begm\b", r"postal ballot", r"book closure", r"record date", r"esop", r"esos", r"reg(?:ulation)?\.? ?74", r"certificate under", r"compliance certificate", r"loss of share certificate", r"shareholders meeting", r"e-?voting"]),
]
ROUTINE_CATEGORIES = {"Trading Window", "Analysts/Institutional Investor Meet/Con. Call Updates", "Shareholders meeting", "Copy of Newspaper Publication", "ESOP/ESOS/ESPS",
                      "Certificate under SEBI (Depositories and Participants) Regulations", "Loss of share certificates", "Reply to Clarification- Financial results"}
CATEGORY_HINTS = {"Action(s) taken or orders passed": ("regulatory_decision", "action_taken", "negative", 60), "Press Release": ("institution", "press_release", "neutral", 30),
                  "Credit Rating": ("credit", "rating", "neutral", 45), "Resignation of Director/KMP/SMP": ("management", "exit", "negative", 35), "Resignation": ("management", "exit", "negative", 35),
                  "Change in Management": ("management", "change", "neutral", 30), "Appointment": ("management", "appointment", "neutral", 20), "Outcome of Board Meeting": ("results", "board_outcome", "mixed", 45),
                  "Acquisition": ("m_and_a", "acquisition", "positive", 55), "Bagging/Receiving of orders/contracts": ("order_win", "contract", "positive", 55)}
_DEVANAGARI = re.compile(r"[\u0900-\u097F]")
_MONEY = re.compile(r"(?:rs\.?|inr|₹)\s*([\d,]+(?:\.\d+)?)\s*(crore|cr\b|lakh|million|mn|billion|bn)", re.I)


def _whole_word(low: str, m: "re.Match") -> str:
    """Extend a prefix match (\\bdebar) to the full word(s) it sits in, so the report reads 'debarment' not 'debar'."""
    start = m.start()
    while start > 0 and (low[start - 1].isalnum() or low[start - 1] in "-'"):
        start -= 1
    end = max(m.end(), start)
    while end < len(low) and (low[end].isalnum() or low[end] in "-'"):
        end += 1
    return low[start:end]


def _text(e: dict) -> str:
    return " ".join(x for x in (e.get("title"), e.get("summary"), e.get("doc_text")) if x)


def _quantities(text: str) -> dict:
    q = {}
    for amount, unit in _MONEY.findall(text):
        v = float(amount.replace(",", "")); u = unit.lower()
        cr = v if u.startswith("cr") else v / 100 if u.startswith("lakh") else v * 0.1 if u in ("million", "mn") else v * 100 if u in ("billion", "bn") else v
        q.setdefault("order_value_cr", cr); q.setdefault("amounts_cr", []).append(round(cr, 2))
    return q


def classify(e: dict) -> dict:
    text = _text(e); low = text.lower()
    lang = "hi" if len(_DEVANAGARI.findall(text)) > max(10, 0.3 * len(text)) else "en"
    named = [name for name, pats in AUTHORITIES.items() if any(re.search(p, low) for p in pats)]
    cat = e.get("category") or ""
    if cat in ROUTINE_CATEGORIES:
        return {"event_type": "routine", "event_subtype": "routine", "direction": "neutral", "materiality": 5, "confidence": 0.9, "matched_terms": [f"category:{cat}"],
                "named_authorities": named, "quantities": {}, "raw_language": lang, "classifier": "rules-v1"}
    best = None
    for etype, sub, direction, prior, pats in RULES:
        terms = [_whole_word(low, m) for p in pats if (m := re.search(p, low))]   # the words actually found, not the pattern
        if terms and (best is None or prior > best[3]):
            best = (etype, sub, direction, prior, terms)
    if best is None and cat in CATEGORY_HINTS:
        etype, sub, direction, prior = CATEGORY_HINTS[cat]; best = (etype, sub, direction, prior, [f"category:{cat}"])
    if best is None:
        return {"event_type": "unclassified", "event_subtype": None, "direction": "neutral", "materiality": 15, "confidence": 0.3, "matched_terms": [],
                "named_authorities": named, "quantities": _quantities(text), "raw_language": lang, "classifier": "rules-v1"}
    etype, sub, direction, prior, terms = best
    materiality = prior
    if etype in ("regulatory_decision", "operations", "order_win", "credit") and named:
        materiality = min(100, materiality + 5)                 # a named authority is a stronger signal than a bare word
    if etype == "order_win" and not named and sub == "government":
        sub = "contract"
    quantities = _quantities(text)
    conf = 0.6 + 0.1 * min(3, len(terms)) + (0.1 if named else 0.0)
    if e.get("doc_text"):
        conf = min(0.95, conf + 0.05)
    return {"event_type": etype, "event_subtype": sub, "direction": direction, "materiality": int(materiality), "confidence": round(min(conf, 0.95), 2),
            "matched_terms": [t.strip()[:32] for t in terms][:6], "named_authorities": named, "quantities": quantities,
            "raw_language": lang, "classifier": "rules-v1"}
