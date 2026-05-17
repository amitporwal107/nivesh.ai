"""
CAS Parser Comparison — casparser lib vs Nivesh (DocAI+Claude) vs Claude Vision standalone
Run this ON THE VM where all keys are configured:

  cd /opt/nivesh/repo
  sudo -E python3 scripts/compare_cas_parsers.py --password AMPPP4547E

Or for a single PDF:
  sudo -E python3 scripts/compare_cas_parsers.py --password AMPPP4547E --pdf /path/to/file.pdf
"""

import argparse
import asyncio
import io
import json
import os
import sys
import time
from pathlib import Path
from typing import Optional

# ── Ensure backend is on the Python path ────────────────────────────────
REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "backend"))

# Load env from .env.prod if present (VM), else .env (local)
def _load_env():
    for f in ["/opt/nivesh/.env.prod", str(REPO_ROOT / "backend/.env")]:
        if Path(f).exists():
            for line in Path(f).read_text().splitlines():
                line = line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                k, _, v = line.partition("=")
                v = v.strip('"').strip("'")
                if k and v and k not in os.environ:
                    os.environ[k] = v
            break

_load_env()

DEFAULT_PDF_DIR = "/opt/nivesh/data/app/gmail_cas"


# ── Parser 1: casparser library ──────────────────────────────────────────

def run_casparser_lib(pdf_bytes: bytes, password: str) -> dict:
    """Run the open-source casparser Python library (CAMS/KFintech/NSDL/CDSL)."""
    try:
        import casparser
        t0 = time.monotonic()
        result = casparser.read_cas_pdf(io.BytesIO(pdf_bytes), password, "dict")
        elapsed = time.monotonic() - t0

        d = result.model_dump() if hasattr(result, "model_dump") else (
            result.dict() if hasattr(result, "dict") else result
        )

        def _norm(obj):
            return obj.model_dump() if hasattr(obj, "model_dump") else (
                obj.dict() if hasattr(obj, "dict") else obj
            )

        investor = _norm(d.get("investor_info") or {})
        investor_name = investor.get("name", "") if isinstance(investor, dict) else ""

        # NSDL: accounts[].equities + accounts[].mutual_funds
        mf, equities = [], []
        for acc in (d.get("accounts") or []):
            a = _norm(acc)
            for eq in (a.get("equities") or []):
                e = _norm(eq)
                shares = float(e.get("num_shares", 0) or 0)
                if shares > 0:
                    equities.append({"isin": e.get("isin",""), "name": e.get("name",""),
                                     "shares": int(shares), "price": float(e.get("price",0) or 0)})
            for m in (a.get("mutual_funds") or []):
                mu = _norm(m)
                bal = float(mu.get("balance", 0) or 0)
                if bal > 0:
                    mf.append({"isin": mu.get("isin",""),
                               "name": (mu.get("name") or "").replace("\n"," ").replace("\t"," "),
                               "units": round(bal, 4),
                               "nav": float(mu.get("nav",0) or 0),
                               "source": "demat"})

        # CAMS/KFintech: folios[].schemes
        for folio in (d.get("folios") or []):
            if isinstance(folio, int):
                continue
            f = _norm(folio)
            for scheme in (f.get("schemes") or []):
                s = _norm(scheme)
                units = s.get("close_calculated") or s.get("close", 0) or 0
                if float(units) <= 0:
                    continue
                val = _norm(s.get("valuation") or {})
                mf.append({"isin": s.get("isin",""),
                           "name": s.get("scheme",""),
                           "units": round(float(units), 4),
                           "nav": float(val.get("nav", 0) or 0),
                           "source": "folio"})

        return {"ok": True, "elapsed_s": round(elapsed, 2),
                "mf": mf, "equities": equities,
                "investor": investor_name, "error": None}

    except Exception as e:
        err = str(e)
        if any(t in err.lower() for t in ["password","incorrect","decrypt","wrong"]):
            return {"ok": False, "error": "wrong_password", "mf": [], "equities": [], "elapsed_s": 0}
        return {"ok": False, "error": err[:120], "mf": [], "equities": [], "elapsed_s": 0}


# ── Parser 2: Nivesh (Document AI + Claude Vision) ───────────────────────

async def run_nivesh_parser(pdf_bytes: bytes, password: str) -> dict:
    """Run the Nivesh CAS parser (Google Document AI → Claude normalizer)."""
    try:
        from services.nivesh_cas_parser import parse_with_nivesh, is_configured
        if not is_configured():
            return {"ok": False, "error": "not_configured (GOOGLE_DOCAI_* missing)",
                    "mf": [], "equities": [], "elapsed_s": 0}

        from services.claude_cas_mapper import map_to_internal

        t0 = time.monotonic()
        raw = await asyncio.to_thread(parse_with_nivesh, pdf_bytes, password)
        if not raw:
            return {"ok": False, "error": "returned None", "mf": [], "equities": [], "elapsed_s": 0}

        holdings, _ = map_to_internal(raw)
        elapsed = time.monotonic() - t0

        mf = [h for h in holdings if h.get("asset_type") in ("mutual_fund", "etf", "gold")]
        eq = [h for h in holdings if h.get("asset_type") == "equity"]

        return {"ok": True, "elapsed_s": round(elapsed, 2),
                "mf": [{"isin": h.get("ticker",""), "name": h.get("name",""),
                         "units": h.get("quantity",0), "nav": h.get("current_price",0),
                         "source": "nivesh"} for h in mf],
                "equities": [{"isin": h.get("ticker",""), "name": h.get("name",""),
                               "shares": int(h.get("quantity",0)), "price": h.get("current_price",0)} for h in eq],
                "investor": (raw.get("investor_info") or {}).get("name",""),
                "error": None}

    except Exception as e:
        return {"ok": False, "error": str(e)[:120], "mf": [], "equities": [], "elapsed_s": 0}


# ── Parser 3: Claude Vision standalone ──────────────────────────────────

async def run_claude_vision(pdf_bytes: bytes, password: str) -> dict:
    """Run the Claude Vision CAS parser (PDF → images → Claude Sonnet)."""
    try:
        from services.claude_cas_parser import parse_with_claude_vision, is_configured
        if not is_configured():
            return {"ok": False, "error": "not_configured (EMERGENT_LLM_KEY missing)",
                    "mf": [], "equities": [], "elapsed_s": 0}

        from services.claude_cas_mapper import map_to_internal

        t0 = time.monotonic()
        raw = await parse_with_claude_vision(pdf_bytes, password=password)
        if not raw:
            return {"ok": False, "error": "returned None", "mf": [], "equities": [], "elapsed_s": 0}

        holdings, _ = map_to_internal(raw)
        elapsed = time.monotonic() - t0

        mf = [h for h in holdings if h.get("asset_type") in ("mutual_fund", "etf", "gold")]
        eq = [h for h in holdings if h.get("asset_type") == "equity"]

        return {"ok": True, "elapsed_s": round(elapsed, 2),
                "mf": [{"isin": h.get("ticker",""), "name": h.get("name",""),
                         "units": h.get("quantity",0), "nav": h.get("current_price",0),
                         "source": "claude"} for h in mf],
                "equities": [{"isin": h.get("ticker",""), "name": h.get("name",""),
                               "shares": int(h.get("quantity",0)), "price": h.get("current_price",0)} for h in eq],
                "investor": (raw.get("investor_info") or {}).get("name",""),
                "error": None}

    except Exception as e:
        err = str(e)
        if "password" in err.lower():
            return {"ok": False, "error": "wrong_password", "mf": [], "equities": [], "elapsed_s": 0}
        return {"ok": False, "error": err[:120], "mf": [], "equities": [], "elapsed_s": 0}


# ── Analysis helpers ──────────────────────────────────────────────────────

def overlap(a: dict, b: dict) -> dict:
    ai = {h["isin"] for h in a.get("mf", []) if h.get("isin")}
    bi = {h["isin"] for h in b.get("mf", []) if h.get("isin")}
    return {"both": len(ai & bi), "only_a": sorted(ai - bi), "only_b": sorted(bi - ai)}


def fmt_result(r: dict, field: str, fmt: str = "{}") -> str:
    if not r["ok"]:
        return r.get("error", "ERR")[:12]
    return fmt.format(r.get(field, 0))


# ── Main ─────────────────────────────────────────────────────────────────

async def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--password", required=True, help="PAN used to decrypt CAS PDFs")
    ap.add_argument("--pdf-dir", default=DEFAULT_PDF_DIR, help="Directory of PDF files")
    ap.add_argument("--pdf", help="Single PDF path (overrides --pdf-dir)")
    ap.add_argument("--limit", type=int, default=10)
    ap.add_argument("--json-out", default="/tmp/cas_compare_results.json")
    ap.add_argument("--skip-claude", action="store_true", help="Skip Claude Vision (faster)")
    args = ap.parse_args()

    if args.pdf:
        pdfs = [Path(args.pdf)]
    else:
        # Walk all user subdirs
        base = Path(args.pdf_dir)
        pdfs = sorted(base.rglob("*.pdf"))[:args.limit]

    if not pdfs:
        print(f"No PDFs found in {args.pdf_dir}"); sys.exit(1)

    W = 115
    print(f"\n{'='*W}")
    print(f"  CAS Parser Comparison — {len(pdfs)} PDF(s)  |  password='{args.password}'")
    print(f"{'='*W}")
    cols = f"{'FILE':<26} {'CAS-lib MF':>11} {'CAS EQ':>7} {'Nivesh MF':>10} {'Niv EQ':>7} {'Claude MF':>10} {'Cld EQ':>7} {'CAS t':>6} {'Niv t':>7} {'Cld t':>7} {'CAS∩Niv':>8} {'CAS∩Cld':>8}"
    print(cols)
    print("-"*W)

    all_results = []
    totals = {k: 0.0 for k in ["cas_mf","cas_eq","niv_mf","niv_eq","cld_mf","cld_eq",
                                 "cas_t","niv_t","cld_t","cn_both","cc_both"]}

    for pdf_path in pdfs:
        pdf_bytes = pdf_path.read_bytes()
        name = "/".join(pdf_path.parts[-2:])[:24]

        cas = run_casparser_lib(pdf_bytes, args.password)
        niv = await run_nivesh_parser(pdf_bytes, args.password)
        cld = await run_claude_vision(pdf_bytes, args.password) if not args.skip_claude else \
              {"ok": False, "error": "skipped", "mf": [], "equities": [], "elapsed_s": 0}

        cn = overlap(cas, niv)
        cc = overlap(cas, cld)

        def fv(r, key, fmt="{:>4}"):
            return fmt.format(r[key]) if r["ok"] else "ERR"

        row = (f"{name:<26} "
               f"{fv(cas,'mf','{:>11}'):>11} {len(cas.get('equities',[])):>7} "
               f"{fv(niv,'mf','{:>10}'):>10} {len(niv.get('equities',[])):>7} "
               f"{fv(cld,'mf','{:>10}'):>10} {len(cld.get('equities',[])):>7} "
               f"{fv(cas,'elapsed_s','{:>6.1f}'):>6} {fv(niv,'elapsed_s','{:>7.1f}'):>7} {fv(cld,'elapsed_s','{:>7.1f}'):>7} "
               f"{cn['both']:>8} {cc['both']:>8}")
        print(row)

        all_results.append({"file": str(pdf_path), "casparser": cas, "nivesh": niv, "claude": cld,
                             "overlap_cas_nivesh": cn, "overlap_cas_claude": cc})

        def add(key, r, field):
            if r["ok"]:
                totals[key] += len(r.get(field, [])) if isinstance(r.get(field), list) else r.get(field, 0)

        if cas["ok"]:
            totals["cas_mf"] += len(cas.get("mf",[])); totals["cas_eq"] += len(cas.get("equities",[])); totals["cas_t"] += cas["elapsed_s"]
        if niv["ok"]:
            totals["niv_mf"] += len(niv.get("mf",[])); totals["niv_eq"] += len(niv.get("equities",[])); totals["niv_t"] += niv["elapsed_s"]
        if cld["ok"]:
            totals["cld_mf"] += len(cld.get("mf",[])); totals["cld_eq"] += len(cld.get("equities",[])); totals["cld_t"] += cld["elapsed_s"]
        totals["cn_both"] += cn["both"]
        totals["cc_both"] += cc["both"]

    print("="*W)
    print(f"{'TOTAL':<26} "
          f"{int(totals['cas_mf']):>11} {int(totals['cas_eq']):>7} "
          f"{int(totals['niv_mf']):>10} {int(totals['niv_eq']):>7} "
          f"{int(totals['cld_mf']):>10} {int(totals['cld_eq']):>7} "
          f"{totals['cas_t']:>6.1f} {totals['niv_t']:>7.1f} {totals['cld_t']:>7.1f} "
          f"{int(totals['cn_both']):>8} {int(totals['cc_both']):>8}")

    # ── Per-file diff report ──────────────────────────────────────────
    print(f"\n{'─'*W}")
    print("FUNDS IN Nivesh/Claude but NOT in casparser-lib (these are the missing ones):\n")
    for row in all_results:
        name = Path(row["file"]).name[:20]
        for label, key, ovlp_key in [("Nivesh","nivesh","overlap_cas_nivesh"),
                                      ("Claude","claude","overlap_cas_claude")]:
            missed = row[ovlp_key].get("only_b", [])
            if missed:
                fund_map = {h["isin"]: h.get("name","") for h in row[key].get("mf",[])}
                for isin in missed:
                    print(f"  [{name}] {label}  {isin}  {fund_map.get(isin,'')[:55]}")

    print(f"\nFUNDS IN casparser-lib but NOT in Nivesh/Claude (casparser false positives):\n")
    for row in all_results:
        name = Path(row["file"]).name[:20]
        for label, ovlp_key in [("vs Nivesh","overlap_cas_nivesh"), ("vs Claude","overlap_cas_claude")]:
            missed = row[ovlp_key].get("only_a", [])
            if missed:
                fund_map = {h["isin"]: h.get("name","") for h in row["casparser"].get("mf",[])}
                for isin in missed:
                    print(f"  [{name}] {label}  {isin}  {fund_map.get(isin,'')[:55]}")

    Path(args.json_out).write_text(json.dumps(all_results, indent=2, default=str))
    print(f"\nDetailed results → {args.json_out}\n")


if __name__ == "__main__":
    asyncio.run(main())
