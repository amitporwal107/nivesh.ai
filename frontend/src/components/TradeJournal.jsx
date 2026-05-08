/**
 * TradeJournal — log positional trades with staged entries + exit ladder.
 *
 * Per the user's BTST framework:
 *   • Staged entry plan (PILOT 20 / CONFIRM 30 / SUSTAIN 30 / MOMENTUM 20%)
 *   • Exit ladder (+5% cover hedge, +8-10% book 25%, +12-15% book 25%, trail rest)
 *   • Live LTP + P&L
 *   • Hedge guidance (Nifty PE lots) when gross long > ₹2L
 *
 * Endpoints:
 *   GET    /api/positional/journal?live=true
 *   POST   /api/positional/journal
 *   POST   /api/positional/journal/{id}/fill
 *   POST   /api/positional/journal/{id}/close
 *   GET    /api/positional/journal/summary/portfolio
 */
import React, { useEffect, useMemo, useState } from "react";
import axios from "axios";
import {
  BookOpen, Plus, X, Shield, TrendingUp, TrendingDown, ChevronDown, ChevronRight,
  CheckCircle2, AlertTriangle,
} from "lucide-react";
import { toast } from "sonner";
import { Button } from "@/components/ui/button";

const BACKEND_URL = process.env.REACT_APP_BACKEND_URL;
const API = `${BACKEND_URL}/api`;

const fmtINR = (n) => {
  if (n === null || n === undefined) return "—";
  return `₹${Number(n).toLocaleString("en-IN", { maximumFractionDigits: 2 })}`;
};

const STATUS_STYLE = {
  OPEN:    "bg-emerald-100 text-emerald-700 dark:bg-emerald-900/40 dark:text-emerald-300",
  CLOSED:  "bg-slate-200 text-slate-700 dark:bg-slate-700 dark:text-slate-300",
  STOPPED: "bg-rose-100 text-rose-700 dark:bg-rose-900/40 dark:text-rose-300",
};

const STAGE_PCT = { PILOT: 20, CONFIRM: 30, SUSTAIN: 30, MOMENTUM: 20 };


/** Inline form to add a fill (entry / exit) at a given stage. */
const FillForm = ({ tradeId, defaultStage, onAdded, onCancel }) => {
  const [qty, setQty] = useState("");
  const [price, setPrice] = useState("");
  const [kind, setKind] = useState("ENTRY");
  const [stage, setStage] = useState(defaultStage || "PILOT");
  const [busy, setBusy] = useState(false);

  const submit = async (e) => {
    e.preventDefault();
    if (!qty || !price) return toast.error("qty + price required");
    setBusy(true);
    try {
      const r = await axios.post(`${API}/positional/journal/${tradeId}/fill`,
        { stage, qty: Number(qty), price: Number(price), kind },
        { withCredentials: true },
      );
      toast.success(`${kind} logged: ${qty} @ ₹${price}`);
      onAdded?.(r.data);
      setQty(""); setPrice("");
    } catch (err) {
      toast.error(err?.response?.data?.detail || "Failed to add fill");
    } finally {
      setBusy(false);
    }
  };

  return (
    <form onSubmit={submit} className="grid grid-cols-2 sm:grid-cols-5 gap-2 text-xs" data-testid={`fill-form-${tradeId}`}>
      <select value={kind} onChange={(e) => setKind(e.target.value)} className="border rounded-md px-2 py-1 dark:bg-slate-800 dark:border-slate-700">
        <option value="ENTRY">Entry</option>
        <option value="EXIT">Exit</option>
      </select>
      <select value={stage} onChange={(e) => setStage(e.target.value)} className="border rounded-md px-2 py-1 dark:bg-slate-800 dark:border-slate-700">
        {["PILOT", "CONFIRM", "SUSTAIN", "MOMENTUM"].map((s) => <option key={s}>{s}</option>)}
      </select>
      <input value={qty} onChange={(e) => setQty(e.target.value)} type="number" step="any" placeholder="qty" className="border rounded-md px-2 py-1 dark:bg-slate-800 dark:border-slate-700" data-testid={`fill-qty-${tradeId}`} />
      <input value={price} onChange={(e) => setPrice(e.target.value)} type="number" step="any" placeholder="price" className="border rounded-md px-2 py-1 dark:bg-slate-800 dark:border-slate-700" data-testid={`fill-price-${tradeId}`} />
      <div className="flex gap-1">
        <Button type="submit" size="sm" disabled={busy} className="text-[11px] h-7 bg-emerald-600 hover:bg-emerald-700 text-white" data-testid={`fill-submit-${tradeId}`}>
          {busy ? "…" : "Log"}
        </Button>
        {onCancel && (
          <Button type="button" size="sm" variant="ghost" onClick={onCancel} className="text-[11px] h-7"><X className="w-3 h-3"/></Button>
        )}
      </div>
    </form>
  );
};


const TradeRow = ({ trade, onChanged }) => {
  const [open, setOpen] = useState(false);
  const [showFill, setShowFill] = useState(false);
  const [details, setDetails] = useState(null);
  const [loadingDetails, setLoadingDetails] = useState(false);

  const expand = async () => {
    setOpen(!open);
    if (!open && !details) {
      setLoadingDetails(true);
      try {
        const r = await axios.get(`${API}/positional/journal/${trade._id}?live=true`, { withCredentials: true });
        setDetails(r.data);
      } catch (e) {
        // soft fail
      } finally {
        setLoadingDetails(false);
      }
    }
  };

  const close = async (status) => {
    if (!window.confirm(`Mark ${trade.nse_symbol} as ${status}?`)) return;
    try {
      await axios.post(`${API}/positional/journal/${trade._id}/close`,
        { status }, { withCredentials: true });
      toast.success(`${trade.nse_symbol} marked ${status}`);
      onChanged?.();
    } catch (e) {
      toast.error(e?.response?.data?.detail || "Close failed");
    }
  };

  const pnl = trade.pnl || {};
  const pnlTone = pnl.total_pnl_rs > 0 ? "text-emerald-600" : pnl.total_pnl_rs < 0 ? "text-rose-500" : "text-slate-500";
  const ltp = trade.live_price;

  return (
    <div className="rounded-xl bg-white dark:bg-slate-800 border border-slate-100 dark:border-slate-700" data-testid={`journal-row-${trade.nse_symbol}`}>
      <div className="flex items-center gap-3 p-3">
        <button onClick={expand} className="text-slate-400 hover:text-slate-700 dark:hover:text-slate-200">
          {open ? <ChevronDown className="w-4 h-4"/> : <ChevronRight className="w-4 h-4"/>}
        </button>
        <div className="flex-1 min-w-0">
          <div className="flex items-center gap-2">
            <span className="font-semibold text-slate-900 dark:text-white">{trade.nse_symbol}</span>
            <span className={`text-[10px] uppercase tracking-wide px-1.5 py-0.5 rounded ${STATUS_STYLE[trade.status]}`}>
              {trade.status}
            </span>
            {trade.next_stage && trade.status === "OPEN" && (
              <span className="text-[10px] text-indigo-600 dark:text-indigo-400 font-medium" title="Next staged entry">
                next: {trade.next_stage}
              </span>
            )}
          </div>
          <div className="text-[11px] text-slate-500 dark:text-slate-400 mt-0.5">
            cap {fmtINR(trade.capital_alloc_rs)} · invested {fmtINR(pnl.invested_rs)} ({pnl.deployed_pct}%)
            {pnl.held_qty > 0 && <> · holding {pnl.held_qty} @ {fmtINR(pnl.avg_buy)}</>}
          </div>
        </div>
        <div className="text-right">
          <div className="text-sm tabular-nums text-slate-700 dark:text-slate-200">
            {ltp ? fmtINR(ltp) : "—"}
          </div>
          <div className={`text-[11px] tabular-nums font-semibold ${pnlTone}`}>
            {pnl.total_pnl_rs >= 0 ? "+" : ""}{fmtINR(pnl.total_pnl_rs)} ({pnl.total_pnl_pct >= 0 ? "+" : ""}{pnl.total_pnl_pct?.toFixed(1)}%)
          </div>
        </div>
        {trade.status === "OPEN" && (
          <Button size="sm" variant="outline" onClick={() => setShowFill((s) => !s)} className="text-[11px] h-7" data-testid={`fill-toggle-${trade.nse_symbol}`}>
            <Plus className="w-3 h-3 mr-1"/> Fill
          </Button>
        )}
      </div>

      {showFill && trade.status === "OPEN" && (
        <div className="px-3 pb-3 -mt-1">
          <FillForm
            tradeId={trade._id}
            defaultStage={trade.next_stage || "PILOT"}
            onAdded={() => { setShowFill(false); onChanged?.(); }}
            onCancel={() => setShowFill(false)}
          />
        </div>
      )}

      {open && (
        <div className="border-t border-slate-100 dark:border-slate-700 p-3 space-y-3">
          {loadingDetails && <div className="text-xs text-slate-400">Loading…</div>}

          {details && (
            <>
              {/* Stage plan */}
              <div>
                <div className="text-[10px] uppercase tracking-wider text-slate-400 mb-1.5">Staged entry plan</div>
                <div className="grid grid-cols-2 sm:grid-cols-4 gap-1.5">
                  {(details.stage_plan || []).map((s) => (
                    <div key={s.stage} className={`rounded-lg p-2 text-[11px] border ${
                      s.filled
                        ? "bg-emerald-50 dark:bg-emerald-900/20 border-emerald-200 dark:border-emerald-800"
                        : "bg-slate-50 dark:bg-slate-900/30 border-slate-200 dark:border-slate-700"
                    }`}>
                      <div className="flex items-center justify-between">
                        <span className="font-bold text-slate-700 dark:text-slate-200">{s.stage}</span>
                        <span className="text-[10px] text-slate-400">{s.alloc_pct}%</span>
                      </div>
                      <div className="text-[10px] text-slate-500 mt-0.5">{fmtINR(s.alloc_rs)}</div>
                      <div className="text-[10px] text-slate-400 mt-1 leading-tight">{s.trigger}</div>
                      {s.filled && s.fill && (
                        <div className="text-[10px] text-emerald-700 dark:text-emerald-400 mt-1 inline-flex items-center gap-1">
                          <CheckCircle2 className="w-3 h-3"/> {s.fill.qty} @ {fmtINR(s.fill.price)}
                        </div>
                      )}
                    </div>
                  ))}
                </div>
              </div>

              {/* Exit ladder */}
              {details.exit_ladder?.length > 0 && (
                <div>
                  <div className="text-[10px] uppercase tracking-wider text-slate-400 mb-1.5">Exit ladder</div>
                  <div className="grid grid-cols-2 sm:grid-cols-4 gap-1.5">
                    {details.exit_ladder.map((lv) => (
                      <div key={lv.name} className={`rounded-lg p-2 text-[11px] border ${
                        lv.status === "HIT"
                          ? "bg-emerald-50 dark:bg-emerald-900/20 border-emerald-200 dark:border-emerald-800"
                          : "bg-slate-50 dark:bg-slate-900/30 border-slate-200 dark:border-slate-700"
                      }`}>
                        <div className="flex items-center justify-between">
                          <span className="font-bold text-slate-700 dark:text-slate-200">{lv.name}</span>
                          {lv.trigger_price && <span className="text-[10px] text-slate-500 tabular-nums">{fmtINR(lv.trigger_price)}</span>}
                        </div>
                        <div className="text-[10px] text-slate-500 mt-1 leading-tight">{lv.action}</div>
                        {lv.status && (
                          <div className={`text-[10px] mt-1 font-medium ${lv.status === "HIT" ? "text-emerald-700 dark:text-emerald-400" : "text-slate-400"}`}>
                            {lv.status}
                          </div>
                        )}
                      </div>
                    ))}
                  </div>
                </div>
              )}

              {/* Fills log */}
              {details.fills?.length > 0 && (
                <div>
                  <div className="text-[10px] uppercase tracking-wider text-slate-400 mb-1.5">Fill log</div>
                  <div className="space-y-0.5 text-[11px]">
                    {details.fills.map((f, i) => (
                      <div key={f.id || i} className="flex items-center gap-2 text-slate-600 dark:text-slate-300">
                        <span className={`px-1.5 py-0.5 rounded text-[9px] ${f.kind === "ENTRY" ? "bg-emerald-100 text-emerald-700" : "bg-rose-100 text-rose-700"}`}>{f.kind}</span>
                        <span className="font-medium w-16">{f.stage}</span>
                        <span className="tabular-nums">{f.qty} @ {fmtINR(f.price)}</span>
                        <span className="text-slate-400 text-[10px] ml-auto">{(f.at || "").slice(0, 10)}</span>
                      </div>
                    ))}
                  </div>
                </div>
              )}

              {/* Close actions */}
              {trade.status === "OPEN" && (
                <div className="flex gap-2 pt-2 border-t border-slate-100 dark:border-slate-700">
                  <Button size="sm" variant="outline" onClick={() => close("CLOSED")} className="text-[11px] h-7" data-testid={`close-trade-${trade.nse_symbol}`}>Close trade</Button>
                  <Button size="sm" variant="outline" onClick={() => close("STOPPED")} className="text-[11px] h-7 text-rose-600 hover:text-rose-700" data-testid={`stop-trade-${trade.nse_symbol}`}>Stopped out</Button>
                </div>
              )}
            </>
          )}
        </div>
      )}
    </div>
  );
};


const NewTradeForm = ({ onCreated, onCancel }) => {
  const [sym, setSym] = useState("");
  const [cap, setCap] = useState("");
  const [sl, setSl] = useState("");
  const [tgt, setTgt] = useState("");
  const [busy, setBusy] = useState(false);

  const submit = async (e) => {
    e.preventDefault();
    if (!sym || !cap) return toast.error("Symbol + capital required");
    setBusy(true);
    try {
      await axios.post(`${API}/positional/journal`, {
        nse_symbol: sym.toUpperCase(),
        capital_alloc_rs: Number(cap),
        stop_loss: Number(sl) || 0,
        target: Number(tgt) || 0,
        plan_source: "MANUAL",
      }, { withCredentials: true });
      toast.success(`Trade journal opened for ${sym.toUpperCase()}`);
      onCreated?.();
    } catch (err) {
      toast.error(err?.response?.data?.detail || "Failed to create trade");
    } finally {
      setBusy(false);
    }
  };

  return (
    <form onSubmit={submit} className="grid grid-cols-2 sm:grid-cols-5 gap-2 text-xs bg-slate-50 dark:bg-slate-900/40 rounded-xl p-3" data-testid="new-trade-form">
      <input value={sym} onChange={(e) => setSym(e.target.value)} placeholder="NSE Symbol (e.g. PETRONET)" className="border rounded-md px-2 py-1.5 dark:bg-slate-800 dark:border-slate-700 col-span-2" data-testid="new-trade-symbol" />
      <input value={cap} onChange={(e) => setCap(e.target.value)} type="number" step="any" placeholder="Capital ₹" className="border rounded-md px-2 py-1.5 dark:bg-slate-800 dark:border-slate-700" data-testid="new-trade-capital" />
      <input value={sl} onChange={(e) => setSl(e.target.value)} type="number" step="any" placeholder="SL ₹" className="border rounded-md px-2 py-1.5 dark:bg-slate-800 dark:border-slate-700" />
      <input value={tgt} onChange={(e) => setTgt(e.target.value)} type="number" step="any" placeholder="Target ₹" className="border rounded-md px-2 py-1.5 dark:bg-slate-800 dark:border-slate-700" />
      <Button type="submit" disabled={busy} size="sm" className="text-xs h-8 bg-emerald-600 hover:bg-emerald-700 text-white col-span-1" data-testid="new-trade-submit">{busy ? "…" : "Open Trade"}</Button>
      {onCancel && <Button type="button" variant="ghost" size="sm" onClick={onCancel} className="text-xs h-8 col-span-1">Cancel</Button>}
    </form>
  );
};


export default function TradeJournal() {
  const [trades, setTrades] = useState([]);
  const [summary, setSummary] = useState(null);
  const [loading, setLoading] = useState(true);
  const [showNew, setShowNew] = useState(false);
  const [filter, setFilter] = useState("OPEN");

  const load = async () => {
    setLoading(true);
    try {
      const [t, s] = await Promise.all([
        axios.get(`${API}/positional/journal?live=true`, { withCredentials: true }),
        axios.get(`${API}/positional/journal/summary/portfolio`, { withCredentials: true }),
      ]);
      setTrades(t.data?.trades || []);
      setSummary(s.data);
    } catch (e) {
      // soft fail
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => { load(); }, []);

  const filteredTrades = useMemo(() => {
    if (filter === "ALL") return trades;
    return trades.filter((t) => t.status === filter);
  }, [trades, filter]);

  return (
    <div data-testid="trade-journal-section" className="space-y-3">
      {/* Summary strip */}
      {summary && (
        <div className="grid grid-cols-2 sm:grid-cols-4 gap-2">
          <div className="rounded-xl bg-white dark:bg-slate-800 border border-slate-100 dark:border-slate-700 p-3" data-testid="journal-tile-open">
            <div className="text-[10px] uppercase tracking-wider text-slate-400">Open Trades</div>
            <div className="text-lg font-bold mt-1 text-slate-900 dark:text-white tabular-nums">{summary.open_count}</div>
          </div>
          <div className="rounded-xl bg-white dark:bg-slate-800 border border-slate-100 dark:border-slate-700 p-3" data-testid="journal-tile-gross-long">
            <div className="text-[10px] uppercase tracking-wider text-slate-400">Gross Long</div>
            <div className="text-lg font-bold mt-1 text-slate-900 dark:text-white tabular-nums">{fmtINR(summary.gross_long_rs)}</div>
          </div>
          <div className="rounded-xl bg-white dark:bg-slate-800 border border-slate-100 dark:border-slate-700 p-3" data-testid="journal-tile-realized">
            <div className="text-[10px] uppercase tracking-wider text-slate-400">Realized P&amp;L</div>
            <div className={`text-lg font-bold mt-1 tabular-nums ${summary.realized_pnl_rs > 0 ? "text-emerald-600" : summary.realized_pnl_rs < 0 ? "text-rose-500" : "text-slate-700 dark:text-slate-200"}`}>
              {summary.realized_pnl_rs >= 0 ? "+" : ""}{fmtINR(summary.realized_pnl_rs)}
            </div>
          </div>
          <div className="rounded-xl bg-white dark:bg-slate-800 border border-slate-100 dark:border-slate-700 p-3" data-testid="journal-tile-winrate">
            <div className="text-[10px] uppercase tracking-wider text-slate-400">Win Rate</div>
            <div className="text-lg font-bold mt-1 text-slate-900 dark:text-white tabular-nums">
              {summary.win_rate_pct === null ? "—" : `${summary.win_rate_pct}%`}
            </div>
            <div className="text-[10px] text-slate-400">{summary.win_count}W · {summary.loss_count}L</div>
          </div>
        </div>
      )}

      {/* Hedge guidance */}
      {summary?.needs_hedge && summary.suggested_hedge && (
        <div className="rounded-xl bg-amber-50 dark:bg-amber-900/20 border border-amber-200 dark:border-amber-800/50 p-3 flex items-start gap-2" data-testid="hedge-guidance">
          <Shield className="w-4 h-4 text-amber-600 flex-shrink-0 mt-0.5" />
          <div className="text-xs text-amber-800 dark:text-amber-200">
            <div className="font-semibold">Hedge suggested · {summary.suggested_hedge.lots} lot{summary.suggested_hedge.lots > 1 ? "s" : ""} {summary.suggested_hedge.instrument}</div>
            <div className="text-[11px] opacity-80 mt-0.5">{summary.suggested_hedge.rationale}</div>
          </div>
        </div>
      )}

      {/* Header + filters */}
      <div className="flex items-center justify-between flex-wrap gap-2">
        <div className="inline-flex rounded-lg border border-slate-200 dark:border-slate-700 overflow-hidden text-[11px]">
          {["OPEN", "CLOSED", "ALL"].map((f) => (
            <button
              key={f}
              type="button"
              onClick={() => setFilter(f)}
              className={`px-3 py-1 ${filter === f ? "bg-emerald-50 text-emerald-700 dark:bg-emerald-900/40 dark:text-emerald-300" : "text-slate-500 hover:text-slate-700"}`}
              data-testid={`journal-filter-${f}`}
            >
              {f}
            </button>
          ))}
        </div>
        <Button size="sm" onClick={() => setShowNew((s) => !s)} className="text-xs bg-emerald-600 hover:bg-emerald-700 text-white" data-testid="new-trade-toggle">
          <Plus className="w-3 h-3 mr-1"/> New Trade
        </Button>
      </div>

      {showNew && (
        <NewTradeForm onCreated={() => { setShowNew(false); load(); }} onCancel={() => setShowNew(false)} />
      )}

      {/* Trade rows */}
      {loading && <div className="text-xs text-slate-400">Loading journal…</div>}
      {!loading && filteredTrades.length === 0 && (
        <div className="rounded-xl border border-dashed border-slate-200 dark:border-slate-700 p-6 text-center text-xs text-slate-500 dark:text-slate-400" data-testid="journal-empty">
          <BookOpen className="w-6 h-6 mx-auto mb-2 text-slate-300 dark:text-slate-600" />
          {filter === "OPEN"
            ? "No open trades. Click New Trade to log your first staged entry."
            : `No ${filter.toLowerCase()} trades.`}
        </div>
      )}
      {!loading && filteredTrades.length > 0 && (
        <div className="space-y-2">
          {filteredTrades.map((t) => (
            <TradeRow key={t._id} trade={t} onChanged={load} />
          ))}
        </div>
      )}
    </div>
  );
}
