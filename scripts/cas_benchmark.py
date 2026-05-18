"""
CAS Parser Benchmark: casparser_lib vs Docling (fully local, no external APIs)
Usage:
    cd /app && python scripts/cas_benchmark.py [PDF_FILE [PASSWORD]]

Default test files and password below — edit as needed.
"""
import asyncio, sys, time, json, os
sys.path.insert(0, "/app/backend")

PDF_FILES = [
    "/app/data/gmail_cas/user_5d1fdd810738/b968c7ea485a4796.pdf",  # 513KB
    "/app/data/gmail_cas/user_5d1fdd810738/ff12b144cc024797.pdf",  # 486KB
    "/app/data/gmail_cas/user_5d1fdd810738/fcd5d28cdc454535.pdf",  # 435KB
    "/app/data/gmail_cas/user_5d1fdd810738/11ba8124d24847e3.pdf",  # 409KB
    "/app/data/gmail_cas/user_5d1fdd810738/697aaf07ce794d6f.pdf",  # 108KB
]
PDF_PASSWORD = "AMPPP4547E"


def summarise(holdings: list, source: str = "") -> dict:
    if not holdings:
        return {"count": 0, "equity": 0, "mutual_fund": 0, "gold": 0, "etf": 0,
                "isin_pct": 0.0, "zero_qty": 0, "truncated": 0, "duplicates": 0}
    by_type = {}
    for h in holdings:
        t = (h.get("asset_type") or "other").lower()
        by_type[t] = by_type.get(t, 0) + 1
    with_isin = sum(1 for h in holdings if (h.get("ticker") or h.get("isin") or "").strip())
    zero_qty  = sum(1 for h in holdings if float(h.get("quantity") or 1) == 0)
    trunc     = sum(1 for h in holdings
                    if h.get("asset_type") in ("mutual_fund", "etf")
                    and len(h.get("name", "")) < 20)
    names  = [h.get("name", "") for h in holdings]
    dupes  = len(names) - len(set(names))
    return {
        "count":       len(holdings),
        "equity":      by_type.get("equity", 0),
        "mutual_fund": by_type.get("mutual_fund", 0),
        "gold":        by_type.get("gold", 0),
        "etf":         by_type.get("etf", 0),
        "isin_pct":    round(with_isin / len(holdings) * 100, 1),
        "zero_qty":    zero_qty,
        "truncated":   trunc,
        "duplicates":  dupes,
    }


async def run_casparser(pdf_bytes: bytes, label: str) -> dict:
    import casparser as _casparser
    from helpers.parsing import convert_casparser_to_holdings
    t0 = time.perf_counter()
    try:
        import io
        cas_data = await asyncio.to_thread(
            _casparser.read_cas_pdf, io.BytesIO(pdf_bytes), PDF_PASSWORD, "dict"
        )
        holdings = convert_casparser_to_holdings(cas_data)
        elapsed = round(time.perf_counter() - t0, 2)
        return {
            "parser": "casparser_lib", "file": label, "elapsed_s": elapsed,
            "ok": bool(holdings), "summary": summarise(holdings), "error": None,
        }
    except Exception as e:
        return {
            "parser": "casparser_lib", "file": label,
            "elapsed_s": round(time.perf_counter() - t0, 2),
            "ok": False, "summary": None, "error": str(e)[:300],
        }


async def run_docling(pdf_bytes: bytes, label: str) -> dict:
    from services.docling_cas_parser import parse_with_docling, is_available
    t0 = time.perf_counter()
    if not is_available():
        return {
            "parser": "docling", "file": label, "elapsed_s": 0,
            "ok": False, "summary": None, "error": "docling not installed — pip install docling",
        }
    try:
        holdings, _ = await asyncio.to_thread(parse_with_docling, pdf_bytes, PDF_PASSWORD)
        elapsed = round(time.perf_counter() - t0, 2)
        return {
            "parser": "docling", "file": label, "elapsed_s": elapsed,
            "ok": bool(holdings), "summary": summarise(holdings), "error": None,
        }
    except Exception as e:
        return {
            "parser": "docling", "file": label,
            "elapsed_s": round(time.perf_counter() - t0, 2),
            "ok": False, "summary": None, "error": str(e)[:300],
        }


async def run_full_chain(pdf_bytes: bytes, label: str) -> dict:
    """End-to-end chain as used in production (parsing.py)."""
    from helpers.parsing import parse_cas_pdf_with_data
    t0 = time.perf_counter()
    try:
        holdings, normalized, _, source = await parse_cas_pdf_with_data(pdf_bytes, PDF_PASSWORD)
        elapsed = round(time.perf_counter() - t0, 2)
        return {
            "parser": f"chain({source})", "file": label, "elapsed_s": elapsed,
            "ok": bool(holdings), "summary": summarise(holdings), "error": None,
        }
    except Exception as e:
        return {
            "parser": "chain", "file": label,
            "elapsed_s": round(time.perf_counter() - t0, 2),
            "ok": False, "summary": None, "error": str(e)[:300],
        }


def print_row(r: dict) -> None:
    s = r["summary"]
    if r["ok"] and s and s.get("count", 0) > 0:
        print(
            f"  {r['parser']:22s}  {r['elapsed_s']:6.1f}s  "
            f"total={s['count']:3d}  isin={s['isin_pct']:5.1f}%  "
            f"trunc={s['truncated']:2d}  zero={s['zero_qty']:2d}  dupes={s['duplicates']:2d}  "
            f"[eq={s['equity']} mf={s['mutual_fund']} gold={s['gold']} etf={s['etf']}]"
        )
    else:
        print(f"  {r['parser']:22s}  FAILED: {(r.get('error') or '')[:120]}")


async def main() -> None:
    # Allow overriding PDF path and password from CLI args
    files = sys.argv[1:2] or PDF_FILES
    pwd   = sys.argv[2] if len(sys.argv) > 2 else PDF_PASSWORD

    from deps import db
    from helpers import secrets as _secrets
    await _secrets.hydrate_from_db(db)

    print("=" * 80)
    print("CAS PARSER BENCHMARK — fully local: casparser_lib + Docling")
    print(f"Password: {pwd}   Files: {len(files)}")
    print("=" * 80)

    all_results = []
    for pdf_path in files:
        if not os.path.exists(pdf_path):
            print(f"\n[SKIP] {pdf_path} — not found")
            continue
        label    = os.path.basename(pdf_path)[:18]
        size_kb  = round(os.path.getsize(pdf_path) / 1024)
        print(f"\n[{label}]  {size_kb} KB")

        with open(pdf_path, "rb") as fh:
            pdf_bytes = fh.read()

        results = await asyncio.gather(
            run_casparser(pdf_bytes, label),
            run_docling(pdf_bytes, label),
            run_full_chain(pdf_bytes, label),
        )
        for r in results:
            all_results.append(r)
            print_row(r)

    print("\n" + "=" * 80)
    print("AGGREGATE SUMMARY")
    print("=" * 80)
    parsers = sorted({r["parser"] for r in all_results})
    for parser in parsers:
        pr = [r for r in all_results if r["parser"] == parser and r["ok"] and r["summary"]]
        if not pr:
            total = [r for r in all_results if r["parser"] == parser]
            print(f"\n{parser}: 0/{len(total)} successful")
            continue
        def avg(k):
            return round(sum(r["summary"][k] for r in pr) / len(pr), 1)
        total_runs = len([r for r in all_results if r["parser"] == parser])
        print(f"\n{parser}  ({len(pr)}/{total_runs} successful):")
        print(f"  avg time          : {round(sum(r['elapsed_s'] for r in pr)/len(pr), 1)}s")
        print(f"  avg holdings      : {avg('count')}")
        print(f"  avg ISIN coverage : {avg('isin_pct')}%")
        print(f"  avg truncated MF  : {avg('truncated')}")
        print(f"  avg zero-qty      : {avg('zero_qty')}")
        print(f"  avg duplicates    : {avg('duplicates')}")


if __name__ == "__main__":
    asyncio.run(main())
