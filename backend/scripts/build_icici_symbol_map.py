"""Build backend/data/broker_symbols/icicidirect.csv from ICICI Direct's public security master.

ICICI's Breeze API names a position by ICICI's own stock code (SONBLW, CNXBAN), never the NSE symbol (SONACOMS,
BANKNIFTY). ICICI publishes the mapping in its security master:
    https://directlink.icicidirect.com/NewSecurityMaster/SecurityMaster.zip
    NSEScripMaster.txt    ShortName (ICICI code) -> ExchangeCode (NSE symbol), ISINCode, Series
    FONSEScripMaster.txt  ShortName -> ExchangeCode for every F&O underlying (an index as its index name)

Usage (download the zip yourself, into a directory of its own):
    python -I scripts/build_icici_symbol_map.py /path/to/SecurityMaster.zip

Writes one row per ICICI code: broker_code, nse_symbol, isin, segment ("fno" when the code has F&O contracts,
else "equity"). A code that maps to two NSE symbols is dropped and printed: an ambiguous code is never guessed.
"""
from __future__ import annotations

import csv
import io
import sys
import zipfile
from datetime import date
from pathlib import Path
from typing import Dict, Iterator, Set

OUT = Path(__file__).resolve().parents[1] / "data" / "broker_symbols" / "icicidirect.csv"
SOURCE = "https://directlink.icicidirect.com/NewSecurityMaster/SecurityMaster.zip"
EQUITY_SERIES = {"EQ", "BE", "BZ", "SM", "ST"}

# ICICI's F&O master names an index underlying by its index name; NSE's F&O symbol is different.
INDEX_FNO_SYMBOL = {
    "NIFTY 50": "NIFTY",
    "NIFTY BANK": "BANKNIFTY",
    "NIFTY FINANCIAL": "FINNIFTY",
    "NIFTY MIDCAP": "MIDCPNIFTY",
    "NIFTY NEXT 50": "NIFTYNXT50",
}


def _rows(z: zipfile.ZipFile, name: str) -> Iterator[Dict[str, str]]:
    with z.open(name) as f:
        reader = csv.reader(io.TextIOWrapper(f, "utf-8", errors="replace"), skipinitialspace=True)
        head = [h.strip() for h in next(reader)]
        for row in reader:
            yield {k: (v or "").strip() for k, v in zip(head, row)}


def build(zip_path: Path) -> Dict[str, Dict[str, str]]:
    z = zipfile.ZipFile(zip_path)
    fno: Dict[str, Set[str]] = {}
    for d in _rows(z, "FONSEScripMaster.txt"):
        code, nse = d.get("ShortName", "").upper(), d.get("ExchangeCode", "").upper()
        if code and nse:
            fno.setdefault(code, set()).add(INDEX_FNO_SYMBOL.get(nse, nse))
    equity: Dict[str, Set[str]] = {}
    isin: Dict[str, str] = {}
    for d in _rows(z, "NSEScripMaster.txt"):
        if d.get("Series") not in EQUITY_SERIES:
            continue
        code, nse = d.get("ShortName", "").upper(), d.get("ExchangeCode", "").upper()
        if code and nse:
            equity.setdefault(code, set()).add(nse)
            if d.get("ISINCode"):
                isin.setdefault(code, d["ISINCode"].upper())
    out: Dict[str, Dict[str, str]] = {}
    for code in sorted(set(fno) | set(equity)):
        names = fno.get(code) or equity.get(code) or set()
        if len(names) != 1:
            print(f"ambiguous, dropped: {code} -> {sorted(names)}")
            continue
        out[code] = {"broker_code": code, "nse_symbol": names.pop(), "isin": isin.get(code, ""),
                     "segment": "fno" if code in fno else "equity"}
    return out


def main(argv: list) -> int:
    if len(argv) != 2:
        print(__doc__)
        return 2
    rows = build(Path(argv[1]))
    OUT.parent.mkdir(parents=True, exist_ok=True)
    with OUT.open("w", newline="") as f:
        f.write(f"# ICICI Direct stock code -> NSE symbol. Source: {SOURCE}, read {date.today().isoformat()}. "
                f"Built by backend/scripts/build_icici_symbol_map.py.\n")
        w = csv.DictWriter(f, fieldnames=["broker_code", "nse_symbol", "isin", "segment"])
        w.writeheader()
        w.writerows(rows.values())
    print(f"wrote {len(rows)} codes ({sum(1 for r in rows.values() if r['segment'] == 'fno')} with F&O) to {OUT}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
