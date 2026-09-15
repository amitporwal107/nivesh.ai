"""Entity map: listed companies from the security master, curated non-listed entities and sourced relationships
(seed_relationships.csv). Resolution is exact symbol / scrip code first, then alias matching in text; propagation follows
the relationship rows with their sourced exposure. Nothing is inferred: an edge without a source row does not exist."""
from __future__ import annotations

import csv
import io
import re
from pathlib import Path
from typing import Optional

SEED_PATH = Path(__file__).with_name("seed_relationships.csv")
_SUFFIX = re.compile(r"\b(limited|ltd\.?|private|pvt\.?|corporation|corp\.?|company|co\.?|india|\(india\))\b", re.I)
AUTHORITY_ALIASES = {"Reserve Bank of India": ["rbi"], "Securities and Exchange Board of India": ["sebi"], "National Highways Authority of India": ["nhai"],
                     "Ministry of Road Transport and Highways": ["morth"], "Competition Commission of India": ["cci"], "Central Drugs Standard Control Organisation": ["cdsco"],
                     "US Food and Drug Administration": ["usfda", "us fda", "fda"], "Global Legal Entity Identifier Foundation": ["gleif"], "Ministry of Defence": ["ministry of defence", "mod"],
                     "Ministry of New and Renewable Energy": ["mnre"], "Tata Sons": ["tata sons"], "Awadh Expressway Private Limited": ["awadh expressway"]}


_COMMON = {"total", "global", "focus", "take", "marine", "sigma", "accuracy", "national", "india", "indian", "united", "modern", "premier", "standard", "supreme", "capital",
           "century", "orient", "oriental", "eastern", "western", "northern", "southern", "central", "royal", "star", "sun", "crown", "prime", "first", "one", "new", "best", "power",
           "energy", "finance", "industries", "infra", "tech", "systems", "solutions", "services", "trading", "exports", "textiles", "chemicals", "pharma", "steel", "cement", "motors",
           "bank", "insurance", "housing", "digital", "network", "media", "group", "holdings", "ventures", "enterprises", "international", "universal", "general", "lal", "shah", "pnc", "bse", "nse",
           "reliance", "alliance", "vision", "mission", "pioneer", "zenith", "summit", "matrix", "insight", "dynamic", "infinite", "sterling", "imperial", "classic", "jubilee", "arrow", "pearl",
           "diamond", "silver", "platinum", "eastern", "coastal", "national", "bharat", "hindustan", "modern", "welcome", "pearl", "mahindra", "birla", "jindal", "godrej", "adani", "tata"}


_FILLER = {"india", "indian", "the", "of", "and", "new", "company", "group", "industries", "enterprises", "international", "services", "solutions", "systems", "limited", "ltd"}


def _free_text_ok(alias: str) -> bool:
    """An alias may match free text only if it cannot be an ordinary word: two or more words, or one long uncommon word."""
    words = alias.split()
    if len(words) >= 2:                                  # "Tata Chemicals", "Adani Power": a group word plus a business word is a name
        return len(alias) >= 9 and not all(w in _FILLER for w in words)
    return len(alias) >= 6 and alias not in _COMMON


def _aliases(name: str) -> set[str]:
    base = re.sub(r"\s+", " ", _SUFFIX.sub(" ", name)).strip(" .,").lower()
    if len(base) < 4 or not _free_text_ok(base):          # "BSE Limited" is "bse" once the suffix goes: not a free-text alias
        return set()
    return {name.lower(), base}


class EntityMap:
    def __init__(self, listed: list[dict], seed_rows: list[dict]):
        self.by_symbol = {r["symbol"]: {"entity_name": r["company_name"], "entity_type": "listed_company", "symbol": r["symbol"], "isin": r.get("isin"), "sector": r.get("sector") or None} for r in listed}
        self.entities: dict[str, dict] = {v["entity_name"]: v for v in self.by_symbol.values()}
        self.alias_index: dict[str, str] = {}
        for v in self.by_symbol.values():
            for a in _aliases(v["entity_name"]):                 # symbols never match free text: NH, TOTAL, BSE are words too
                self.alias_index.setdefault(a, v["entity_name"])
        self.edges = seed_rows
        for r in seed_rows:
            self.entities.setdefault(r["source_entity"], {"entity_name": r["source_entity"], "entity_type": r["source_type"], "symbol": None, "sector": None})
            for a in _aliases(r["source_entity"]) | set(AUTHORITY_ALIASES.get(r["source_entity"], [])):   # curated aliases (rbi, nhai) are trusted
                self.alias_index.setdefault(a, r["source_entity"])
        for name, al in AUTHORITY_ALIASES.items():
            self.entities.setdefault(name, {"entity_name": name, "entity_type": "regulator", "symbol": None, "sector": None})
            for a in al:
                self.alias_index.setdefault(a, name)
        keys = sorted((re.escape(a) for a in self.alias_index), key=len, reverse=True) or ["(?!x)x"]
        self._rx = re.compile(r"(?<![A-Za-z0-9])(" + "|".join(keys) + r")(?![A-Za-z0-9])", re.I)

    @classmethod
    def from_csv_text(cls, names_csv: str, seed_path: Path = SEED_PATH) -> "EntityMap":
        listed = list(csv.DictReader(io.StringIO(names_csv)))
        seed = list(csv.DictReader(open(seed_path))) if Path(seed_path).exists() else []
        return cls(listed, seed)

    @classmethod
    def from_files(cls, names_path: Path, seed_path: Path = SEED_PATH) -> "EntityMap":
        return cls.from_csv_text(Path(names_path).read_text(), seed_path)

    def resolve_symbol(self, symbol: Optional[str]) -> Optional[dict]:
        return self.by_symbol.get(symbol) if symbol else None

    def resolve_name(self, name: Optional[str]) -> Optional[dict]:
        """Exact (normalised) legal-name match for a filer printed by the source (BSE SLONGNAME, NSE sm_name)."""
        if not name:
            return None
        key = re.sub(r"\s+", " ", _SUFFIX.sub(" ", name)).strip(" .,").lower()
        for v in self.by_symbol.values():
            if re.sub(r"\s+", " ", _SUFFIX.sub(" ", v["entity_name"])).strip(" .,").lower() == key:
                return v
        return None

    def resolve_issuer(self, e: dict) -> Optional[tuple[dict, str]]:
        """(entity, match_type) for the company that filed the event, or None for regulator / news items."""
        ent = self.resolve_symbol(e.get("symbol"))
        if ent:
            return ent, "exact_nse_issuer"
        if str(e.get("source_id", "")).startswith("bse_"):
            ent = self.resolve_name(e.get("entity_text"))
            if ent:
                return ent, "exact_bse_issuer"
        return None

    def find_in_text(self, text: str) -> list[dict]:
        if not text:
            return []
        seen, out = set(), []
        for m in self._rx.finditer(text):
            name = self.alias_index[m.group(1).lower()]
            if name not in seen:
                seen.add(name); out.append({**self.entities[name], "matched": m.group(1)})
        return out

    def regulator_sectors(self, name: str) -> list[str]:
        return [r["target_entity"] for r in self.edges if r["source_entity"] == name and r["relationship_type"] == "REGULATOR_SECTOR"]

    MATCH_TYPE = {"SUBSIDIARY": "verified_subsidiary", "PARENT": "verified_parent", "INVESTEE": "verified_investee", "PROMOTER": "verified_promoter", "ASSOCIATE": "associate_jv",
                  "JV": "associate_jv", "CONTRACTOR": "project_contractor", "PROJECT_OWNER": "project_contractor", "CUSTOMER": "supplier_customer", "SUPPLIER": "supplier_customer",
                  "LENDER": "supplier_customer", "BORROWER": "supplier_customer", "COMPETITOR": "sector_inference", "BENEFICIARY": "sector_inference", "SECTOR_MEMBER": "sector_inference"}

    def propagate(self, entity_name: str, direction: str = "neutral", materiality: int = 0, max_hops: int = 2, include_self: bool = True) -> list[dict]:
        """Listed stocks reached from `entity_name` through sourced edges, each with its match type, path and exposure."""
        out, seen = [], set()
        ent = self.entities.get(entity_name)
        if include_self and ent and ent.get("symbol"):
            out.append({"symbol": ent["symbol"], "hops": 0, "exposure": 1.0, "path": entity_name, "source_url": None, "confidence": 1.0, "relationship": "SELF", "match_type": "exact_entity"}); seen.add(ent["symbol"])
        frontier = [(entity_name, 0, entity_name, 1.0, 1.0)]
        while frontier:
            name, hops, path, conf, exp = frontier.pop(0)
            if hops >= max_hops:
                continue
            for r in self.edges:
                if r["source_entity"] != name or r["relationship_type"] == "REGULATOR_SECTOR":
                    continue
                sym = r.get("target_symbol") or None
                pct = float(r["ownership_pct"]) / 100 if r.get("ownership_pct") else None
                new_path = f"{path} → ({r['relationship_type']}{f' {r[chr(111)+chr(119)+chr(110)+chr(101)+chr(114)+chr(115)+chr(104)+chr(105)+chr(112)+chr(95)+chr(112)+chr(99)+chr(116)]}%' if r.get('ownership_pct') else ''}) → {r['target_entity']}"
                c = conf * float(r.get("confidence") or 0.5)
                if sym and sym not in seen:
                    seen.add(sym)
                    out.append({"symbol": sym, "hops": hops + 1, "exposure": (None if pct is None else round(pct * (exp or 1.0), 6)), "path": new_path,
                                "source_url": r.get("source_url"), "confidence": round(c, 3), "relationship": r["relationship_type"],
                                "match_type": self.MATCH_TYPE.get(r["relationship_type"], "sector_inference")})
                frontier.append((r["target_entity"], hops + 1, new_path, c, pct if pct is not None else exp))
        return out
