import React, { useState } from "react";
import { useNavigate, useOutletContext } from "react-router-dom";
import { AlertTriangle, RefreshCw, Plus, Target, TrendingUp, Clock, Trash2, X, Check } from "lucide-react";
import HeroCard from "../../components/HeroCard";
import CompactCard from "../../components/CompactCard";
import TinyChip from "../../components/TinyChip";
import SectionHead from "../../components/SectionHead";
import ScreenContainer from "../../components/layout/ScreenContainer";
import TopBar from "../../components/layout/TopBar";
import { useGoals, deleteGoal, whatIfGoal, createGoal } from "../../adapters/goals";
import { inrCompact, pct } from "../../lib/format";

// ─── goal type icons + colors ─────────────────────────────────────────────────

const GOAL_META = {
  retirement: { label: "Retirement", icon: "👴", accent: "var(--v3-gold)" },
  education:  { label: "Education",  icon: "🎓", accent: "var(--v3-indigo)" },
  home:       { label: "Home",       icon: "🏠", accent: "var(--v3-moss)" },
  vehicle:    { label: "Vehicle",    icon: "🚗", accent: "var(--v3-saffron)" },
  travel:     { label: "Travel",     icon: "✈️", accent: "var(--v3-saffron)" },
  emergency:  { label: "Emergency",  icon: "🛡️", accent: "var(--v3-crimson)" },
  wedding:    { label: "Wedding",    icon: "💍", accent: "var(--v3-gold)" },
  other:      { label: "Goal",       icon: "🎯", accent: "var(--v3-saffron)" },
};

function goalMeta(g) {
  const key = (g.goal_type || g.type || "other").toLowerCase();
  return GOAL_META[key] || GOAL_META.other;
}

// ─── progress ring ────────────────────────────────────────────────────────────

function ProgressRing({ pct: val = 0, size = 44, accent = "var(--v3-saffron)" }) {
  const r = (size - 6) / 2;
  const circ = 2 * Math.PI * r;
  const filled = Math.min((val / 100) * circ, circ);
  return (
    <svg width={size} height={size} style={{ flexShrink: 0 }}>
      <circle cx={size / 2} cy={size / 2} r={r} fill="none" stroke="var(--v3-bg-3)" strokeWidth={5} />
      <circle
        cx={size / 2} cy={size / 2} r={r}
        fill="none"
        stroke={val >= 80 ? "var(--v3-moss)" : val >= 50 ? "var(--v3-gold)" : "var(--v3-crimson)"}
        strokeWidth={5}
        strokeDasharray={`${filled} ${circ}`}
        strokeLinecap="round"
        transform={`rotate(-90 ${size / 2} ${size / 2})`}
      />
      <text x={size / 2} y={size / 2 + 4} textAnchor="middle" fontSize={9} fill="var(--v3-ink-2)" fontFamily="var(--v3-font-mono)">
        {Math.round(val)}%
      </text>
    </svg>
  );
}

// ─── verdict banner ───────────────────────────────────────────────────────────

function VerdictBanner({ verdict, shortfall }) {
  const cfg = {
    ON_TRACK:  { color: "var(--v3-moss)",    bg: "var(--v3-moss-soft)",    label: "ON TRACK ✓" },
    AHEAD:     { color: "var(--v3-moss)",    bg: "var(--v3-moss-soft)",    label: "AHEAD ✓" },
    AT_RISK:   { color: "var(--v3-gold)",    bg: "#D4AF3726",              label: "AT RISK ⚠" },
    CRITICAL:  { color: "var(--v3-crimson)", bg: "var(--v3-crimson-soft)", label: "CRITICAL ✕" },
  };
  const c = cfg[verdict] || cfg.AT_RISK;
  return (
    <div style={{ padding: "10px 14px", background: c.bg, borderRadius: 10, display: "flex", alignItems: "center", gap: 10 }}>
      <span style={{ fontFamily: "var(--v3-font-mono)", fontSize: 11, color: c.color, fontWeight: 600 }}>{c.label}</span>
      {shortfall != null && shortfall > 0 && (
        <span style={{ fontSize: 12, color: "var(--v3-ink-2)" }}>{inrCompact(shortfall)} short at current pace</span>
      )}
    </div>
  );
}

// ─── goal detail panel (slide-in) ────────────────────────────────────────────

function GoalDetail({ goal, onClose }) {
  const meta = goalMeta(goal);
  const onTrackPct = goal.on_track_pct ?? goal.probability_of_success ?? null;
  const mcSuccess = goal.monte_carlo?.success_probability ?? goal.mc_success_pct ?? null;
  const targetFV = goal.target_amount ?? goal.target_fv ?? null;
  const currentSIP = goal.monthly_sip ?? goal.sip_amount ?? null;
  const requiredSIP = goal.sip_gap != null ? (currentSIP ?? 0) + goal.sip_gap : null;
  const horizonYrs = goal.horizon_years ?? goal.years_remaining ?? null;
  const verdict = goal.verdict ?? (onTrackPct >= 80 ? "ON_TRACK" : onTrackPct >= 50 ? "AT_RISK" : "CRITICAL");
  const shortfall = goal.shortfall_amount ?? null;

  const recoveryPaths = goal.recovery_paths || [];
  const scenarios = goal.scenarios || {};
  const whyBehind = goal.failure_reasons || goal.why_behind || [];

  return (
    <div style={{ position: "fixed", inset: 0, zIndex: 50, display: "flex", alignItems: "flex-end", background: "rgba(10,9,8,0.7)" }} onClick={onClose}>
      <div
        style={{ width: "100%", maxWidth: 680, maxHeight: "90vh", overflowY: "auto", background: "var(--v3-bg-1)", border: "1px solid var(--v3-line-strong)", borderRadius: "20px 20px 0 0", padding: 24, display: "flex", flexDirection: "column", gap: 18, margin: "0 auto" }}
        onClick={(e) => e.stopPropagation()}
      >
        {/* header */}
        <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
          <span style={{ fontSize: 24 }}>{meta.icon}</span>
          <div style={{ flex: 1 }}>
            <p className="v3-eyebrow" style={{ color: "var(--v3-ink-4)", fontSize: 10, margin: 0 }}>GOAL DETAIL</p>
            <p style={{ fontSize: 16, fontWeight: 600, color: "var(--v3-ink-1)", margin: 0 }}>{goal.name || meta.label}</p>
          </div>
          <button onClick={onClose} style={{ background: "none", border: "none", color: "var(--v3-ink-3)", cursor: "pointer", padding: 4 }}>
            <X size={18} />
          </button>
        </div>

        <VerdictBanner verdict={verdict} shortfall={shortfall} />

        {/* Key metrics */}
        <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 10 }}>
          {targetFV != null && <MetricTile label="Target" value={inrCompact(targetFV)} />}
          {currentSIP != null && <MetricTile label="Current SIP" value={inrCompact(currentSIP) + "/mo"} sub={requiredSIP != null ? `Need ${inrCompact(requiredSIP)}/mo` : null} />}
          {horizonYrs != null && <MetricTile label="Horizon" value={`${horizonYrs} yrs`} />}
          {mcSuccess != null && <MetricTile label="MC success" value={`${mcSuccess.toFixed(0)}%`} sub="probability" />}
        </div>

        {/* Why behind */}
        {whyBehind.length > 0 && (
          <div>
            <p className="v3-eyebrow" style={{ color: "var(--v3-ink-3)", fontSize: 10, marginBottom: 8 }}>WHY YOU'RE BEHIND</p>
            {whyBehind.slice(0, 3).map((reason, i) => (
              <div key={i} style={{ display: "flex", gap: 10, padding: "8px 0", borderBottom: "1px solid var(--v3-line)", alignItems: "flex-start" }}>
                <AlertTriangle size={12} color="var(--v3-gold)" style={{ marginTop: 2, flexShrink: 0 }} />
                <span style={{ fontSize: 13, color: "var(--v3-ink-2)" }}>{typeof reason === "string" ? reason : reason.reason || reason.message}</span>
              </div>
            ))}
          </div>
        )}

        {/* Recovery paths */}
        {recoveryPaths.length > 0 && (
          <div>
            <p className="v3-eyebrow" style={{ color: "var(--v3-ink-3)", fontSize: 10, marginBottom: 8 }}>RECOVERY PATHS</p>
            <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
              {recoveryPaths.slice(0, 3).map((path, i) => (
                <div key={i} style={{ padding: "10px 14px", background: "var(--v3-bg-2)", border: "1px solid var(--v3-line)", borderRadius: 10, display: "flex", justifyContent: "space-between", alignItems: "center" }}>
                  <span style={{ fontSize: 13, color: "var(--v3-ink-1)" }}>{path.label || path.description || `Option ${i + 1}`}</span>
                  <span className="v3-data" style={{ fontSize: 11, color: "var(--v3-moss)" }}>
                    {path.on_track_pct != null ? `${path.on_track_pct.toFixed(0)}% on-track` : path.mc_success != null ? `${path.mc_success.toFixed(0)}% MC` : ""}
                  </span>
                </div>
              ))}
            </div>
          </div>
        )}

        {/* Scenarios */}
        {(scenarios.base != null || scenarios.bull != null) && (
          <div>
            <p className="v3-eyebrow" style={{ color: "var(--v3-ink-3)", fontSize: 10, marginBottom: 8 }}>SCENARIOS</p>
            <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr 1fr 1fr", gap: 8 }}>
              {[["Base", scenarios.base], ["Bull", scenarios.bull], ["Bear", scenarios.bear], ["Stress", scenarios.stress]].map(([label, val]) =>
                val != null ? (
                  <div key={label} style={{ textAlign: "center", padding: 10, background: "var(--v3-bg-2)", borderRadius: 8 }}>
                    <p className="v3-eyebrow" style={{ color: "var(--v3-ink-4)", fontSize: 9, margin: "0 0 4px" }}>{label.toUpperCase()}</p>
                    <p className="v3-data" style={{ fontSize: 13, color: "var(--v3-ink-1)", margin: 0 }}>{inrCompact(typeof val === "object" ? val.corpus ?? val.value : val)}</p>
                  </div>
                ) : null
              )}
            </div>
          </div>
        )}
      </div>
    </div>
  );
}

function MetricTile({ label, value, sub = null }) {
  return (
    <div style={{ padding: 12, background: "var(--v3-bg-2)", borderRadius: 10 }}>
      <p className="v3-eyebrow" style={{ color: "var(--v3-ink-4)", fontSize: 9, margin: "0 0 4px" }}>{label.toUpperCase()}</p>
      <p className="v3-data" style={{ fontSize: 15, color: "var(--v3-ink-1)", margin: 0 }}>{value}</p>
      {sub && <p style={{ fontSize: 10, color: "var(--v3-ink-4)", margin: "3px 0 0" }}>{sub}</p>}
    </div>
  );
}

// ─── add goal sheet ───────────────────────────────────────────────────────────

const GOAL_TYPES = [
  { id: "retirement", label: "Retirement", icon: "👴" },
  { id: "education",  label: "Education",  icon: "🎓" },
  { id: "home",       label: "Home",       icon: "🏠" },
  { id: "emergency",  label: "Emergency",  icon: "🛡️" },
  { id: "travel",     label: "Travel",     icon: "✈️" },
  { id: "other",      label: "Other",      icon: "🎯" },
];

function AddGoalSheet({ onClose, onCreated }) {
  const [step, setStep] = useState(1);
  const [form, setForm] = useState({ goal_type: "", name: "", target_amount: "", horizon_years: "", monthly_sip: "" });
  const [saving, setSaving] = useState(false);

  async function handleCreate() {
    setSaving(true);
    const body = {
      goal_type: form.goal_type,
      name: form.name || form.goal_type,
      target_amount: parseFloat(form.target_amount),
      horizon_years: parseInt(form.horizon_years, 10),
      monthly_sip: parseFloat(form.monthly_sip) || 0,
    };
    const res = await createGoal(body);
    setSaving(false);
    if (!res.error) { onCreated(); onClose(); }
  }

  return (
    <div style={{ position: "fixed", inset: 0, zIndex: 50, display: "flex", alignItems: "flex-end", background: "rgba(10,9,8,0.7)" }} onClick={onClose}>
      <div style={{ width: "100%", maxWidth: 520, background: "var(--v3-bg-1)", border: "1px solid var(--v3-line-strong)", borderRadius: "20px 20px 0 0", padding: 24, margin: "0 auto" }} onClick={(e) => e.stopPropagation()}>
        <div style={{ display: "flex", justifyContent: "space-between", marginBottom: 20 }}>
          <p style={{ fontSize: 16, fontWeight: 600, color: "var(--v3-ink-1)", margin: 0 }}>{step === 1 ? "Choose goal type" : step === 2 ? "Set your target" : "Review & create"}</p>
          <button onClick={onClose} style={{ background: "none", border: "none", color: "var(--v3-ink-3)", cursor: "pointer" }}><X size={18} /></button>
        </div>

        {step === 1 && (
          <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr 1fr", gap: 10 }}>
            {GOAL_TYPES.map((gt) => (
              <button
                key={gt.id}
                onClick={() => { setForm((f) => ({ ...f, goal_type: gt.id })); setStep(2); }}
                style={{ padding: 14, background: "var(--v3-bg-2)", border: "1px solid var(--v3-line)", borderRadius: 12, cursor: "pointer", display: "flex", flexDirection: "column", alignItems: "center", gap: 8 }}
              >
                <span style={{ fontSize: 24 }}>{gt.icon}</span>
                <span style={{ fontSize: 12, color: "var(--v3-ink-2)" }}>{gt.label}</span>
              </button>
            ))}
          </div>
        )}

        {step === 2 && (
          <div style={{ display: "flex", flexDirection: "column", gap: 14 }}>
            {[
              { key: "name", label: "Goal name (optional)", placeholder: "e.g. Child's MBA fund" },
              { key: "target_amount", label: "Target amount (₹)", placeholder: "e.g. 2500000" },
              { key: "horizon_years", label: "Years to goal", placeholder: "e.g. 15" },
              { key: "monthly_sip", label: "Current SIP / month (₹)", placeholder: "e.g. 15000" },
            ].map(({ key, label, placeholder }) => (
              <div key={key}>
                <p className="v3-eyebrow" style={{ color: "var(--v3-ink-4)", fontSize: 10, marginBottom: 6 }}>{label.toUpperCase()}</p>
                <input
                  value={form[key]}
                  onChange={(e) => setForm((f) => ({ ...f, [key]: e.target.value }))}
                  placeholder={placeholder}
                  style={{ width: "100%", padding: "10px 14px", background: "var(--v3-bg-2)", border: "1px solid var(--v3-line)", borderRadius: 10, fontSize: 14, color: "var(--v3-ink-1)", outline: "none", boxSizing: "border-box" }}
                />
              </div>
            ))}
            <div style={{ display: "flex", gap: 10, marginTop: 4 }}>
              <button onClick={() => setStep(1)} style={{ flex: 1, padding: "11px 0", background: "var(--v3-bg-2)", border: "1px solid var(--v3-line)", borderRadius: 10, fontSize: 13, color: "var(--v3-ink-2)", cursor: "pointer" }}>Back</button>
              <button
                onClick={handleCreate}
                disabled={saving || !form.target_amount || !form.horizon_years}
                style={{ flex: 2, padding: "11px 0", background: saving ? "var(--v3-bg-3)" : "var(--v3-saffron)", border: "none", borderRadius: 10, fontSize: 13, fontWeight: 600, color: saving ? "var(--v3-ink-3)" : "#000", cursor: saving ? "not-allowed" : "pointer" }}
              >
                {saving ? "Creating…" : "Create goal"}
              </button>
            </div>
          </div>
        )}
      </div>
    </div>
  );
}

// ─── error state ──────────────────────────────────────────────────────────────

function ErrorState({ onRetry }) {
  return (
    <div style={{ textAlign: "center", padding: "60px 24px", display: "flex", flexDirection: "column", alignItems: "center", gap: 14 }}>
      <AlertTriangle size={28} color="var(--v3-ink-4)" />
      <p style={{ color: "var(--v3-ink-3)", fontSize: 14, margin: 0 }}>Couldn't load goals</p>
      <button onClick={onRetry} style={{ display: "flex", alignItems: "center", gap: 6, padding: "8px 16px", background: "var(--v3-bg-2)", border: "1px solid var(--v3-line)", borderRadius: 999, fontSize: 13, color: "var(--v3-ink-2)", cursor: "pointer" }}>
        <RefreshCw size={13} /> Retry
      </button>
    </div>
  );
}

// ─── main screen ──────────────────────────────────────────────────────────────

export default function Goals() {
  const { viewport } = useOutletContext() || { viewport: "mobile" };
  const isDesktop = viewport === "desktop";
  const navigate = useNavigate();
  const [selectedGoal, setSelectedGoal] = useState(null);
  const [showAddSheet, setShowAddSheet] = useState(false);

  const { data, loading, error, refetch } = useGoals();
  const goals = data?.goals || [];

  // Consolidated stats
  const totalTarget = goals.reduce((s, g) => s + (g.target_amount ?? g.target_fv ?? 0), 0);
  const totalSIP = goals.reduce((s, g) => s + (g.monthly_sip ?? g.sip_amount ?? 0), 0);
  const onTrackCount = goals.filter((g) => (g.on_track_pct ?? 0) >= 70 || g.verdict === "ON_TRACK" || g.verdict === "AHEAD").length;
  const atRiskCount = goals.length - onTrackCount;
  const avgOnTrack = goals.length ? goals.reduce((s, g) => s + (g.on_track_pct ?? 50), 0) / goals.length : 0;

  const heroTitle = loading
    ? "Loading goals…"
    : data?.empty
    ? "Set up your financial goals to get started"
    : totalTarget > 0
    ? `${inrCompact(totalTarget)} target · ${goals.length} goal${goals.length !== 1 ? "s" : ""}`
    : `${goals.length} goal${goals.length !== 1 ? "s" : ""} · ${onTrackCount} on track`;

  async function handleDelete(goal, e) {
    e.stopPropagation();
    if (!window.confirm(`Remove goal "${goal.name || goalMeta(goal).label}"?`)) return;
    await deleteGoal(goal.id || goal._id);
    refetch();
  }

  return (
    <ScreenContainer variant={isDesktop ? "desktop" : "mobile"}>
      <TopBar variant={isDesktop ? "desktop" : "mobile"} eyebrow="Plan · Goals" title="Goals" />

      {error && !loading ? (
        <ErrorState onRetry={refetch} />
      ) : (
        <div style={{ display: "flex", flexDirection: "column", gap: isDesktop ? 26 : 18, paddingBottom: 80 }}>
          {/* Hero */}
          <HeroCard
            layout={isDesktop ? "desktop" : "mobile"}
            category="goal"
            priorityLabel={loading ? "Loading…" : "Consolidated"}
            title={heroTitle}
            description={
              isDesktop && goals.length > 0
                ? `Total SIP ${inrCompact(totalSIP)}/mo · ${onTrackCount} on track · ${atRiskCount} at risk`
                : null
            }
            viz={
              loading ? (
                <div style={{ width: "100%", height: 80, background: "var(--v3-bg-3)", borderRadius: 10 }} />
              ) : goals.length > 0 ? (
                <div style={{ display: "flex", flexDirection: "column", gap: 6, width: "100%" }}>
                  {goals.slice(0, 4).map((g, i) => {
                    const meta = goalMeta(g);
                    const onT = g.on_track_pct ?? 50;
                    return (
                      <div key={i} style={{ display: "flex", alignItems: "center", gap: 8 }}>
                        <span style={{ fontSize: 14, width: 20, textAlign: "center" }}>{meta.icon}</span>
                        <div style={{ flex: 1, height: 6, background: "var(--v3-bg-3)", borderRadius: 3 }}>
                          <div style={{ width: `${Math.min(onT, 100)}%`, height: "100%", borderRadius: 3, background: onT >= 80 ? "var(--v3-moss)" : onT >= 50 ? "var(--v3-gold)" : "var(--v3-crimson)" }} />
                        </div>
                        <span className="v3-data" style={{ fontSize: 10, color: "var(--v3-ink-3)", minWidth: 28 }}>{onT.toFixed(0)}%</span>
                      </div>
                    );
                  })}
                </div>
              ) : null
            }
            ctaText={data?.empty ? "Add your first goal →" : "Run a full review →"}
            onClick={data?.empty ? () => setShowAddSheet(true) : () => navigate("/v3/chat?q=Review+my+financial+goals")}
          />

          {/* Goal cards grid */}
          <section>
            <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", marginBottom: 12 }}>
              <SectionHead title="Your goals" count={loading ? "…" : `${goals.length} active`} />
              <button
                onClick={() => setShowAddSheet(true)}
                style={{ display: "flex", alignItems: "center", gap: 5, padding: "7px 12px", background: "var(--v3-saffron)", border: "none", borderRadius: 999, fontSize: 12, fontWeight: 600, color: "#000", cursor: "pointer" }}
              >
                <Plus size={13} /> Add goal
              </button>
            </div>

            {loading && (
              <div style={{ display: "grid", gridTemplateColumns: isDesktop ? "repeat(3, 1fr)" : "1fr 1fr", gap: 12 }}>
                {[1, 2, 3].map((i) => <div key={i} style={{ height: 160, background: "var(--v3-bg-2)", borderRadius: 14 }} />)}
              </div>
            )}

            {!loading && goals.length === 0 && (
              <div style={{ textAlign: "center", padding: "40px 24px", background: "var(--v3-bg-2)", borderRadius: 14, display: "flex", flexDirection: "column", alignItems: "center", gap: 12 }}>
                <Target size={28} color="var(--v3-ink-4)" />
                <p style={{ color: "var(--v3-ink-3)", fontSize: 14, margin: 0 }}>No goals yet. Add your first financial goal.</p>
                <button onClick={() => setShowAddSheet(true)} style={{ padding: "9px 18px", background: "var(--v3-saffron)", border: "none", borderRadius: 999, fontSize: 13, fontWeight: 600, color: "#000", cursor: "pointer" }}>
                  Add a goal
                </button>
              </div>
            )}

            {!loading && goals.length > 0 && (
              <div style={{ display: "grid", gridTemplateColumns: isDesktop ? "repeat(3, 1fr)" : "1fr 1fr", gap: 12 }}>
                {goals.map((goal, i) => {
                  const meta = goalMeta(goal);
                  const onT = goal.on_track_pct ?? 50;
                  const targetFV = goal.target_amount ?? goal.target_fv;
                  const sip = goal.monthly_sip ?? goal.sip_amount;
                  const horizonYrs = goal.horizon_years ?? goal.years_remaining;
                  return (
                    <button
                      key={goal.id || goal._id || i}
                      onClick={() => setSelectedGoal(goal)}
                      style={{ width: "100%", textAlign: "left", background: "var(--v3-bg-2)", border: "1px solid var(--v3-line)", borderRadius: 14, padding: 14, cursor: "pointer", position: "relative" }}
                    >
                      {/* Delete */}
                      <button
                        onClick={(e) => handleDelete(goal, e)}
                        style={{ position: "absolute", top: 10, right: 10, background: "none", border: "none", color: "var(--v3-ink-4)", cursor: "pointer", padding: 4 }}
                      >
                        <Trash2 size={12} />
                      </button>

                      <div style={{ display: "flex", alignItems: "center", gap: 8, marginBottom: 10 }}>
                        <span style={{ fontSize: 20 }}>{meta.icon}</span>
                        <span style={{ fontSize: 13, fontWeight: 600, color: "var(--v3-ink-1)", flex: 1, paddingRight: 20 }}>{goal.name || meta.label}</span>
                      </div>

                      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-end" }}>
                        <div style={{ display: "flex", flexDirection: "column", gap: 4 }}>
                          {targetFV != null && <span className="v3-data" style={{ fontSize: 12, color: "var(--v3-ink-1)" }}>{inrCompact(targetFV)}</span>}
                          {sip != null && <span style={{ fontSize: 10, color: "var(--v3-ink-4)" }}>{inrCompact(sip)}/mo</span>}
                          {horizonYrs != null && <span style={{ fontSize: 10, color: "var(--v3-ink-4)" }}>{horizonYrs}y horizon</span>}
                        </div>
                        <ProgressRing pct={onT} accent={meta.accent} size={44} />
                      </div>

                      <div style={{ marginTop: 8, padding: "4px 8px", borderRadius: 999, display: "inline-block", background: onT >= 80 ? "var(--v3-moss-soft)" : onT >= 50 ? "#D4AF3726" : "var(--v3-crimson-soft)" }}>
                        <span style={{ fontSize: 10, fontFamily: "var(--v3-font-mono)", color: onT >= 80 ? "var(--v3-moss)" : onT >= 50 ? "var(--v3-gold)" : "var(--v3-crimson)" }}>
                          {onT >= 80 ? "ON TRACK" : onT >= 50 ? "AT RISK" : "CRITICAL"}
                        </span>
                      </div>
                    </button>
                  );
                })}
              </div>
            )}
          </section>

          {/* Suggested prompts */}
          <div style={{ display: "flex", flexWrap: "wrap", gap: 8 }}>
            <TinyChip onClick={() => navigate("/v3/chat?q=Add+a+new+goal")}>Add a new goal</TinyChip>
            <TinyChip onClick={() => navigate("/v3/chat?q=Run+financial+snapshot+review")}>Financial snapshot</TinyChip>
            <TinyChip onClick={() => navigate("/v3/chat?q=Compare+risk+allocations+across+my+goals")}>Compare allocations</TinyChip>
          </div>
        </div>
      )}

      {/* Goal detail sheet */}
      {selectedGoal && <GoalDetail goal={selectedGoal} onClose={() => setSelectedGoal(null)} />}

      {/* Add goal sheet */}
      {showAddSheet && <AddGoalSheet onClose={() => setShowAddSheet(false)} onCreated={refetch} />}
    </ScreenContainer>
  );
}
