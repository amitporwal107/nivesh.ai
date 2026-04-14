import React, { useState, useMemo } from "react";
import { X, Search, ArrowUpDown } from "lucide-react";
import { Dialog, DialogContent, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { useNumberFormat } from "@/context/NumberFormatContext";

const ASSET_LABELS = { equity: "Equity", mutual_fund: "MF", etf: "ETF", bond: "Bond", gold: "Gold", fd: "FD", other: "Other" };

const DrilldownModal = ({ open, onClose, title, holdings }) => {
  const { fmt } = useNumberFormat();
  const [search, setSearch] = useState("");
  const [sortField, setSortField] = useState("value");
  const [sortDir, setSortDir] = useState("desc");

  const filtered = useMemo(() => {
    let list = (holdings || []).map(h => {
      const inv = h.quantity * h.buy_price;
      const cur = h.quantity * h.current_price;
      return { ...h, invested: inv, value: cur, pnl: cur - inv, pnl_pct: inv > 0 ? ((cur - inv) / inv * 100) : 0 };
    });
    if (search) {
      const q = search.toLowerCase();
      list = list.filter(h => h.name.toLowerCase().includes(q) || (h.ticker || "").toLowerCase().includes(q) || (h.sector || "").toLowerCase().includes(q));
    }
    list.sort((a, b) => {
      const va = sortField === "name" ? a.name.toLowerCase() : a[sortField];
      const vb = sortField === "name" ? b.name.toLowerCase() : b[sortField];
      return sortDir === "asc" ? (va > vb ? 1 : -1) : (va < vb ? 1 : -1);
    });
    return list;
  }, [holdings, search, sortField, sortDir]);

  const toggle = (f) => {
    if (sortField === f) setSortDir(d => d === "asc" ? "desc" : "asc");
    else { setSortField(f); setSortDir("desc"); }
  };

  const totalValue = filtered.reduce((s, h) => s + h.value, 0);
  const totalPnl = filtered.reduce((s, h) => s + h.pnl, 0);

  return (
    <Dialog open={open} onOpenChange={onClose}>
      <DialogContent className="sm:max-w-4xl max-h-[85vh] overflow-hidden rounded-2xl flex flex-col">
        <DialogHeader>
          <DialogTitle className="text-xl font-medium text-slate-900 dark:text-white" style={{ fontFamily: "'Outfit', sans-serif" }}>
            {title} <span className="text-sm text-slate-400 font-normal ml-2">{filtered.length} holdings &middot; {fmt(totalValue)}</span>
          </DialogTitle>
        </DialogHeader>
        <div className="relative mt-2">
          <Search className="w-4 h-4 absolute left-3 top-1/2 -translate-y-1/2 text-slate-400" />
          <Input data-testid="drilldown-search" value={search} onChange={e => setSearch(e.target.value)} placeholder="Search by name, ticker, sector..." className="pl-10 rounded-xl" />
        </div>
        <div className="flex-1 overflow-auto mt-3">
          <Table>
            <TableHeader>
              <TableRow className="border-slate-100 dark:border-slate-700">
                <TableHead className="text-[10px] font-bold tracking-wider uppercase text-slate-400 cursor-pointer" onClick={() => toggle("name")}>Name</TableHead>
                <TableHead className="text-[10px] font-bold tracking-wider uppercase text-slate-400">Type</TableHead>
                <TableHead className="text-[10px] font-bold tracking-wider uppercase text-slate-400 cursor-pointer" onClick={() => toggle("quantity")}>Qty</TableHead>
                <TableHead className="text-[10px] font-bold tracking-wider uppercase text-slate-400">Buy</TableHead>
                <TableHead className="text-[10px] font-bold tracking-wider uppercase text-slate-400">CMP</TableHead>
                <TableHead className="text-[10px] font-bold tracking-wider uppercase text-slate-400 cursor-pointer" onClick={() => toggle("value")}>Value</TableHead>
                <TableHead className="text-[10px] font-bold tracking-wider uppercase text-slate-400 cursor-pointer" onClick={() => toggle("pnl_pct")}>P&L</TableHead>
                <TableHead className="text-[10px] font-bold tracking-wider uppercase text-slate-400">Sector</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {filtered.map(h => {
                const pos = h.pnl >= 0;
                return (
                  <TableRow key={h.holding_id} className="border-slate-50 dark:border-slate-700/50">
                    <TableCell className="py-2.5">
                      <p className="text-sm font-medium text-slate-900 dark:text-white">{h.name}</p>
                      {h.ticker && <p className="text-[10px] text-slate-400">{h.ticker}</p>}
                    </TableCell>
                    <TableCell><span className="text-[10px] font-medium bg-slate-100 dark:bg-slate-700 text-slate-600 dark:text-slate-300 px-1.5 py-0.5 rounded-full">{ASSET_LABELS[h.asset_type] || h.asset_type}</span></TableCell>
                    <TableCell className="text-sm text-slate-700 dark:text-slate-300">{h.quantity.toLocaleString(undefined, { maximumFractionDigits: 3 })}</TableCell>
                    <TableCell className="text-sm text-slate-600 dark:text-slate-400">₹{h.buy_price.toLocaleString()}</TableCell>
                    <TableCell className="text-sm text-slate-700 dark:text-slate-300">₹{h.current_price.toLocaleString()}</TableCell>
                    <TableCell className="text-sm font-medium text-slate-900 dark:text-white">{fmt(h.value)}</TableCell>
                    <TableCell>
                      <p className={`text-sm font-medium ${pos ? "text-emerald-600" : "text-red-500"}`}>{pos ? "+" : ""}{h.pnl_pct.toFixed(1)}%</p>
                      <p className={`text-[10px] ${pos ? "text-emerald-500" : "text-red-400"}`}>{pos ? "+" : ""}{fmt(Math.abs(h.pnl))}</p>
                    </TableCell>
                    <TableCell className="text-xs text-slate-500 dark:text-slate-400">{h.sector}</TableCell>
                  </TableRow>
                );
              })}
            </TableBody>
          </Table>
        </div>
        <div className="flex items-center justify-between pt-3 border-t border-slate-100 dark:border-slate-700 text-xs text-slate-400">
          <span>{filtered.length} holdings</span>
          <span className={totalPnl >= 0 ? "text-emerald-600" : "text-red-500"}>Total P&L: {totalPnl >= 0 ? "+" : ""}{fmt(Math.abs(totalPnl))}</span>
        </div>
      </DialogContent>
    </Dialog>
  );
};

export default DrilldownModal;
