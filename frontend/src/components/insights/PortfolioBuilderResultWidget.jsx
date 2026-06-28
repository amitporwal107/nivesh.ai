import React from "react";
import {
  ShieldCheck, ShieldAlert, ShieldQuestion, Layers, RefreshCw,
  Info, AlertTriangle,
} from "lucide-react";

/**
 * PortfolioBuilderResultWidget — renders the SLEEVE-based selection result
 * (services.sleeve_builder.build_sleeve_portfolio / POST /portfolio-builder/
 * generate-sleeves). This is the canonical output of the selection framework, so
 * it surfaces the signals the framework adds that the legacy bucket view does
 * not: per-pick hard-gate chips, holdings-overlap status, the compliance mode,
 * empty sleeves (shown honestly, never dropped) and the mandatory disclosures.
 *
 * Honesty contract (mirrors backend services/selection.py + CONTEXT.md §1):
 *   - a gate that could not be checked renders AMBER "not evaluated", visually
 *     distinct from a green pass — never shown as a pass;
 *   - a sleeve with no eligible fund is shown with its reason, not hidden;
 *   - in category-and-model mode (names suppressed) we render the model + a clear
 *     banner, never blanked-out rows that look like a bug.
 *
 * Render of this component is UNVERIFIED in CI (no yarn/browser available when it
 * was written); the logic matches the unit-tested backend payload shape.
 */

const fmtRs = (n) => {
  const v = Number(n) || 0;
  if (v >= 1e7) return `₹${(v / 1e7).toFixed(2)}Cr`;
  if (v >= 1e5) return `₹${(v / 1e5).toFixed(2)}L`;
  if (v >= 1000) return `₹${(v / 1000).toFixed(1)}k`;
  return `₹${Math.round(v).toLocaleString("en-IN")}`;
};

const ALLOC_COLOURS = {
  equity: "bg-emerald-500",
  debt: "bg-indigo-500",
  gold: "bg-amber-500",
  cash: "bg-slate-400",
};

const MANDATORY_DISCLOSURES = [
  "Past performance is not indicative of future results.",
  "Mutual funds are subject to market risk; read all scheme-related documents carefully.",
  "This is a model-driven, deterministic selection — not personalised investment advice.",
  "Conflict-of-interest: where a regular plan is shown, distributor commissions may apply.",
];

export default function PortfolioBuilderResultWidget({ result, onRebuild, testId = "selection-result" }) {
  if (!result) return null;
  const sleeves = result.sleeves || [];
  const comp = result.compliance || {};
  const namesAllowed = comp.names_allowed !== false; // default to model-only when unknown
  const alloc = result.allocation || {};
  const allocEntries = Object.entries(alloc).filter(([, v]) => Number(v) > 0);

  return (
    <div className="space-y-4" data-testid={testId}>
      {/* Header */}
      <div className="rounded-xl border-2 border-emerald-200 bg-emerald-50 px-5 py-4">
        <div className="flex items-start justify-between gap-3 flex-wrap">
          <div>
            <div className="text-[10px] uppercase tracking-wider font-bold text-emerald-700">
              Proposed portfolio · model
            </div>
            <h3 className="text-lg font-bold text-emerald-900">
              {sleeves.length} sleeve{sleeves.length !== 1 ? "s" : ""} · {result.risk_profile || "—"}
              {result.horizon_years ? ` · ${result.horizon_years}y` : ""}
            </h3>
          </div>
          {onRebuild && (
            <button
              onClick={onRebuild}
              className="text-xs text-emerald-700 hover:text-emerald-900 font-semibold inline-flex items-center gap-1"
              data-testid="selection-rebuild"
            >
              <RefreshCw className="w-3 h-3" /> Rebuild
            </button>
          )}
        </div>
      </div>

      {/* Compliance banner — only when names are suppressed (the MVP prod default) */}
      {!namesAllowed && (
        <div className="rounded-md border border-amber-200 bg-amber-50 px-3 py-2.5 text-[12px] text-amber-900 flex items-start gap-2" data-testid="selection-compliance-banner">
          <Info className="w-4 h-4 flex-shrink-0 mt-0.5" />
          <span>
            Showing the asset-allocation <strong>model and categories only</strong>. Specific scheme
            names appear once Compliance enables named recommendations.
          </span>
        </div>
      )}

      {/* Allocation strip */}
      {allocEntries.length > 0 && (
        <div className="rounded-xl border border-slate-200 bg-white p-4">
          <div className="text-[10px] uppercase tracking-wider font-bold text-slate-500 mb-2">
            Asset allocation
          </div>
          <div className="h-3 rounded-full bg-slate-100 overflow-hidden flex">
            {allocEntries.map(([k, v]) => (
              <div key={k} className={ALLOC_COLOURS[k] || "bg-slate-300"} style={{ width: `${v}%` }} title={`${k}: ${v}%`} />
            ))}
          </div>
          <div className="mt-3 grid grid-cols-2 md:grid-cols-4 gap-3">
            {allocEntries.map(([k, v]) => (
              <div key={k}>
                <div className="flex items-center gap-1.5 text-[11px] text-slate-500">
                  <span className={`w-2 h-2 rounded-sm ${ALLOC_COLOURS[k] || "bg-slate-300"}`} />
                  <span className="capitalize font-semibold text-slate-700">{k}</span>
                </div>
                <div className="text-base font-bold tabular-nums text-slate-900">{Number(v).toFixed(1)}%</div>
              </div>
            ))}
          </div>
        </div>
      )}

      {/* Validation verdict */}
      {result.validation && (
        <ValidationBadge validation={result.validation} />
      )}

      {/* Sleeve cards */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-3">
        {sleeves.map((s) => (
          <SleeveCard key={s.key} sleeve={s} namesAllowed={namesAllowed} />
        ))}
      </div>

      {/* Disclosures — mandatory, non-dismissible */}
      <DisclosuresFooter extra={comp.disclaimer} />

      {/* Audit reference (provenance, not advice) */}
      {(result.audit?.proposal_id || result.policy_version) && (
        <div className="text-[10.5px] text-slate-400 font-mono px-1" data-testid="selection-audit-ref">
          {result.audit?.proposal_id ? `proposal ${result.audit.proposal_id} · ` : ""}
          policy v{result.audit?.scoring_config_version || result.policy_version}
        </div>
      )}
    </div>
  );
}

// ── Sleeve card ───────────────────────────────────────────────────────────
function SleeveCard({ sleeve, namesAllowed }) {
  const funds = sleeve.funds || [];
  const rejected = (sleeve.selection && sleeve.selection.rejected) || [];
  return (
    <div className="rounded-xl border border-slate-200 bg-white p-4" data-testid={`sleeve-${sleeve.key}`}>
      <div className="flex items-center justify-between mb-2">
        <div>
          <div className="text-[10px] uppercase tracking-wider font-bold text-slate-500">{sleeve.label}</div>
          <div className="text-base font-bold text-slate-900">
            {sleeve.target_pct}%
            {sleeve.monthly_sip_rs ? <span className="ml-1 text-[12px] font-normal text-slate-500">· SIP {fmtRs(sleeve.monthly_sip_rs)}/mo</span> : null}
          </div>
        </div>
        <Layers className="w-4 h-4 text-slate-300" />
      </div>

      {/* Category-and-model mode: show the member categories, no names */}
      {!namesAllowed && (
        <div className="flex flex-wrap gap-1.5">
          {(sleeve.category_members || []).map((m) => (
            <span key={m} className="text-[11px] px-2 py-0.5 rounded-full bg-slate-100 text-slate-700">{m}</span>
          ))}
          {(sleeve.category_members || []).length === 0 && (
            <span className="text-[11px] text-slate-400 italic">{sleeve.detail || "Category guidance"}</span>
          )}
        </div>
      )}

      {/* Named mode: ranked picks with gate chips + overlap */}
      {namesAllowed && funds.length > 0 && (
        <div className="space-y-2">
          {funds.map((f) => (
            <FundRow key={f.isin || f.scheme_name} fund={f} />
          ))}
        </div>
      )}

      {/* Named mode but no eligible fund — shown honestly with reasons */}
      {namesAllowed && funds.length === 0 && (
        <div className="rounded-lg border border-dashed border-slate-300 bg-slate-50 px-3 py-2.5 text-[11.5px] text-slate-500" data-testid={`sleeve-empty-${sleeve.key}`}>
          <div className="flex items-center gap-1.5 font-semibold text-slate-600">
            <AlertTriangle className="w-3.5 h-3.5 text-amber-500" /> No eligible fund for this sleeve
          </div>
          {rejected.length > 0 && (
            <div className="mt-1">
              All candidates were excluded:{" "}
              {Array.from(new Set(rejected.flatMap((r) => r.gate_failed || []))).join(", ") || "did not pass the hard gates"}.
            </div>
          )}
        </div>
      )}
    </div>
  );
}

// ── Fund row: name + score + gate chips + overlap ───────────────────────────
function FundRow({ fund }) {
  const score = fund.quality_score != null ? fund.quality_score : fund.debt_score;
  return (
    <div className="bg-slate-50 rounded-lg p-2.5" data-testid={`fund-${fund.isin || "x"}`}>
      <div className="flex items-start justify-between gap-2">
        <div className="text-[12.5px] font-semibold text-slate-900 leading-tight">{fund.scheme_name || fund.isin}</div>
        {score != null && (
          <span className="text-[11px] font-bold tabular-nums text-slate-500 flex-shrink-0">{Number(score).toFixed(0)}</span>
        )}
      </div>
      <div className="mt-1.5 flex flex-wrap items-center gap-1.5">
        <GateChips gates={fund.gate_results} />
        <OverlapChip status={fund.overlap_status} pct={fund.overlap_pct} />
      </div>
    </div>
  );
}

// ── Gate chips: pass=emerald, fail=rose, not_evaluated=amber ────────────────
function GateChips({ gates }) {
  if (!gates || gates.length === 0) return null;
  const failed = gates.filter((g) => g.status === "failed");
  const notEval = gates.filter((g) => g.status === "not_evaluated");
  // If everything checkable passed, a single concise "eligible" chip.
  if (failed.length === 0 && notEval.length === 0) {
    return <Chip tone="emerald" icon={ShieldCheck} label="Eligible" />;
  }
  return (
    <>
      {failed.length === 0 && (
        <Chip tone="emerald" icon={ShieldCheck} label="Gates passed" />
      )}
      {failed.map((g) => (
        <Chip key={g.gate} tone="rose" icon={ShieldAlert} label={g.gate.replace(/_/g, " ")} title={g.reason} />
      ))}
      {notEval.map((g) => (
        <Chip key={g.gate} tone="amber" icon={ShieldQuestion} label={`${g.gate.replace(/_/g, " ")}: n/a`} title="Not evaluated — data unavailable" />
      ))}
    </>
  );
}

function OverlapChip({ status, pct }) {
  if (!status) return null;
  if (status === "rejected") {
    return <Chip tone="rose" icon={ShieldAlert} label={`overlap ${pct != null ? `${Math.round(pct * 100)}%` : "high"}`} />;
  }
  if (status === "not_evaluated") {
    return <Chip tone="amber" icon={ShieldQuestion} label="overlap: n/a" title="No holdings data to check overlap" />;
  }
  return <Chip tone="slate" icon={ShieldCheck} label={`overlap ${pct != null ? `${Math.round(pct * 100)}%` : "ok"}`} />;
}

const TONES = {
  emerald: "bg-emerald-50 text-emerald-700 border-emerald-200",
  rose: "bg-rose-50 text-rose-700 border-rose-200",
  amber: "bg-amber-50 text-amber-800 border-amber-200",
  slate: "bg-slate-100 text-slate-600 border-slate-200",
};

function Chip({ tone, icon: Icon, label, title }) {
  return (
    <span className={`inline-flex items-center gap-1 text-[10.5px] font-medium px-1.5 py-0.5 rounded-full border ${TONES[tone] || TONES.slate}`} title={title}>
      {Icon ? <Icon className="w-3 h-3" /> : null}
      {label}
    </span>
  );
}

// ── Validation verdict ──────────────────────────────────────────────────────
function ValidationBadge({ validation }) {
  const passed = validation.passed !== false;
  return (
    <div className={`rounded-md border px-3 py-2 text-[12px] flex items-center gap-2 ${passed ? "border-emerald-200 bg-emerald-50 text-emerald-800" : "border-amber-200 bg-amber-50 text-amber-900"}`}>
      {passed ? <ShieldCheck className="w-4 h-4" /> : <AlertTriangle className="w-4 h-4" />}
      <span>{passed ? "Passed simulation validation gates." : (validation.message || "Simulation flagged a warning — review before acting.")}</span>
    </div>
  );
}

// ── Disclosures footer (mandatory, always visible) ──────────────────────────
function DisclosuresFooter({ extra }) {
  return (
    <div className="rounded-lg border border-slate-200 bg-slate-50 px-3 py-2.5" data-testid="selection-disclosures">
      <div className="text-[10px] uppercase tracking-wider font-bold text-slate-500 mb-1">Important disclosures</div>
      <ul className="space-y-0.5">
        {extra && (
          <li className="text-[10.5px] text-slate-600 leading-relaxed">{extra}</li>
        )}
        {MANDATORY_DISCLOSURES.map((d) => (
          <li key={d} className="text-[10.5px] text-slate-500 leading-relaxed">• {d}</li>
        ))}
      </ul>
    </div>
  );
}
