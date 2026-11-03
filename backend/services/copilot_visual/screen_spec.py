"""A screening sentence turned into the Screener's own rules, and an honest list of the words that were not used.

Slice W4 of docs/plans_20261031/SCREENER_WATCHLIST_PLAN.md. The legacy parser in the recommendation node
(`_parse_screen_filters`) claims the phrases it knows and IGNORES the rest without saying so; this one reads the same
vocabulary the same way (the node's own metric table, so a rule means the same thing in both) and then reports what is
left over, so the answer can say "Not used: …" instead of silently running a different screen from the one that was asked.

    "Screen large cap stocks with ROE over 20 and debt to equity under 0.5"
      → conditions [{roe over 20}, {de under 0.5}], bucket "large", not_used []

The result is exactly the request `POST /api/screeners/run` takes (conditions / bucket / sector): nothing here runs a
screen, reads data or calls a model. Pure functions, no I/O: the vocabulary is passed in (readers.screen_vocabulary reads it
from the node), so tests can pin it.

What is NOT understood is never guessed at: an unknown word is listed, a number with no metric is listed, "micro cap" (the
screener has large / mid / small only) is listed. Several rules on one metric are kept as written (the screener keeps the
stricter bound; the words show both).
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Sequence, Tuple

# (widget key, regex) in the node's order — longer, more specific phrases first.
Vocabulary = Tuple[Sequence[Tuple[str, str]], str, str]

OP_WORD = {"over": "over", "under": "under"}
MAX_NOT_USED = 8

# Words that carry no rule: the sentence's scaffolding. Anything else left after the rules are read is reported.
_FILLER = frozenset("""
a an the and or of in on at for to by from with where whose that which what who whom whose have has having had is are was were be been
screen screens screener screening filter filters find show me list give get see want need please can could you i my us we
stock stocks share shares compan company companies firm firms scrip scrips name names
all any every some those these them it its than then also only just both either
above below over under more less greater lower higher at least most min max minimum maximum
""".split())

_SECTOR = re.compile(r"\b(?:in|from|within)\s+(?:the\s+)?([a-z][a-z&\- ]{1,28}?)\s+(?:sector|industry)\b|\b(?:sector|industry)\s*(?:is|=|:)\s*([a-z][a-z&\- ]{1,28})\b")
_BUCKETS: Tuple[Tuple[str, str, Optional[str]], ...] = (
    (r"large[\s-]*caps?", "Large cap", "large"),
    (r"mid[\s-]*caps?", "Mid cap", "mid"),
    (r"small[\s-]*caps?", "Small cap", "small"),
    (r"micro[\s-]*caps?", "Micro cap", None),            # the screener has no micro-cap bucket: reported, not guessed
)
_DEBT_FREE = re.compile(r"debt[\s-]*free|no\s+debt|zero\s+debt")
_LOW_DEBT = re.compile(r"low\s+debt")
_NUMBER = re.compile(r"-?\d+(?:\.\d+)?")


@dataclass
class ScreenSpec:
    conditions: List[Dict[str, Any]] = field(default_factory=list)     # [{key, op, value}] — the screener request's shape
    bucket: Optional[str] = None                                       # "large" | "mid" | "small"
    sector: Optional[str] = None
    not_used: List[str] = field(default_factory=list)                  # words / numbers / phrases that matched nothing
    bucket_label: Optional[str] = None
    # each rule, in the order the user wrote it, as (key, op, value) — for the words below
    order: List[Tuple[str, str, float]] = field(default_factory=list)

    @property
    def has_rules(self) -> bool:
        return bool(self.conditions or self.bucket or self.sector)

    def request(self) -> Dict[str, Any]:
        """The body of POST /api/screeners/run."""
        out: Dict[str, Any] = {"conditions": [dict(c) for c in self.conditions]}
        if self.bucket:
            out["bucket"] = self.bucket
        if self.sector:
            out["sector"] = self.sector
        return out


def _num_text(v: float) -> str:
    return f"{v:g}"


def words(spec: ScreenSpec, labels: Dict[str, str]) -> str:
    """The rules in words: "ROE over 20 · Debt / Equity under 0.5 · Large cap"."""
    parts: List[str] = []
    if spec.bucket_label and spec.bucket:
        parts.append(spec.bucket_label)
    for key, op, value in spec.order:
        parts.append(f"{labels.get(key, key)} {OP_WORD[op]} {_num_text(value)}")
    if spec.sector:
        parts.append(f"sector contains “{spec.sector}”")
    return " · ".join(parts)


def query_string(spec: ScreenSpec) -> str:
    """The rules as the Screener page reads them from its address: `r=roe:over:20,de:under:0.5&b=large&s=IT`.
    Only letters, digits and `: , . - & = _` are produced, so it is safe to carry in a link."""
    bits: List[str] = []
    if spec.conditions:
        bits.append("r=" + ",".join(f"{c['key']}:{c['op']}:{_num_text(float(c['value']))}" for c in spec.conditions))
    if spec.bucket:
        bits.append(f"b={spec.bucket}")
    if spec.sector and re.fullmatch(r"[A-Za-z0-9 ]{1,30}", spec.sector):
        bits.append("s=" + spec.sector.replace(" ", "_"))
    return "&".join(bits)


def parse(message: str, vocab: Vocabulary) -> ScreenSpec:
    """Read `message` against the node's metric vocabulary. Never raises; an unreadable sentence gives an empty spec."""
    metrics, min_words, max_words = vocab
    original = (message or "").strip()
    text = original.lower()
    work = text                                     # matched spans are blanked as they are claimed
    spec = ScreenSpec()
    found: List[Tuple[int, str, str, float]] = []   # (position, key, op, value)

    def claim(m: "re.Match[str]") -> None:
        nonlocal work
        work = work[:m.start()] + " " * (m.end() - m.start()) + work[m.end():]

    number = r"(-?\d+(?:\.\d+)?)"
    for key, syn in metrics:
        for op_words, op in ((min_words, "over"), (max_words, "under")):
            # a metric phrase, a few non-number characters, an over/under word, a number: the node's own shape of a rule
            for m in list(re.finditer(rf"(?:{syn})[^\d-]{{0,12}}?(?:{op_words})\s*{number}", work)):
                if work[m.start():m.end()].strip() == "":
                    continue                          # already claimed by an earlier, more specific phrase
                found.append((m.start(), key, op, float(m.group(1))))
                claim(m)

    # Qualitative shortcuts the node also knows. Only when the user wrote no debt rule of their own.
    have = {k for _, k, _, _ in found}
    m = _DEBT_FREE.search(work)
    if m:
        if "de" not in have:
            found.append((m.start(), "de", "under", 0.1))
        claim(m)
    m = _LOW_DEBT.search(work)
    if m:
        if "de" not in {k for _, k, _, _ in found}:
            found.append((m.start(), "de", "under", 0.5))
        claim(m)

    for pattern, label, bucket in _BUCKETS:
        m = re.search(pattern, work)
        if not m:
            continue
        claim(m)
        if bucket is None:
            spec.not_used.append(label.lower() + " (the screener has large, mid and small cap only)")
        elif spec.bucket is None:
            spec.bucket, spec.bucket_label = bucket, label
        else:
            spec.not_used.append(label.lower() + " (one size bucket per screen)")

    m = _SECTOR.search(work)
    if m:
        name = (m.group(1) or m.group(2) or "").strip()
        claim(m)
        if name:
            spec.sector = name.upper() if len(name) <= 3 else name.title()

    found.sort(key=lambda f: f[0])
    spec.order = [(k, op, v) for _, k, op, v in found]
    spec.conditions = [{"key": k, "op": op, "value": v} for _, k, op, v in found]

    # What is left: numbers first (a number nothing used is the dangerous one), then words that are not scaffolding.
    leftovers: List[str] = []
    for tok in re.findall(r"-?\d+(?:\.\d+)?|[a-z][a-z&/\-']*", work):
        if _NUMBER.fullmatch(tok):
            leftovers.append(tok)
        elif tok not in _FILLER:
            leftovers.append(tok)
    # keep the user's own spelling for what is reported, in order, without repeats
    shown: List[str] = []
    for tok in leftovers:
        if tok not in shown:
            shown.append(tok)
    spec.not_used += shown
    spec.not_used = spec.not_used[:MAX_NOT_USED]
    return spec
