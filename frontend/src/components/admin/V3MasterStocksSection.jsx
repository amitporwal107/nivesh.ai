import React, { useEffect, useState } from "react";
import axios from "axios";
import { RefreshCw, TrendingUp, TrendingDown, Minus } from "lucide-react";
import { Button } from "@/components/ui/button";

const API = `${process.env.REACT_APP_BACKEND_URL}/api`;

const RECO_STYLE = {
  BUY:    { color: "bg-emerald-100 text-emerald-800", icon: TrendingUp },
  HOLD:   { color: "bg-slate-100 text-slate-800",     icon: Minus },
  TRIM:   { color: "bg-amber-100 text-amber-800",     icon: TrendingDown },
  EXIT:   { color: "bg-rose-100 text-rose-800",       icon: TrendingDown },
  REVIEW: { color: "bg-indigo-100 text-indigo-800",   icon: Minus },
};

const ScoreCell = ({ value }) => {
  if (value == null) return <span className="text-slate-400">—</span>;
  const color = value >= 70 ? "text-emerald-700" : value >= 50 ? "text-amber-700" : "text-rose-700";
  return <span className={`font-mono font-semibold ${color}`}>{Math.round(value)}</span>;
};

export default function V3MasterStocksSection() {
  const [rows, setRows] = useState(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);
  const [nifty100Only, setNifty100Only] = useState(true);

  const load = async () => {
    setLoading(true);
    setError(null);
    try {
      const res = await axios.get(`${API}/admin/v3-stock-master`, {
        params: { nifty_100_only: nifty100Only, limit: 200 },
        withCredentials: true,
      });
      setRows(res.data.funds || []);
    } catch (e) {
      setError(e.response?.data?.detail || e.message);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => { load(); /* eslint-disable-next-line react-hooks/exhaustive-deps */ }, [nifty100Only]);

  return (
    <div className="space-y-4" data-testid="v3-stock-master-section">
      <div className="rounded-2xl border border-slate-200 bg-white p-4 flex items-center justify-between flex-wrap gap-3">
        <div>
          <h2 className="text-base font-semibold text-slate-900">V3 Stock Master — Equity Catalogue</h2>
          <p className="text-xs text-slate-500 mt-0.5">
            Scored direct equities with Quality / Health / Exit / Add composite scores. Nifty 100 by default; toggle to see the full scored universe.
          </p>
        </div>
        <div className="flex items-center gap-2">
          <label className="flex items-center gap-2 text-xs text-slate-700" data-testid="nifty100-toggle">
            <input type="checkbox" checked={nifty100Only} onChange={(e) => setNifty100Only(e.target.checked)} />
            Nifty 100 only
          </label>
          <Button size="sm" variant="outline" onClick={load} disabled={loading}>
            <RefreshCw className={`w-4 h-4 mr-1 ${loading ? "animate-spin" : ""}`} />Refresh
          </Button>
        </div>
      </div>

      {error && (
        <div className="rounded-xl border border-rose-200 bg-rose-50 p-3 text-sm text-rose-700" data-testid="stock-master-error">
          {error}
        </div>
      )}

      {rows && rows.length === 0 && !error && (
        <div className="rounded-xl border border-dashed border-slate-300 p-12 text-center text-sm text-slate-500" data-testid="stock-master-empty">
          <p className="font-semibold mb-1">No scored stocks yet.</p>
          <p>Equity scoring requires the Groww scraper and primitives persistence. Run the stock refresh pipeline to populate.</p>
        </div>
      )}

      {rows && rows.length > 0 && (
        <div className="rounded-2xl border border-slate-200 bg-white overflow-hidden" data-testid="stock-master-table">
          <div className="overflow-x-auto">
            <table className="min-w-full text-sm">
              <thead className="bg-slate-50 border-b border-slate-200">
                <tr className="text-left text-[11px] uppercase tracking-wider text-slate-500">
                  <th className="p-3">Symbol</th>
                  <th className="p-3">Company</th>
                  <th className="p-3">Sector</th>
                  <th className="p-3 text-right">Mkt Cap (Cr)</th>
                  <th className="p-3">Cap</th>
                  <th className="p-3 text-center">Quality</th>
                  <th className="p-3 text-center">Health</th>
                  <th className="p-3 text-center">Exit</th>
                  <th className="p-3 text-center">Add</th>
                  <th className="p-3">Action</th>
                </tr>
              </thead>
              <tbody>
                {rows.map((r) => {
                  const reco = r.recommendation?.action || r.recommendation || "REVIEW";
                  const recoStyle = RECO_STYLE[reco] || RECO_STYLE.REVIEW;
                  const RecoIcon = recoStyle.icon;
                  return (
                    <tr key={r.nse_symbol} className="border-b border-slate-100 hover:bg-slate-50" data-testid={`stock-row-${r.nse_symbol}`}>
                      <td className="p-3 font-mono font-semibold">{r.nse_symbol}</td>
                      <td className="p-3">{r.company_name}</td>
                      <td className="p-3 text-slate-600">{r.sector || "—"}</td>
                      <td className="p-3 text-right font-mono">{r.market_cap_cr != null ? Math.round(r.market_cap_cr).toLocaleString() : "—"}</td>
                      <td className="p-3 capitalize text-slate-600">{r.cap_bucket || "—"}</td>
                      <td className="p-3 text-center"><ScoreCell value={r.scores?.quality} /></td>
                      <td className="p-3 text-center"><ScoreCell value={r.scores?.health} /></td>
                      <td className="p-3 text-center"><ScoreCell value={r.scores?.exit} /></td>
                      <td className="p-3 text-center"><ScoreCell value={r.scores?.add} /></td>
                      <td className="p-3">
                        <span className={`inline-flex items-center gap-1 text-[11px] font-semibold px-2 py-0.5 rounded ${recoStyle.color}`}>
                          <RecoIcon className="w-3 h-3" />{reco}
                        </span>
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        </div>
      )}
    </div>
  );
}
