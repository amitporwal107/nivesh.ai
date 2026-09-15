"""Deterministic classifier under a strict taxonomy (user, 2026-09-16). Exchange filings are read category-first;
keyword rules refine within the group the category implies, and may only move a filing into REGULATORY when a named
authority and an un-negated regulatory term appear. Negated terms ('is not debarred from holding the office') and the
names of regulations ('Prohibition of Insider Trading') never fire. Output: event_type (group), event_subtype,
direction, event_severity 0-100, confidence, named authorities, stated amounts, raw_language, classifier."""
from __future__ import annotations

import re

TAXONOMY = {
    "CORPORATE": ("director_change", "management_change", "resignation", "appointment", "promoter_transaction", "acquisition", "divestment", "restructuring", "disruption", "capacity", "product_launch", "update"),
    "REGULATORY": ("approval", "rejection", "forced_listing", "penalty", "ban", "debarment", "bidding_restriction", "suspension", "licence_cancelled", "licence_granted", "regulatory_order", "inspection_observations"),
    "CONTRACT": ("order_win", "order_loss", "loa", "contract_termination", "contract_extension"),
    "FINANCIAL": ("rating_upgrade", "rating_downgrade", "rating_watch", "debt_restructuring", "default", "insolvency"),
    "M&A": ("acquisition", "merger", "demerger", "takeover", "cci_approval", "stake_sale", "open_offer"),
    "GOVERNMENT": ("policy", "tender", "project", "subsidy", "tariff", "procurement", "circular"),
    "PHARMA": ("fda_approval", "fda_warning", "import_alert", "inspection", "product_approval", "recall", "clinical_hold"),
    "RESULTS": ("quarterly", "annual", "board_outcome"),
    "CAPITAL": ("buyback", "dividend", "bonus_split", "fund_raise", "delisting"),
    "INSTITUTION": ("appointment", "accreditation", "partnership", "press_release"),
    "LEGAL": ("litigation", "tax_demand", "arbitration"),
    "ROUTINE": ("routine",),
    "UNCLASSIFIED": ("unclassified",),
}
AUTHORITIES = {
    "RBI": ["reserve bank of india", r"\brbi\b"], "SEBI": ["securities and exchange board", r"\bsebi\b"], "NHAI": ["national highways authority", r"\bnhai\b"],
    "MoRTH": [r"\bmorth\b", "ministry of road transport"], "CCI": ["competition commission", r"\bcci\b"], "CDSCO": [r"\bcdsco\b", "drugs controller"],
    "USFDA": [r"\busfda\b", r"\bus fda\b", r"\bfda\b", "food and drug administration"], "GLEIF": [r"\bgleif\b", "global legal entity identifier"],
    "MoD": ["ministry of defence", r"\bdac\b"], "NCLT": [r"\bnclt\b"], "IBBI": [r"\bibbi\b"], "DGFT": [r"\bdgft\b"], "MCA": ["ministry of corporate affairs"],
    "Supreme Court": ["supreme court"], "High Court": ["high court"], "GST": [r"\bgst\b"], "Income Tax": ["income tax"], "MNRE": [r"\bmnre\b", "new and renewable energy"],
    "ICRA": [r"\bicra\b"], "CRISIL": [r"\bcrisil\b"], "CARE": [r"\bcare ratings\b", r"\bcare\b(?= (?:rating|reaffirm|assign|upgrade|downgrade))"],
}
# (group, subtype, direction, severity prior, patterns); the first matching rule of the highest prior wins
RULES = [
    ("REGULATORY", "debarment", "negative", 90, [r"\bdebar", r"\bblacklist", r"barred from"]),
    ("REGULATORY", "bidding_restriction", "negative", 85, [r"bidding restriction", r"not (?:be )?able to participate in any bid", r"restrict(?:ed|ion) from (?:bidding|participat)"]),
    ("REGULATORY", "ban", "negative", 85, [r"\bban(?:ned|s)?\b", r"\bprohibit(?:ed|s)\b", r"restrain(?:ed|s)?\b", r"cease and desist"]),
    ("REGULATORY", "forced_listing", "positive", 85, [r"reject.{0,90}(?:surrender|deregist|de-regist|avoid (?:a |market |public |stock[- ]market )?listing|exemption from listing)", r"(?:surrender|deregist).{0,90}reject"]),   # a holding company denied its exit from listing rules: positive for the companies that own it
    ("REGULATORY", "rejection", "negative", 80, [r"reject(?:ed|s|ion)", r"declin(?:ed|es)", r"not approved", r"refus(?:ed|al)"]),
    ("REGULATORY", "licence_cancelled", "negative", 85, [r"cancel(?:led|lation) of (?:the )?(?:licen[cs]e|registration|certificate)", r"licen[cs]e (?:cancel|suspend|revok)", r"withdraw(?:al|n) of (?:the )?(?:licen[cs]e|registration)"]),
    ("REGULATORY", "suspension", "negative", 75, [r"suspen(?:ded|sion) of (?:trading|licen[cs]e|registration|operations)"]),
    ("REGULATORY", "penalty", "negative", 55, [r"\bpenalt", r"\bfine of\b", r"monetary penalty", r"show[- ]cause", r"adjudicat"]),
    ("REGULATORY", "regulatory_order", "negative", 60, [r"directions? (?:issued|imposed)", r"order (?:passed|issued) (?:by|under)", r"\bembargo\b"]),
    ("REGULATORY", "licence_granted", "positive", 65, [r"licen[cs]e (?:granted|received|obtained)", r"registration (?:granted|received)", r"\bgrant of (?:the )?(?:licen[cs]e|registration|approval)"]),
    ("REGULATORY", "approval", "positive", 60, [r"\bapprov(?:al|ed|es)\b", r"\bgrant(?:ed|s)\b", r"\bauthori[sz]ed\b", r"in-principle", r"no objection certificate", r"\bnoc\b"]),
    ("PHARMA", "fda_warning", "negative", 75, [r"warning letter"]), ("PHARMA", "import_alert", "negative", 85, [r"import alert"]),
    ("PHARMA", "inspection", "negative", 50, [r"form 483", r"\b483\b", r"observations? (?:issued|received)", r"official action indicated", r"\boai\b"]),
    ("PHARMA", "recall", "negative", 60, [r"\brecall(?:ed|s)?\b"]), ("PHARMA", "clinical_hold", "negative", 60, [r"clinical hold"]),
    ("PHARMA", "fda_approval", "positive", 60, [r"\bus ?fda\b.{0,40}approv", r"approv.{0,40}\bus ?fda\b", r"\banda\b", r"\bnda\b", r"tentative approval", r"final approval", r"\beir\b", r"establishment inspection report", r"\bvai\b", r"\bnai\b"]),
    ("PHARMA", "product_approval", "positive", 50, [r"marketing authori[sz]ation", r"\bdcgi\b approval", r"\bcdsco\b.{0,40}approv"]),
    ("CONTRACT", "loa", "positive", 60, [r"letter of award", r"\bloa\b", r"appointed date", r"concession agreement", r"emerged (?:as )?(?:l1|lowest bidder)", r"\bl1 bidder\b"]),
    ("CONTRACT", "order_win", "positive", 55, [r"\border(?:s)? (?:worth|of|valued|aggregating)", r"secures? (?:an? )?(?:order|contract)", r"receiv(?:ed|es) (?:an? )?(?:order|contract|purchase order|work order)", r"contract (?:worth|of|valued)", r"\bbagg?ed\b", r"\bawarded\b", r"work order", r"supply agreement"]),
    ("CONTRACT", "contract_termination", "negative", 65, [r"(?:order|contract) (?:cancel|terminat)", r"termination of (?:the )?(?:contract|agreement|concession)", r"foreclos"]),
    ("CONTRACT", "contract_extension", "positive", 35, [r"(?:contract|agreement) (?:extended|extension|renewed|renewal)"]),
    ("M&A", "cci_approval", "positive", 70, [r"\bcci\b.{0,40}approv", r"competition commission.{0,40}approv", r"approv.{0,60}\bcci\b"]),
    ("M&A", "demerger", "mixed", 50, [r"demerger", r"scheme of arrangement"]), ("M&A", "merger", "positive", 55, [r"\bmerger\b", r"amalgamation"]),
    ("M&A", "open_offer", "positive", 55, [r"open offer", r"takeover"]), ("M&A", "stake_sale", "mixed", 45, [r"stake (?:sale|purchase)", r"divest"]),
    ("M&A", "acquisition", "positive", 50, [r"acqui(?:re|sition|red)"]),
    ("CAPITAL", "buyback", "positive", 45, [r"buy[- ]?back"]), ("CAPITAL", "bonus_split", "positive", 35, [r"bonus (?:issue|shares)", r"stock split", r"sub-?division"]),
    ("CAPITAL", "delisting", "mixed", 60, [r"delist"]), ("CAPITAL", "dividend", "positive", 20, [r"\bdividend\b"]),
    ("CAPITAL", "fund_raise", "mixed", 40, [r"\bqip\b", r"preferential (?:issue|allotment)", r"rights issue", r"fund ?rais", r"\bfpo\b", r"\bipo\b", r"\bncd\b"]),
    ("FINANCIAL", "rating_downgrade", "negative", 65, [r"downgrad", r"negative outlook", r"rating watch with negative"]), ("FINANCIAL", "default", "negative", 85, [r"\bdefault(?:ed|s)?\b"]),
    ("FINANCIAL", "insolvency", "negative", 80, [r"insolvency", r"\bcirp\b", r"resolution plan", r"liquidation", r"\bibc\b", r"admitted (?:by|under) nclt"]),
    ("FINANCIAL", "debt_restructuring", "negative", 60, [r"debt restructur", r"one[- ]time settlement", r"\bots\b"]),
    ("FINANCIAL", "rating_upgrade", "positive", 55, [r"upgrad", r"positive outlook"]), ("FINANCIAL", "rating_watch", "neutral", 40, [r"reaffirm", r"rating (?:continues on )?watch"]),
    ("LEGAL", "tax_demand", "negative", 45, [r"tax demand", r"demand notice", r"attach(?:ed|ment) of (?:property|assets|bank)"]),
    ("LEGAL", "arbitration", "mixed", 40, [r"arbitra"]), ("LEGAL", "litigation", "negative", 40, [r"litigation", r"petition", r"lawsuit", r"\bsuit\b"]),
    ("CORPORATE", "disruption", "negative", 60, [r"\bfire\b", r"explosion", r"accident", r"shut ?down", r"suspension of (?:operations|production)", r"strike\b", r"cyber ?attack", r"ransomware"]),
    ("CORPORATE", "capacity", "positive", 45, [r"commission(?:ed|ing)", r"capacity (?:expansion|addition)", r"new plant", r"greenfield", r"brownfield"]),
    ("CORPORATE", "resignation", "negative", 30, [r"resign(?:ation|ed|s)", r"cessation", r"steps? down"]),
    ("CORPORATE", "management_change", "negative", 45, [r"\barrest", r"\bfraud\b", r"embezzl"]),
    ("CORPORATE", "promoter_transaction", "mixed", 35, [r"promoter.{0,30}(?:pledge|sale|sold|acquired|purchase)", r"pledg(?:e|ed) (?:of )?shares"]),
    ("CORPORATE", "director_change", "neutral", 15, [r"change in director", r"appoint(?:ment|ed|s)\b", r"re-?appoint"]),
    ("RESULTS", "quarterly", "mixed", 60, [r"financial results", r"unaudited (?:financial )?results", r"audited (?:financial )?results", r"results for the quarter"]),
    ("INSTITUTION", "appointment", "positive", 55, [r"validation agent", r"appointed as (?:an? )?(?:agent|partner|distributor|authori[sz]ed)", r"recogni[sz]ed as", r"selected as", r"empanel(?:led|ment)"]),
    ("INSTITUTION", "accreditation", "positive", 50, [r"accredit(?:ed|ation)", r"certif(?:ied|ication) (?:by|from)"]),
    ("INSTITUTION", "partnership", "positive", 35, [r"\bmou\b", r"partnership", r"collaborat", r"tie-?up", r"joint venture"]),
    ("GOVERNMENT", "tender", "neutral", 40, [r"\btender", r"\bbids? invited", r"request for proposal", r"\brfp\b", r"निविदा"]),
    ("GOVERNMENT", "subsidy", "positive", 45, [r"subsid", r"\bpli\b", r"incentive scheme"]), ("GOVERNMENT", "tariff", "mixed", 45, [r"tariff", r"safeguard duty", r"anti-?dumping", r"duty (?:on|for)"]),
    ("GOVERNMENT", "procurement", "positive", 45, [r"procurement", r"\bdac\b.{0,40}(?:approv|clear)"]), ("GOVERNMENT", "project", "neutral", 35, [r"foundation stone", r"inaugurat", r"project (?:approved|sanctioned|awarded)"]),
    ("GOVERNMENT", "circular", "neutral", 30, [r"master direction", r"\bcircular\b", r"notification", r"amendment", r"guidelines"]),
    ("GOVERNMENT", "policy", "neutral", 40, [r"\bpolicy\b", r"\bscheme\b", r"योजना", r"अधिसूचना", r"नीति"]),
    ("ROUTINE", "routine", "neutral", 5, [r"trading window", r"investor meet", r"con\.? ?call", r"analyst", r"newspaper publication", r"scrutini[sz]er", r"\bagm\b", r"annual general meeting", r"\begm\b", r"postal ballot", r"book closure", r"record date", r"esop", r"esos", r"reg(?:ulation)?\.? ?74", r"certificate under", r"compliance certificate", r"loss of share certificate", r"shareholders meeting", r"e-?voting", r"closure of trading"]),
]
# exchange categories → (group, subtype, direction, severity); the category is authoritative for the group
CATEGORY_MAP = {
    "Trading Window": ("ROUTINE", "routine", "neutral", 5), "Analysts/Institutional Investor Meet/Con. Call Updates": ("ROUTINE", "routine", "neutral", 5), "Shareholders meeting": ("ROUTINE", "routine", "neutral", 5),
    "Copy of Newspaper Publication": ("ROUTINE", "routine", "neutral", 5), "ESOP/ESOS/ESPS": ("ROUTINE", "routine", "neutral", 5), "Reply to Clarification- Financial results": ("ROUTINE", "routine", "neutral", 5),
    "Certificate under SEBI (Depositories and Participants) Regulations": ("ROUTINE", "routine", "neutral", 5), "Loss of share certificates": ("ROUTINE", "routine", "neutral", 5),
    "Insider Trading / SAST": ("ROUTINE", "routine", "neutral", 5), "Closure of Trading Window": ("ROUTINE", "routine", "neutral", 5), "Investor Presentation": ("ROUTINE", "routine", "neutral", 8),
    "Change in Director(s)": ("CORPORATE", "director_change", "neutral", 15), "Change in Management": ("CORPORATE", "management_change", "neutral", 25), "Appointment": ("CORPORATE", "appointment", "neutral", 15),
    "Resignation of Director/KMP/SMP": ("CORPORATE", "resignation", "negative", 30), "Resignation": ("CORPORATE", "resignation", "negative", 30), "Cessation": ("CORPORATE", "resignation", "negative", 25),
    "Action(s) taken or orders passed": ("REGULATORY", "regulatory_order", "negative", 60), "Action(s) initiated or orders passed": ("REGULATORY", "regulatory_order", "negative", 60),
    "Granting/withdrawal/surrender/cancellation/suspension of key licenses/ regulatory approvals": ("REGULATORY", "approval", "mixed", 55),
    "Credit Rating": ("FINANCIAL", "rating_watch", "neutral", 40), "Outcome of Board Meeting": ("RESULTS", "board_outcome", "mixed", 40), "Financial Results": ("RESULTS", "quarterly", "mixed", 60),
    "Acquisition": ("M&A", "acquisition", "positive", 50), "Bagging/Receiving of orders/contracts": ("CONTRACT", "order_win", "positive", 55), "Capacity addition": ("CORPORATE", "capacity", "positive", 45),
    "Product launch": ("CORPORATE", "product_launch", "positive", 25), "Press Release": ("INSTITUTION", "press_release", "neutral", 30), "General Updates": ("CORPORATE", "update", "neutral", 20), "Updates": ("CORPORATE", "update", "neutral", 20),
    "Fund Raising": ("CAPITAL", "fund_raise", "mixed", 40), "Buyback": ("CAPITAL", "buyback", "positive", 45), "Dividend": ("CAPITAL", "dividend", "positive", 20), "Bonus": ("CAPITAL", "bonus_split", "positive", 35),
    "Options to purchase securities": ("CORPORATE", "update", "neutral", 15), "Company Update": (None, None, None, None), "Corp. Action": ("CAPITAL", "dividend", "neutral", 15),
}
_DEVANAGARI = re.compile(r"[ऀ-ॿ]")
_MONEY = re.compile(r"(?:rs\.?|inr|₹)\s*([\d,]+(?:\.\d+)?)\s*(crore|cr\b|lakh|million|mn|billion|bn)", re.I)
_REGULATION_NAMES = re.compile(r"\(?prohibition of insider trading\)?|prohibition of fraudulent|substantial acquisition of shares|listing obligations and disclosure|\bpit regulations?\b", re.I)
_NEGATION_BEFORE = re.compile(r"\b(?:not|no|never|neither|nor|without|non)\b(?:\s+\w+){0,4}\s*$", re.I)
_NEGATION_AFTER = re.compile(r"^\s*(?:\w+\s+){0,2}(?:not|no)\b", re.I)


GENERIC_CATEGORIES = {"Updates", "General Updates", "Press Release", "Company Update", "Corporate Update", "Others", "Other"}


def _negated(low: str, m: "re.Match") -> bool:
    return bool(_NEGATION_BEFORE.search(low[max(0, m.start() - 60): m.start()]) or _NEGATION_AFTER.match(low[m.end(): m.end() + 30]))


def _whole_word(low: str, m: "re.Match") -> str:
    start, end = m.start(), max(m.end(), m.start())
    while start > 0 and (low[start - 1].isalnum() or low[start - 1] in "-'"):
        start -= 1
    while end < len(low) and (low[end].isalnum() or low[end] in "-'"):
        end += 1
    return low[start:end]


def _text(e: dict) -> str:
    raw = " ".join(x for x in (e.get("title"), e.get("summary"), e.get("doc_text")) if x)
    return _REGULATION_NAMES.sub(" ", raw)


def _quantities(text: str) -> dict:
    q = {}
    for amount, unit in _MONEY.findall(text):
        v = float(amount.replace(",", "")); u = unit.lower()
        cr = v if u.startswith("cr") else v / 100 if u.startswith("lakh") else v * 0.1 if u in ("million", "mn") else v * 100 if u in ("billion", "bn") else v
        q.setdefault("order_value_cr", cr); q.setdefault("amounts_cr", []).append(round(cr, 2))
    return q


def _best_rule(low: str, allowed_groups=None):
    best = None
    for group, sub, direction, prior, pats in RULES:
        if allowed_groups is not None and group not in allowed_groups:
            continue
        terms = []
        for p in pats:
            for m in re.finditer(p, low):
                if direction == "negative" and _negated(low, m):
                    continue
                terms.append(_whole_word(low, m)); break
        if terms and (best is None or prior > best[3]):
            best = (group, sub, direction, prior, terms)
    return best


def _result(group, sub, direction, severity, terms, named, text, lang, conf, doc):
    return {"event_type": group, "event_subtype": sub, "direction": direction, "event_severity": int(severity), "materiality": int(severity), "confidence": round(min(conf, 0.95), 2),
            "matched_terms": [t.strip()[:32] for t in terms][:6], "named_authorities": named, "quantities": _quantities(text), "raw_language": lang, "classifier": "rules-v2",
            "classification_method": "RULE"}


def _authorities_by_relevance(low: str, terms: list[str]) -> list[str]:
    """Named authorities ordered by distance to the first matched event term (the authority that acted), else by position."""
    anchor = min((low.find(t) for t in terms if t and low.find(t) >= 0), default=-1)
    found = []
    for name, pats in AUTHORITIES.items():
        pos = [m.start() for p in pats for m in re.finditer(p, low)]
        if pos:
            found.append((min(abs(x - anchor) for x in pos) if anchor >= 0 else min(pos), name))
    return [n for _, n in sorted(found)]


def classify(e: dict) -> dict:
    text = _text(e); low = text.lower()
    lang = "hi" if len(_DEVANAGARI.findall(text)) > max(10, 0.3 * len(text)) else "en"
    named = _authorities_by_relevance(low, [])
    doc = bool(e.get("doc_text")); cat = e.get("category") or ""
    cm = CATEGORY_MAP.get(cat)
    if cat in GENERIC_CATEGORIES:
        cm = None                                              # "Updates" / "Press Release" carry no information: full rule search
    exchange = str(e.get("source_id", "")).startswith(("nse_", "bse_"))
    if cm and cm[0] == "ROUTINE":
        return _result("ROUTINE", "routine", "neutral", 5, [f"category:{cat}"], named, text, lang, 0.9, doc)
    if cm and cm[0]:
        group, sub, direction, sev = cm
        # keyword rules may refine within the category's group; a move into REGULATORY needs a named authority and a regulatory term
        best = _best_rule(low, allowed_groups={group, "REGULATORY", "PHARMA"} if named else {group})
        if best and best[0] in ("REGULATORY", "PHARMA") and group not in ("REGULATORY", "PHARMA") and best[3] < 70:
            best = _best_rule(low, allowed_groups={group})
        if best:
            group, sub, direction, sev, terms = best[0], best[1], best[2], max(sev, best[3]), best[4]
        else:
            terms = [f"category:{cat}"]
        named = _authorities_by_relevance(low, [t for t in terms if not t.startswith("category:")])
        if group in ("REGULATORY", "PHARMA", "CONTRACT", "FINANCIAL") and named:
            sev = min(100, sev + 5)
        return _result(group, sub, direction, sev, terms, named, text, lang, 0.65 + (0.1 if named else 0) + (0.1 if doc else 0), doc)
    best = _best_rule(low)
    if best is None:
        return _result("UNCLASSIFIED", "unclassified", "neutral", 15, [], named, text, lang, 0.3, doc)
    group, sub, direction, sev, terms = best
    named = _authorities_by_relevance(low, terms)
    if group in ("REGULATORY", "PHARMA", "CONTRACT", "FINANCIAL") and named:
        sev = min(100, sev + 5)
    if group == "CONTRACT" and sub == "loa" and not named:
        sub = "order_win"
    conf = 0.6 + 0.1 * min(3, len(terms)) + (0.1 if named else 0.0) + (0.05 if doc else 0.0)
    return _result(group, sub, direction, sev, terms, named, text, lang, conf, doc)
