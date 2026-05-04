import React, { useEffect, useState } from "react";
import axios from "axios";
import { Globe, RefreshCw, AlertCircle, CheckCircle2, TrendingUp, Hourglass, XCircle, Info } from "lucide-react";

const API = `${process.env.REACT_APP_BACKEND_URL}/api`;

const fmtRs = (n) => {
  const v = Number(n) || 0;
  if (v >= 1e7) return `₹${(v / 1e7).toFixed(2)}Cr`;
  if (v >= 1e5) return `₹${(v / 1e5).toFixed(2)}L`;
  if (v >= 1000) return `₹${(v / 1000).toFixed(1)}k`;
  return `₹${Math.round(v).toLocaleString("en-IN")}`;
};
const fmtPct = (n, dp = 1) => n == null ? "—" : `${Number(n).toFixed(dp)}%`;

const BAND_TONES = {
  core: {
    title: "Core Allocation",
    subtitle: "Diversified default — start here",
    Icon: CheckCircle2,
    tone: "emerald",
    panel: "bg-emerald-50 border-emerald-200",
    pill: "bg-emerald-600 text-white",
    text: "text-emerald-900",
  },
  selective: {
    title: "Selective Buy",
    subtitle: "Strong but watch valuation / overlap",
    Icon: TrendingUp,
    tone: "amber",
    panel: "bg-amber-50 border-amber-200",
    pill: "bg-amber-500 text-white",
    text: "text-amber-900",
  },
  tactical: {
    title: "Tactical Buy",
    subtitle: "High growth · high risk · small slice only",
    Icon: Hourglass,
    tone: "indigo",
    panel: "bg-indigo-50 border-indigo-200",
    pill: "bg-indigo-600 text-white",
    text: "text-indigo-900",
  },
  avoid: {
    title: "Avoid for Now",
    subtitle: "Blocked by portfolio context or weak scores",
    Icon: XCircle,
    tone: "rose",
    panel: "bg-rose-50 border-rose-200",
    pill: "bg-rose-600 text-white",
    text: "text-rose-900",
  },
};

const BUCKET_BADGE = {
  US: { label: "US", className: "bg-blue-50 text-blue-700 border-blue-200" },
  Global: { label: "Global", className: "bg-emerald-50 text-emerald-700 border-emerald-200" },
  EM: { label: "Emerging", className: "bg-orange-50 text-orange-700 border-orange-200" },
  Tech: { label: "Tech", className: "bg-purple-50 text-purple-700 border-purple-200" },
};

export default function DiscoverInternationalView() {
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [error, setError] = useState(null);

  const load = async () => {
    setLoading(true);
    setError(null);
    try {
      const res = await axios.get(`${API}/portfolio/international-recommendations`, {
        withCredentials: true,
      });
      setData(res.data);
    } catch (e) {
      setError(e.response?.data?.detail || e.message || "Failed to load");
    } finally {
      setLoading(false);
    }
  };

  const refreshCache = async () => {
    setRefreshing(true);
    try {
      await axios.post(`${API}/portfolio/international-funds/refresh`, null, {
        withCredentials: true,
      });
      await load();
    } catch (e) {
      setError(e.response?.data?.detail || e.message || "Refresh failed");
    } finally {
      setRefreshing(false);
    }
  };

  useEffect(() => { load(); }, []); // load is stable — only run once on mount

  if (loading) {
    return (
      <div className="rounded-xl border border-slate-200 bg-white p-8 text-center text-slate-500">
        Computing your international fund recommendation…
      </div>
    );
  }
  if (error) {
    return (
      <div className="rounded-xl border border-rose-200 bg-rose-50 p-5 text-rose-800">
        <div className="flex items-center gap-2 font-semibold mb-1">
          <AlertCircle className="w-4 h-4" /> Couldn’t load recommendations
        </div>
        <div className="text-sm">{error}</div>
        <button
          onClick={load}
          className="mt-3 text-sm font-semibold underline underline-offset-2"
        >
          Try again
        </button>
      </div>
    );
  }
  if (!data) return null;

  const stale = data._stale;
  const target = data.target || {};
  const ctx = data.portfolio_context || {};
  const bands = data.bands || { core: [], selective: [], tactical: [], avoid: [] };
  const totalRecs = bands.core.length + bands.selective.length + bands.tactical.length;

  // ── Stale state — cache empty, prompt to refresh ─────────────────
  if (stale) {
    return (
      <div className="rounded-xl border-2 border-amber-200 bg-amber-50 p-6">
        <div className="flex items-start gap-3">
          <div className="w-10 h-10 rounded-lg bg-amber-100 text-amber-600 flex items-center justify-center flex-shrink-0">
            <Globe className="w-5 h-5" />
          </div>
          <div className="flex-1">
            <h3 className="text-lg font-bold text-amber-900">International fund cache is empty</h3>
            <p className="text-sm text-amber-800 mt-1">
              We need to scrape Groww once to populate fund primitives. This takes ~30 seconds and runs nightly afterwards.
            </p>
            <button
              onClick={refreshCache}
              disabled={refreshing}
              className="mt-3 inline-flex items-center gap-2 px-4 py-2 bg-amber-600 hover:bg-amber-700 text-white rounded-lg font-semibold text-sm disabled:opacity-50"
              data-testid="intl-refresh-cache"
            >
              <RefreshCw className={`w-4 h-4 ${refreshing ? "animate-spin" : ""}`} />
              {refreshing ? "Scraping Groww…" : "Refresh cache now"}
            </button>
          </div>
        </div>
      </div>
    );
  }

  return (
    <div className="space-y-4" data-testid="discover-international">
      {/* ── Hero: how much should I invest? ──────────────────────────── */}
      <HeroAllocation target={target} data={data} />

      {/* ── Portfolio context strip ─────────────────────────────────── */}
      <ContextStrip ctx={ctx} />

      {/* ── Recommendation bands ────────────────────────────────────── */}
      {totalRecs === 0 && bands.avoid.length === 0 && (
        <div className="rounded-xl border border-slate-200 bg-slate-50 p-6 text-center text-slate-500 text-sm">
          No international funds in the cache yet. Run the refresh.
        </div>
      )}

      {bands.core.length > 0 && (
        <BandSection
          band="core"
          funds={bands.core}
          allocationRs={data.split_rs?.core}
        />
      )}
      {bands.selective.length > 0 && (
        <BandSection
          band="selective"
          funds={bands.selective}
          allocationRs={data.split_rs?.selective}
        />
      )}
      {bands.tactical.length > 0 && (
        <BandSection
          band="tactical"
          funds={bands.tactical}
          allocationRs={data.split_rs?.tactical}
        />
      )}
      {bands.avoid.length > 0 && (
        <BandSection band="avoid" funds={bands.avoid} allocationRs={null} />
      )}

      {/* ── Footer: refresh action ──────────────────────────────────── */}
      <div className="flex justify-end">
        <button
          onClick={refreshCache}
          disabled={refreshing}
          className="inline-flex items-center gap-2 text-xs text-slate-500 hover:text-slate-700 disabled:opacity-50"
          data-testid="intl-refresh-footer"
        >
          <RefreshCw className={`w-3 h-3 ${refreshing ? "animate-spin" : ""}`} />
          {refreshing ? "Scraping Groww…" : "Refresh fund data"}
        </button>
      </div>
    </div>
  );
}

// ── Hero allocation ──────────────────────────────────────────────────
function HeroAllocation({ target, data }) {
  const targetPct = Number(data.target_pct ?? 0);
  const currentPct = Number(data.current_pct ?? 0);
  const targetRs = Number(data.target_rs ?? 0);
  const currentRs = Number(data.current_rs ?? 0);
  const gapRs = Number(data.gap_rs ?? 0);
  const gapPct = targetPct - currentPct;

  // Three states: (a) horizon < 3y → no exposure, (b) under-allocated, (c) at/over target
  if (targetPct === 0) {
    return (
      <div className="rounded-xl border-2 border-slate-200 bg-slate-50 p-5">
        <div className="flex items-start gap-3">
          <div className="w-10 h-10 rounded-lg bg-slate-100 text-slate-600 flex items-center justify-center">
            <Info className="w-5 h-5" />
          </div>
          <div className="flex-1">
            <h3 className="text-base font-bold text-slate-900">No international exposure recommended right now</h3>
            <ul className="mt-2 space-y-1 text-[13px] text-slate-700">
              {(target.rationale || []).map((r, i) => (
                <li key={i} className="flex items-start gap-1.5">
                  <span className="mt-1.5 w-1 h-1 rounded-full bg-slate-400 flex-shrink-0" />
                  <span>{r}</span>
                </li>
              ))}
            </ul>
          </div>
        </div>
      </div>
    );
  }

  const isUnder = gapPct >= 0.5;
  const isOver = gapPct <= -0.5;
  const tone = isUnder ? "emerald" : isOver ? "amber" : "slate";
  const headline = isUnder
    ? `Add ~${fmtRs(gapRs)} to international funds`
    : isOver
      ? "Already over target — hold what you have"
      : "You're at target international exposure";

  return (
    <div className={`rounded-xl border-2 px-5 py-4 ${
      tone === "emerald" ? "bg-gradient-to-br from-emerald-50 to-emerald-100/50 border-emerald-200" :
      tone === "amber"   ? "bg-gradient-to-br from-amber-50 to-amber-100/50 border-amber-200" :
                           "bg-slate-50 border-slate-200"
    }`}>
      <div className="flex items-start gap-3">
        <div className={`w-10 h-10 rounded-lg flex items-center justify-center ${
          tone === "emerald" ? "bg-emerald-100 text-emerald-600" :
          tone === "amber"   ? "bg-amber-100 text-amber-600" :
                               "bg-slate-100 text-slate-600"
        }`}>
          <Globe className="w-5 h-5" />
        </div>
        <div className="flex-1 min-w-0">
          <div className="text-[10px] font-bold uppercase tracking-wider text-slate-500">
            International allocation
          </div>
          <h3 className={`text-base font-bold mt-1 ${
            tone === "emerald" ? "text-emerald-900" :
            tone === "amber"   ? "text-amber-900" :
                                 "text-slate-900"
          }`}>{headline}</h3>
          <div className="mt-2 grid grid-cols-3 gap-3 text-[12.5px]">
            <Stat label="Target" value={`${targetPct.toFixed(1)}%`} sub={fmtRs(targetRs)} />
            <Stat label="Current" value={`${currentPct.toFixed(1)}%`} sub={fmtRs(currentRs)} />
            <Stat
              label={isOver ? "Over target" : "Gap"}
              value={`${Math.abs(gapPct).toFixed(1)}pp`}
              sub={fmtRs(Math.abs(gapRs))}
              emphasized={isUnder}
            />
          </div>
          {target.rationale?.length > 0 && (
            <ul className="mt-3 space-y-0.5 text-[11.5px] text-slate-600">
              {target.rationale.map((r, i) => (
                <li key={i} className="flex items-start gap-1.5">
                  <span className="mt-1.5 w-0.5 h-0.5 rounded-full bg-slate-400 flex-shrink-0" />
                  <span>{r}</span>
                </li>
              ))}
            </ul>
          )}
        </div>
      </div>
    </div>
  );
}

const Stat = ({ label, value, sub, emphasized }) => (
  <div>
    <div className="text-[10px] uppercase tracking-wider text-slate-500">{label}</div>
    <div className={`font-mono tabular-nums font-bold ${emphasized ? "text-emerald-700" : "text-slate-800"} text-base`}>
      {value}
    </div>
    {sub && <div className="text-[10.5px] text-slate-500 font-mono tabular-nums">{sub}</div>}
  </div>
);

// ── Portfolio context strip ──────────────────────────────────────────
function ContextStrip({ ctx }) {
  const items = [
    { label: "Risk profile", value: cap(ctx.risk_profile || "moderate") },
    {
      label: "Horizon",
      value: ctx.horizon_years != null ? `${Number(ctx.horizon_years).toFixed(0)}y` : "—",
    },
    {
      label: "US exposure",
      value: fmtPct(ctx.us_exposure_pct, 1),
      hint: ctx.us_exposure_pct > 20 ? "Already concentrated" : null,
    },
    {
      label: "IT concentration",
      value: fmtPct(ctx.it_concentration_pct, 1),
      hint: ctx.it_concentration_pct > 25 ? "Tech FoFs blocked" : null,
    },
  ];
  return (
    <div className="rounded-xl border border-slate-200 bg-white px-4 py-3">
      <div className="text-[10px] uppercase tracking-wider font-bold text-slate-500 mb-2">
        Your portfolio context
      </div>
      <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
        {items.map((it) => (
          <div key={it.label}>
            <div className="text-[10.5px] text-slate-500">{it.label}</div>
            <div className="text-sm font-semibold text-slate-800 font-mono tabular-nums">
              {it.value}
            </div>
            {it.hint && (
              <div className="text-[10px] text-rose-600 font-medium mt-0.5">{it.hint}</div>
            )}
          </div>
        ))}
      </div>
    </div>
  );
}

const cap = (s) => s ? s[0].toUpperCase() + s.slice(1) : s;

// ── Band section (Core / Selective / Tactical / Avoid) ────────────────
function BandSection({ band, funds, allocationRs }) {
  const t = BAND_TONES[band];
  const Icon = t.Icon;
  const showAlloc = band !== "avoid" && allocationRs != null && allocationRs > 0;
  return (
    <div className={`rounded-xl border-2 ${t.panel}`} data-testid={`band-${band}`}>
      <div className="px-5 py-3 flex items-center justify-between gap-3 border-b border-current/10">
        <div className="flex items-center gap-3 min-w-0">
          <div className="w-9 h-9 rounded-lg bg-white/60 flex items-center justify-center">
            <Icon className={`w-4 h-4 ${t.text}`} strokeWidth={2} />
          </div>
          <div className="min-w-0">
            <div className={`text-[10px] uppercase tracking-wider font-bold inline-block px-2 py-0.5 rounded ${t.pill}`}>
              {t.title}
            </div>
            <div className={`text-xs ${t.text} mt-0.5`}>{t.subtitle}</div>
          </div>
        </div>
        {showAlloc && (
          <div className="text-right flex-shrink-0">
            <div className="text-[10px] uppercase tracking-wider text-slate-500">Suggested ₹</div>
            <div className={`font-mono tabular-nums font-bold text-base ${t.text}`}>
              {fmtRs(allocationRs)}
            </div>
          </div>
        )}
      </div>
      <div className="p-3 grid grid-cols-1 md:grid-cols-2 gap-3">
        {funds.map((f, i) => <FundCard key={i} fund={f} band={band} />)}
      </div>
    </div>
  );
}

// ── Single fund card ─────────────────────────────────────────────────
function FundCard({ fund, band }) {
  const bucket = BUCKET_BADGE[fund.bucket] || null;
  return (
    <div className="rounded-lg bg-white border border-slate-200 p-3" data-testid={`fund-card-${fund.scheme_name?.replace(/\s+/g, "-")}`}>
      <div className="flex items-start justify-between gap-2">
        <div className="min-w-0">
          <div className="text-[13px] font-semibold text-slate-900 leading-tight truncate" title={fund.scheme_name}>
            {fund.scheme_name}
          </div>
          <div className="text-[11px] text-slate-500 mt-0.5 flex items-center gap-1.5 flex-wrap">
            {fund.amc && <span>{fund.amc}</span>}
            {bucket && (
              <span className={`inline-block px-1.5 py-0 rounded text-[10px] font-medium border ${bucket.className}`}>
                {bucket.label}
              </span>
            )}
            {fund.risk_label && (
              <span className="text-[10px] text-slate-400">· {fund.risk_label}</span>
            )}
          </div>
        </div>
        <div className="text-right flex-shrink-0">
          <div className="text-[9px] uppercase tracking-wider text-slate-400">Quality</div>
          <div className={`text-lg font-bold font-mono ${
            fund.quality_score >= 70 ? "text-emerald-600" :
            fund.quality_score >= 55 ? "text-amber-600" :
            fund.quality_score >= 40 ? "text-indigo-600" :
                                       "text-rose-600"
          }`}>
            {fund.quality_score?.toFixed(0) ?? "—"}
          </div>
        </div>
      </div>

      {/* Why line — for non-Avoid bands, this is the strengths;
          for Avoid, it's the block reason. */}
      {fund.why && (
        <div className={`mt-2 text-[11.5px] ${
          band === "avoid" ? "text-rose-700" : "text-slate-600"
        }`}>
          {fund.why}
        </div>
      )}

      {/* Stat strip — only render if we have non-Avoid data to show */}
      {band !== "avoid" && (
        <div className="mt-2 grid grid-cols-4 gap-1.5 text-[10.5px]">
          <Mini label="3y" value={fmtPct(fund.ret_3y, 1)} positive={fund.ret_3y > 0} />
          <Mini label="5y" value={fmtPct(fund.ret_5y, 1)} positive={fund.ret_5y > 0} />
          <Mini label="ER" value={fmtPct(fund.expense_ratio_direct, 2)} muted />
          <Mini label="AUM" value={fund.aum_cr ? `₹${Math.round(fund.aum_cr).toLocaleString("en-IN")}Cr` : "—"} muted />
        </div>
      )}
    </div>
  );
}

const Mini = ({ label, value, positive, muted }) => (
  <div className="bg-slate-50 rounded px-1.5 py-1">
    <div className="text-slate-400 text-[9.5px] uppercase tracking-wider">{label}</div>
    <div className={`font-mono tabular-nums font-semibold ${
      muted ? "text-slate-700" :
      positive ? "text-emerald-700" : "text-rose-600"
    }`}>{value}</div>
  </div>
);
