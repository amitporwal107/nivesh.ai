import React, { useState, useCallback } from "react";
import axios from "axios";
import {
  Sparkles, Brain, MessageSquare, RefreshCw, ArrowRight, Download,
  Share2, AlertCircle, CheckCircle2, TrendingUp, Hourglass,
} from "lucide-react";

const API = `${process.env.REACT_APP_BACKEND_URL}/api`;

const fmtRs = (n) => {
  const v = Number(n) || 0;
  if (v >= 1e7) return `₹${(v / 1e7).toFixed(2)}Cr`;
  if (v >= 1e5) return `₹${(v / 1e5).toFixed(2)}L`;
  if (v >= 1000) return `₹${(v / 1000).toFixed(1)}k`;
  return `₹${Math.round(v).toLocaleString("en-IN")}`;
};
const fmtPct = (n, dp = 1) => n == null ? "—" : `${Number(n).toFixed(dp)}%`;

/**
 * PortfolioBuilderView — empty-state magic moment.
 *
 * Single entry point that orchestrates the four flows:
 *   1. Risk-profile chat (if no profile yet)
 *   2. Generate proposed portfolio
 *   3. What-if simulation (collapsible)
 *   4. PDF + WhatsApp export
 */
export default function PortfolioBuilderView({ clientName = "Client" }) {
  const [stage, setStage] = useState("input");   // input | chat | building | result
  const [showChat, setShowChat] = useState(false);
  const [sip, setSip] = useState("");
  const [lump, setLump] = useState("");
  const [proposal, setProposal] = useState(null);
  const [error, setError] = useState(null);
  const [loading, setLoading] = useState(false);

  const generate = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const res = await axios.post(`${API}/portfolio-builder/generate`, {
        monthly_sip_rs: sip ? Number(sip) : null,
        lumpsum_rs: lump ? Number(lump) : null,
      }, { withCredentials: true });
      setProposal(res.data);
      setStage("result");
    } catch (e) {
      setError(e.response?.data?.detail || e.message || "Build failed");
    } finally {
      setLoading(false);
    }
  }, [sip, lump]);

  return (
    <div className="space-y-4" data-testid="portfolio-builder">
      <div className="flex items-start gap-3">
        <div className="w-12 h-12 rounded-xl bg-gradient-to-br from-emerald-500 to-indigo-600 flex items-center justify-center text-white">
          <Sparkles className="w-6 h-6" />
        </div>
        <div className="flex-1">
          <h2 className="text-xl font-bold text-slate-900">AI Portfolio Builder</h2>
          <p className="text-[12.5px] text-slate-500">
            We&apos;ll propose an asset allocation + fund picks based on the risk profile and goals already on file.
          </p>
        </div>
      </div>

      {/* Risk profile chat toggle */}
      <button
        onClick={() => setShowChat((s) => !s)}
        className="w-full text-left rounded-xl border border-indigo-200 bg-indigo-50/60 hover:bg-indigo-50 px-4 py-3 flex items-center justify-between gap-3 transition-colors"
        data-testid="builder-toggle-risk-chat"
      >
        <div className="flex items-center gap-2.5">
          <Brain className="w-4 h-4 text-indigo-600" />
          <div>
            <div className="text-[13px] font-semibold text-indigo-900">
              {showChat ? "Hide risk profiler" : "Run conversational risk profile"}
            </div>
            <div className="text-[11px] text-indigo-700">
              5 quick scenarios — replaces the form, takes &lt; 90 seconds.
            </div>
          </div>
        </div>
        <ArrowRight className={`w-4 h-4 text-indigo-600 transition-transform ${showChat ? "rotate-90" : ""}`} />
      </button>

      {showChat && (
        <RiskProfileChat onComplete={() => setShowChat(false)} />
      )}

      {/* Sizing inputs */}
      <div className="rounded-xl border border-slate-200 bg-white p-4">
        <div className="text-[10px] uppercase tracking-wider font-bold text-slate-500 mb-2">
          Optional sizing
        </div>
        <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
          <NumberField
            label="Monthly SIP (₹)"
            value={sip}
            onChange={setSip}
            placeholder="e.g. 50000"
            testid="builder-sip-input"
          />
          <NumberField
            label="Lump sum (₹)"
            value={lump}
            onChange={setLump}
            placeholder="e.g. 1000000"
            testid="builder-lump-input"
          />
        </div>
        <p className="text-[10.5px] text-slate-400 mt-2">
          Leave blank to see allocation % only — we&apos;ll compute ₹ amounts when sizing is provided.
        </p>
      </div>

      {/* Generate button */}
      <button
        onClick={generate}
        disabled={loading}
        className="w-full inline-flex items-center justify-center gap-2 px-4 py-2.5 rounded-lg bg-emerald-600 hover:bg-emerald-700 text-white font-semibold text-sm disabled:opacity-50"
        data-testid="builder-generate"
      >
        {loading ? (
          <><RefreshCw className="w-4 h-4 animate-spin" /> Building portfolio…</>
        ) : (
          <><Sparkles className="w-4 h-4" /> Build proposed portfolio</>
        )}
      </button>

      {error && (
        <div className="rounded-md border border-rose-200 bg-rose-50 p-3 text-rose-800 text-sm flex items-start gap-2" data-testid="builder-error">
          <AlertCircle className="w-4 h-4 flex-shrink-0 mt-0.5" />
          <div>{String(error)}</div>
        </div>
      )}

      {proposal && stage === "result" && (
        <ProposalView
          proposal={proposal}
          clientName={clientName}
          monthlySipRs={sip ? Number(sip) : null}
          lumpsumRs={lump ? Number(lump) : null}
          onRebuild={generate}
        />
      )}
    </div>
  );
}

const NumberField = ({ label, value, onChange, placeholder, testid }) => (
  <label className="block">
    <span className="block text-[11px] uppercase tracking-wider text-slate-500 mb-1">{label}</span>
    <input
      type="number"
      min="0"
      value={value}
      onChange={(e) => onChange(e.target.value)}
      placeholder={placeholder}
      className="w-full rounded-md border border-slate-200 px-3 py-2 text-sm focus:border-emerald-500 focus:outline-none"
      data-testid={testid}
    />
  </label>
);

// ── Risk profile chat ─────────────────────────────────────────────────
function RiskProfileChat({ onComplete }) {
  const [sessionId, setSessionId] = useState(null);
  const [question, setQuestion] = useState(null);
  const [intro, setIntro] = useState(null);
  const [result, setResult] = useState(null);
  const [submitting, setSubmitting] = useState(false);
  const [chatError, setChatError] = useState(null);

  const start = useCallback(async () => {
    setChatError(null);
    setSubmitting(true);
    try {
      const res = await axios.post(`${API}/risk-profile/start`, {}, { withCredentials: true });
      setSessionId(res.data.session_id);
      setQuestion(res.data.question);
      setIntro(res.data.intro);
      setResult(null);
    } catch (e) {
      setChatError(e.response?.data?.detail || e.message || "Couldn't start chat");
    } finally {
      setSubmitting(false);
    }
  }, []);

  const submit = useCallback(async (value) => {
    if (!sessionId || !question) return;
    setSubmitting(true);
    setChatError(null);
    try {
      const res = await axios.post(
        `${API}/risk-profile/${sessionId}/answer`,
        { question_id: question.id, value },
        { withCredentials: true },
      );
      if (res.data.complete) {
        setResult(res.data);
        setQuestion(null);
      } else {
        setQuestion(res.data.question);
      }
    } catch (e) {
      setChatError(e.response?.data?.detail?.message || e.response?.data?.detail || e.message || "Failed");
    } finally {
      setSubmitting(false);
    }
  }, [sessionId, question]);

  // Auto-start when the chat first opens
  React.useEffect(() => {
    if (!sessionId && !result) start();
  }, [sessionId, result, start]);

  if (chatError) {
    return (
      <div className="rounded-xl border border-rose-200 bg-rose-50 p-4 text-sm text-rose-800">
        {String(chatError)}
        <button onClick={start} className="ml-2 underline font-semibold">Retry</button>
      </div>
    );
  }

  if (result) {
    return (
      <div className="rounded-xl border-2 border-emerald-200 bg-emerald-50 p-4" data-testid="risk-chat-result">
        <div className="flex items-start gap-3">
          <CheckCircle2 className="w-5 h-5 text-emerald-600 flex-shrink-0 mt-0.5" />
          <div className="flex-1">
            <div className="text-[10px] uppercase tracking-wider font-bold text-emerald-700 mb-1">
              Risk profile saved
            </div>
            <h4 className="text-base font-bold text-emerald-900">{result.persona} · {result.score?.toFixed(0)}/100</h4>
            <p className="text-[12.5px] text-emerald-800 mt-1">{result.narrative}</p>
            <button
              onClick={() => { onComplete?.(); }}
              className="mt-2 text-xs font-semibold text-emerald-700 hover:text-emerald-900 underline underline-offset-2"
            >
              Continue to portfolio →
            </button>
          </div>
        </div>
      </div>
    );
  }

  if (!question) {
    return (
      <div className="rounded-xl border border-slate-200 bg-slate-50 p-4 text-sm text-slate-500">
        Loading risk profiler…
      </div>
    );
  }

  return (
    <div className="rounded-xl border-2 border-indigo-200 bg-white p-4 space-y-3" data-testid="risk-chat">
      {intro && question.step === 1 && (
        <div className="rounded-md bg-indigo-50 border border-indigo-100 px-3 py-2 text-[12px] text-indigo-800 flex items-start gap-2">
          <MessageSquare className="w-3.5 h-3.5 mt-0.5 flex-shrink-0" /> {intro}
        </div>
      )}
      <div className="flex items-center justify-between">
        <span className="text-[10px] uppercase tracking-wider font-bold text-indigo-600">
          Step {question.step} of {question.total_steps} · {question.section}
        </span>
        <div className="h-1.5 w-32 rounded-full bg-slate-100 overflow-hidden">
          <div
            className="h-full bg-indigo-500 transition-all"
            style={{ width: `${(question.step / question.total_steps) * 100}%` }}
          />
        </div>
      </div>
      <h4 className="text-base font-bold text-slate-900">{question.prompt}</h4>
      {question.subtitle && (
        <p className="text-[11.5px] text-slate-500">{question.subtitle}</p>
      )}
      <div className="space-y-2 pt-1">
        {question.choices.map((c) => (
          <button
            key={c.value}
            disabled={submitting}
            onClick={() => submit(c.value)}
            className="w-full text-left px-3 py-2 rounded-lg border border-slate-200 hover:border-indigo-400 hover:bg-indigo-50/40 transition-colors text-[13px] font-medium text-slate-800 disabled:opacity-50"
            data-testid={`risk-chat-choice-${c.value}`}
          >
            {c.label}
          </button>
        ))}
      </div>
    </div>
  );
}

// ── Proposal view ─────────────────────────────────────────────────────
function ProposalView({ proposal, clientName, monthlySipRs, lumpsumRs, onRebuild }) {
  const [showSim, setShowSim] = useState(false);
  return (
    <div className="space-y-4" data-testid="builder-proposal">
      <div className="rounded-xl border-2 border-emerald-200 bg-emerald-50 px-5 py-4">
        <div className="flex items-start justify-between gap-3 flex-wrap">
          <div>
            <div className="text-[10px] uppercase tracking-wider font-bold text-emerald-700">
              Proposed portfolio
            </div>
            <h3 className="text-lg font-bold text-emerald-900">
              {proposal.totals?.total_funds || 0} funds across {Object.keys(proposal.allocation || {}).length} buckets
            </h3>
            <div className="text-[12px] text-emerald-800 mt-0.5">
              Risk: <span className="font-semibold">{proposal.risk_profile}</span>
              {monthlySipRs ? <> · SIP <span className="font-semibold">{fmtRs(monthlySipRs)}</span>/mo</> : null}
              {lumpsumRs ? <> · Lump <span className="font-semibold">{fmtRs(lumpsumRs)}</span></> : null}
            </div>
          </div>
          <button
            onClick={onRebuild}
            className="text-xs text-emerald-700 hover:text-emerald-900 font-semibold inline-flex items-center gap-1"
          >
            <RefreshCw className="w-3 h-3" /> Rebuild
          </button>
        </div>
      </div>

      {/* Allocation strip */}
      <AllocationStrip allocation={proposal.allocation || {}}
                       allocationRs={proposal.allocation_rs}
                       sipRs={proposal.monthly_sip_split_rs} />

      {/* Bucket cards with fund picks */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-3">
        {(proposal.buckets || []).map((b) => (
          <BucketCard key={b.bucket} bucket={b} />
        ))}
      </div>

      {/* Why this portfolio */}
      {proposal.rationale?.length > 0 && (
        <div className="rounded-xl border border-slate-200 bg-white p-4">
          <div className="text-[10px] uppercase tracking-wider font-bold text-slate-500 mb-2">
            Why this portfolio
          </div>
          <ul className="space-y-1">
            {proposal.rationale.map((r) => (
              <li key={r} className="flex items-start gap-1.5 text-[12.5px] text-slate-700">
                <span className="mt-1.5 w-1 h-1 rounded-full bg-emerald-500 flex-shrink-0" />
                <span>{r}</span>
              </li>
            ))}
          </ul>
        </div>
      )}

      {/* Simulation toggle */}
      <button
        onClick={() => setShowSim((s) => !s)}
        className="w-full text-left rounded-xl border border-amber-200 bg-amber-50/60 hover:bg-amber-50 px-4 py-3 flex items-center justify-between gap-3 transition-colors"
        data-testid="builder-toggle-sim"
      >
        <div className="flex items-center gap-2.5">
          <TrendingUp className="w-4 h-4 text-amber-600" />
          <div>
            <div className="text-[13px] font-semibold text-amber-900">
              {showSim ? "Hide simulation" : "Run what-if simulation"}
            </div>
            <div className="text-[11px] text-amber-700">
              Stress-test this portfolio under bull / bear / crash scenarios.
            </div>
          </div>
        </div>
        <ArrowRight className={`w-4 h-4 text-amber-600 transition-transform ${showSim ? "rotate-90" : ""}`} />
      </button>

      {showSim && (
        <SimulationPanel
          allocation={proposal.allocation || {}}
          monthlySipRs={monthlySipRs}
          lumpsumRs={lumpsumRs}
        />
      )}

      {/* Export actions */}
      <ExportActions
        clientName={clientName}
        monthlySipRs={monthlySipRs}
        lumpsumRs={lumpsumRs}
      />
    </div>
  );
}

// ── Allocation strip ──────────────────────────────────────────────────
function AllocationStrip({ allocation, allocationRs, sipRs }) {
  const buckets = Object.entries(allocation || {}).filter(([, v]) => v > 0);
  const colours = {
    equity: "bg-emerald-500",
    debt: "bg-indigo-500",
    gold: "bg-amber-500",
    cash: "bg-slate-400",
    hybrid: "bg-rose-400",
  };
  return (
    <div className="rounded-xl border border-slate-200 bg-white p-4">
      <div className="text-[10px] uppercase tracking-wider font-bold text-slate-500 mb-2">
        Asset allocation
      </div>
      <div className="h-3 rounded-full bg-slate-100 overflow-hidden flex">
        {buckets.map(([k, v]) => (
          <div
            key={k}
            className={colours[k] || "bg-slate-300"}
            style={{ width: `${v}%` }}
            title={`${k}: ${v}%`}
          />
        ))}
      </div>
      <div className="mt-3 grid grid-cols-2 md:grid-cols-4 gap-3">
        {buckets.map(([k, v]) => (
          <div key={k}>
            <div className="flex items-center gap-1.5 text-[11px] text-slate-500">
              <span className={`w-2 h-2 rounded-sm ${colours[k] || "bg-slate-300"}`} />
              <span className="capitalize font-semibold text-slate-700">{k}</span>
            </div>
            <div className="text-base font-bold tabular-nums text-slate-900">{v.toFixed(1)}%</div>
            {(allocationRs?.[k] || sipRs?.[k]) && (
              <div className="text-[10.5px] text-slate-500 font-mono tabular-nums">
                {allocationRs?.[k] ? fmtRs(allocationRs[k]) : null}
                {sipRs?.[k] ? <span className="ml-1">SIP {fmtRs(sipRs[k])}/mo</span> : null}
              </div>
            )}
          </div>
        ))}
      </div>
    </div>
  );
}

// ── Bucket card ───────────────────────────────────────────────────────
function BucketCard({ bucket }) {
  return (
    <div className="rounded-xl border border-slate-200 bg-white p-4" data-testid={`bucket-${bucket.bucket}`}>
      <div className="flex items-center justify-between mb-2">
        <div>
          <div className="text-[10px] uppercase tracking-wider font-bold text-slate-500">
            {bucket.bucket}
          </div>
          <div className="text-base font-bold text-slate-900">
            {bucket.target_pct}% · {bucket.n_funds_picked} fund{bucket.n_funds_picked !== 1 ? "s" : ""}
          </div>
        </div>
        {(bucket.target_rs || bucket.monthly_sip_rs) && (
          <div className="text-right text-[11px] text-slate-500">
            {bucket.target_rs ? <div className="font-mono">{fmtRs(bucket.target_rs)}</div> : null}
            {bucket.monthly_sip_rs ? <div className="font-mono">SIP {fmtRs(bucket.monthly_sip_rs)}/mo</div> : null}
          </div>
        )}
      </div>
      <div className="space-y-2">
        {(bucket.funds || []).map((f) => (
          <div key={f.instrument_id || f.scheme_name} className="bg-slate-50 rounded-lg p-2.5">
            <div className="text-[12.5px] font-semibold text-slate-900 leading-tight">
              {f.scheme_name}
            </div>
            <div className="text-[11px] text-slate-600 mt-0.5">{f.rationale}</div>
            {f.lumpsum_rs && (
              <div className="text-[10.5px] text-slate-500 font-mono mt-0.5">
                Allocate {fmtRs(f.lumpsum_rs)}
              </div>
            )}
          </div>
        ))}
        {(bucket.funds || []).length === 0 && (
          <div className="text-[11px] text-slate-400 italic">No funds matched the quality / AUM filters for this bucket.</div>
        )}
      </div>
    </div>
  );
}

// ── Simulation panel ──────────────────────────────────────────────────
function SimulationPanel({ allocation, monthlySipRs, lumpsumRs }) {
  const [years, setYears] = useState(10);
  const [target, setTarget] = useState(10000000);   // 1 Cr default
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);

  const run = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const res = await axios.post(`${API}/portfolio-builder/simulate`, {
        starting_corpus_rs: lumpsumRs || 0,
        monthly_sip_rs: monthlySipRs || 0,
        years: Number(years),
        future_target_rs: Number(target),
        allocation,
      }, { withCredentials: true });
      setData(res.data);
    } catch (e) {
      setError(e.response?.data?.detail || e.message || "Simulation failed");
    } finally {
      setLoading(false);
    }
  }, [allocation, monthlySipRs, lumpsumRs, years, target]);

  React.useEffect(() => { run(); }, [run]);

  if (loading) {
    return <div className="rounded-xl border border-slate-200 bg-white p-4 text-sm text-slate-500">Running scenarios…</div>;
  }
  if (error) {
    return <div className="rounded-xl border border-rose-200 bg-rose-50 p-3 text-sm text-rose-800">{String(error)}</div>;
  }
  if (!data) return null;

  const SCENARIO_TONES = {
    bull:   { label: "Bull case",   bg: "bg-emerald-50 border-emerald-200", text: "text-emerald-900" },
    base:   { label: "Base case",   bg: "bg-indigo-50 border-indigo-200",   text: "text-indigo-900" },
    bear:   { label: "Bear case",   bg: "bg-amber-50 border-amber-200",     text: "text-amber-900" },
    stress: { label: "Stress case", bg: "bg-rose-50 border-rose-200",       text: "text-rose-900" },
  };

  return (
    <div className="rounded-xl border border-slate-200 bg-white p-4 space-y-3" data-testid="builder-simulation">
      <div className="grid grid-cols-2 md:grid-cols-3 gap-3">
        <NumberField label="Horizon (years)" value={years} onChange={(v) => setYears(v || 10)} placeholder="10" />
        <NumberField label="Target corpus (₹)" value={target} onChange={(v) => setTarget(v || 0)} placeholder="10000000" />
        <div className="flex items-end">
          <button
            onClick={run}
            className="w-full px-3 py-2 text-sm font-semibold rounded-md bg-amber-500 hover:bg-amber-600 text-white inline-flex items-center justify-center gap-1.5"
          >
            <RefreshCw className="w-3.5 h-3.5" /> Re-run
          </button>
        </div>
      </div>

      <div className="text-[11px] text-slate-500">
        Blended return: <span className="font-mono font-bold text-slate-800">{fmtPct(data.blended_return_pct)}</span>
        <span className="mx-2 text-slate-300">·</span>
        Volatility: <span className="font-mono font-bold text-slate-800">{fmtPct(data.blended_vol_pct)}</span>
      </div>

      <div className="grid grid-cols-2 md:grid-cols-4 gap-2">
        {Object.entries(data.scenarios || {}).map(([k, v]) => {
          const t = SCENARIO_TONES[k] || SCENARIO_TONES.base;
          return (
            <div key={k} className={`rounded-lg border p-2.5 ${t.bg}`} data-testid={`sim-scenario-${k}`}>
              <div className={`text-[10px] uppercase tracking-wider font-bold ${t.text}`}>{t.label}</div>
              <div className={`text-base font-bold tabular-nums ${t.text}`}>{fmtRs(v.corpus_rs)}</div>
              <div className="text-[10.5px] text-slate-600 font-mono">
                @ {fmtPct(v.return_pct)} · {fmtPct(v.success_pct, 0)} of target
              </div>
            </div>
          );
        })}
      </div>

      {data.monte_carlo && (
        <div className="rounded-lg bg-slate-50 p-3 text-[12px] text-slate-700">
          <div className="text-[10px] uppercase tracking-wider font-bold text-slate-500 mb-1">
            Monte Carlo · 500 paths
          </div>
          <div className="grid grid-cols-3 gap-2 text-center">
            <div>
              <div className="text-slate-500 text-[10px]">P10 (worst)</div>
              <div className="font-mono font-bold text-rose-700">{fmtRs(data.monte_carlo.p10)}</div>
            </div>
            <div>
              <div className="text-slate-500 text-[10px]">P50 (median)</div>
              <div className="font-mono font-bold text-indigo-700">{fmtRs(data.monte_carlo.p50)}</div>
            </div>
            <div>
              <div className="text-slate-500 text-[10px]">P90 (best)</div>
              <div className="font-mono font-bold text-emerald-700">{fmtRs(data.monte_carlo.p90)}</div>
            </div>
          </div>
          {data.monte_carlo.success_pct != null && (
            <div className="text-center mt-2 text-[11px]">
              Probability of hitting target: <span className="font-bold tabular-nums">{fmtPct(data.monte_carlo.success_pct)}</span>
            </div>
          )}
        </div>
      )}
    </div>
  );
}

// ── Export actions ────────────────────────────────────────────────────
function ExportActions({ clientName, monthlySipRs, lumpsumRs }) {
  const [busy, setBusy] = useState(false);

  const downloadPdf = async () => {
    setBusy(true);
    try {
      const res = await axios.post(`${API}/portfolio-builder/export.pdf`, {
        monthly_sip_rs: monthlySipRs,
        lumpsum_rs: lumpsumRs,
      }, { withCredentials: true, responseType: "blob" });
      const url = window.URL.createObjectURL(new Blob([res.data], { type: "application/pdf" }));
      const a = document.createElement("a");
      a.href = url;
      a.download = `portfolio_proposal_${clientName.replace(/\s+/g, "_")}.pdf`;
      a.click();
      window.URL.revokeObjectURL(url);
    } catch (e) {
      alert(`PDF export failed: ${e.message || e}`);
    } finally {
      setBusy(false);
    }
  };

  const shareWhatsApp = async () => {
    setBusy(true);
    try {
      const res = await axios.post(`${API}/portfolio-builder/whatsapp-share`, {
        monthly_sip_rs: monthlySipRs,
        lumpsum_rs: lumpsumRs,
        client_name: clientName,
      }, { withCredentials: true });
      window.open(res.data.deeplink, "_blank", "noopener,noreferrer");
    } catch (e) {
      alert(`WhatsApp share failed: ${e.message || e}`);
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="flex gap-2 flex-wrap">
      <button
        onClick={downloadPdf}
        disabled={busy}
        className="flex-1 inline-flex items-center justify-center gap-2 px-3 py-2 rounded-lg border border-slate-200 hover:bg-slate-50 text-sm font-semibold text-slate-800 disabled:opacity-50"
        data-testid="builder-export-pdf"
      >
        {busy ? <Hourglass className="w-4 h-4 animate-pulse" /> : <Download className="w-4 h-4" />}
        Download PDF
      </button>
      <button
        onClick={shareWhatsApp}
        disabled={busy}
        className="flex-1 inline-flex items-center justify-center gap-2 px-3 py-2 rounded-lg bg-emerald-600 hover:bg-emerald-700 text-white text-sm font-semibold disabled:opacity-50"
        data-testid="builder-export-whatsapp"
      >
        {busy ? <Hourglass className="w-4 h-4 animate-pulse" /> : <Share2 className="w-4 h-4" />}
        Send via WhatsApp
      </button>
    </div>
  );
}
