/**
 * V4 Goals Dashboard — ① Insight · ② Recommendations · ③ Apply
 * Endpoints:
 *   GET /api/goals          → list of goals with simulation
 *   GET /api/goals/snapshot → user's financial snapshot (age/income/risk)
 *   GET /api/plans/active   → domain-filtered recommendations
 */
import React, { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import { useAuth } from "@/context/AuthContext";
import api from "../api/client";
import {
  DashboardShell, StatTile, EmptyState, Skeleton,
  RecommendationCard, ApplyCard, HlBar, formatInr,
} from "../components/DashboardShell";

const TRACK_TONE = (pct) => {
  if (pct == null) return "var(--v4-ink-faint)";
  if (pct >= 80) return "var(--v4-moss)";
  if (pct >= 50) return "var(--v4-gold)";
  return "var(--v4-rust)";
};

const RISK_LABELS = {
  conservative: "Conservative",
  moderately_conservative: "Mod. Conservative",
  moderate: "Moderate",
  moderately_aggressive: "Mod. Aggressive",
  aggressive: "Aggressive",
};

const GOAL_CODES = new Set([
  "SIP_INCREASE", "SIP_STEP_UP", "GOAL_SHORTFALL",
  "GOAL_AT_RISK", "LUMPSUM_TOPUP", "HORIZON_EXTENSION",
]);

export default function Goals() {
  const navigate = useNavigate();
  const { user, loading: authLoading } = useAuth();

  const [loading, setLoading]   = useState(true);
  const [goals, setGoals]       = useState([]);
  const [snapshot, setSnapshot] = useState(null);
  const [plan, setPlan]         = useState(null);
  const [err, setErr]           = useState(null);
  const [accepted, setAccepted] = useState(new Set());

  useEffect(() => {
    if (!user) return;
    setLoading(true);
    Promise.allSettled([
      api.get("/api/goals"),
      api.get("/api/goals/snapshot"),
      api.get("/api/plans/active"),
    ]).then(([goalsRes, snapRes, planRes]) => {
      if (goalsRes.status === "fulfilled") {
        const raw = goalsRes.value;
        setGoals(Array.isArray(raw) ? raw : raw?.goals || []);
      } else setErr(goalsRes.reason);
      if (snapRes.status === "fulfilled") setSnapshot(snapRes.value);
      if (planRes.status === "fulfilled") setPlan(planRes.value);
      setLoading(false);
    });
  }, [user]);

  if (authLoading) return null;
  if (!user) { navigate("/onboarding", { replace: true }); return null; }

  const snap = snapshot?.snapshot || snapshot;

  /* badge */
  const atRisk = goals.filter(g => (g.on_track_pct ?? 100) < 50).length;
  const badge = atRisk > 0 ? `${atRisk} at risk` : goals.length > 0 ? "On track" : undefined;
  const badgeTone = atRisk > 0 ? "rust" : "moss";

  /* ② filter */
  const allActions = plan?.plan?.actions || [];
  const domainRecs = allActions.filter(a =>
    (a.reason_codes || []).some(c => GOAL_CODES.has(c))
    && (a.status || "").toUpperCase() !== "COMPLETED"
  );
  const recs = domainRecs.length > 0
    ? domainRecs.slice(0, 4)
    : allActions.filter(a => ["ADD", "REVIEW"].includes((a.type || "").toUpperCase())
        && (a.status || "").toUpperCase() !== "COMPLETED").slice(0, 3);

  return (
    <DashboardShell title="Goals" badge={badge} badgeTone={badgeTone}>
      {loading && (
        <div style={{ display: "flex", flexDirection: "column", gap: 12 }}>
          {[...Array(3)].map((_, i) => <Skeleton key={i} height={120} />)}
        </div>
      )}
      {!loading && err && <EmptyState icon="⚡" title="Could not load goals" sub={err.message || String(err)} />}

      {!loading && !err && (
        <>
          {/* ① Insight */}
          <div style={eyebrowStyle}>① Insight</div>

          {/* Financial snapshot */}
          {snap && (
            <div style={snapCardStyle}>
              <div style={cardHeaderStyle}>
                <span style={monoLabelStyle}>Your financial profile</span>
              </div>
              <div style={{ padding: "12px 16px 14px", display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(120px,1fr))", gap: 12 }}>
                {snap.age != null && <SnapItem label="Age" value={`${snap.age}y`} />}
                {snap.monthly_income != null && <SnapItem label="Income / mo" value={formatInr(snap.monthly_income)} />}
                {snap.monthly_expenses != null && <SnapItem label="Expenses / mo" value={formatInr(snap.monthly_expenses)} />}
                {snap.risk_profile && <SnapItem label="Risk" value={RISK_LABELS[snap.risk_profile] || snap.risk_profile} />}
                {snap.net_worth != null && <SnapItem label="Net worth" value={formatInr(snap.net_worth)} />}
              </div>
            </div>
          )}

          {/* Goal stats row */}
          {goals.length > 0 && (
            <div style={statsRowStyle}>
              <StatTile label="Goals tracked" value={goals.length} />
              <StatTile label="On track" value={goals.filter(g => (g.on_track_pct ?? 0) >= 80).length} tone="var(--v4-moss)" />
              <StatTile label="At risk" value={atRisk} tone={atRisk > 0 ? "var(--v4-rust)" : "var(--v4-ink-faint)"} />
            </div>
          )}

          {/* Goals list */}
          {goals.length === 0 ? (
            <EmptyState
              icon="◎"
              title="No goals set yet"
              sub="Add your financial goals in the profile section. We'll track progress and suggest optimisations."
            />
          ) : (
            <div style={{ display: "flex", flexDirection: "column", gap: 12, marginBottom: 18 }}>
              {goals.map((goal, i) => (
                <GoalCard key={goal.id || goal.goal_id || i} goal={goal} />
              ))}
            </div>
          )}

          {/* ② Recommendations */}
          {recs.length > 0 && (
            <>
              <HlBar>② Recommendations · ranked by priority</HlBar>
              <div style={{ display: "flex", flexDirection: "column", gap: 8, marginBottom: 14 }}>
                {recs.map(action => (
                  <RecommendationCard
                    key={action.action_id || action.id}
                    action={action}
                    accepted={accepted.has(action.action_id || action.id)}
                    onAccept={() => setAccepted(s => new Set([...s, action.action_id || action.id]))}
                    onSkip={() => setAccepted(s => { const n = new Set(s); n.delete(action.action_id || action.id); return n; })}
                  />
                ))}
              </div>
            </>
          )}

          {/* ③ Apply */}
          <ApplyCard
            metricLabel={null}
            before={null}
            after={null}
            acceptedCount={accepted.size}
            onSend={() => navigate("/plan")}
          />
        </>
      )}
    </DashboardShell>
  );
}

function SnapItem({ label, value }) {
  return (
    <div>
      <div style={{ fontFamily: "var(--v4-mono)", fontSize: 8, letterSpacing: 1, color: "var(--v4-ink-faint)", textTransform: "uppercase", marginBottom: 3 }}>{label}</div>
      <div style={{ fontFamily: "var(--v4-display)", fontSize: 14, fontWeight: 600, color: "var(--v4-ink)" }}>{value}</div>
    </div>
  );
}

function GoalCard({ goal }) {
  const name = goal.name || goal.goal_name || goal.title || "Goal";
  const target = goal.target_amount || goal.target_value;
  const current = goal.current_amount || goal.current_value;
  const onTrackPct = goal.on_track_pct;
  const tone = TRACK_TONE(onTrackPct);
  const sim = goal.last_simulation || goal.simulation || {};
  const sipRequired = sim.required_sip_rs || sim.required_sip;
  const shortfall = sim.shortfall_rs || sim.shortfall;
  const progressPct = (target && current) ? Math.min(100, (Number(current) / Number(target)) * 100) : null;
  const years = goal.target_year ? goal.target_year - new Date().getFullYear() : goal.horizon_years;
  const trackLabel = onTrackPct >= 80 ? "ON TRACK" : onTrackPct >= 50 ? "NEEDS WORK" : "AT RISK";

  return (
    <div style={goalCardStyle}>
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start", marginBottom: 12, flexWrap: "wrap", gap: 8 }}>
        <div>
          <div style={{ fontFamily: "var(--v4-display)", fontSize: 17, fontWeight: 600, color: "var(--v4-ink)", marginBottom: 4 }}>{name}</div>
          {goal.category && (
            <div style={{ fontFamily: "var(--v4-mono)", fontSize: 9, letterSpacing: 1, color: "var(--v4-ink-faint)", textTransform: "uppercase" }}>{goal.category}</div>
          )}
        </div>
        {onTrackPct != null && (
          <div style={{ textAlign: "right" }}>
            <div style={{ fontFamily: "var(--v4-display)", fontSize: 20, fontWeight: 600, color: tone }}>{Math.round(onTrackPct)}%</div>
            <div style={{ fontFamily: "var(--v4-mono)", fontSize: 8.5, color: tone, letterSpacing: 0.8 }}>{trackLabel}</div>
          </div>
        )}
      </div>

      <div style={{ display: "flex", gap: 20, marginBottom: 12, flexWrap: "wrap" }}>
        {target && <AmtItem label="Target" value={formatInr(target)} />}
        {current && <AmtItem label="Current" value={formatInr(current)} />}
        {years != null && years > 0 && <AmtItem label="Horizon" value={`${years}y`} />}
      </div>

      {progressPct != null && (
        <div style={{ marginBottom: 10 }}>
          <div style={{ height: 5, borderRadius: 3, background: "var(--v4-line-strong)", overflow: "hidden" }}>
            <div style={{ height: "100%", width: `${progressPct}%`, background: tone, borderRadius: 3, transition: "width .5s var(--v4-ease)" }} />
          </div>
          <div style={{ fontFamily: "var(--v4-mono)", fontSize: 9, color: "var(--v4-ink-faint)", marginTop: 3 }}>{progressPct.toFixed(1)}% funded</div>
        </div>
      )}

      {(sipRequired || shortfall) && (
        <div style={{ display: "flex", gap: 20, padding: "9px 12px", background: "var(--v4-s1)", border: "1px solid var(--v4-line)", borderRadius: 8, flexWrap: "wrap" }}>
          {sipRequired && (
            <div style={{ fontFamily: "var(--v4-mono)", fontSize: 10, color: "var(--v4-ink-mute)" }}>
              Required SIP: <span style={{ color: "var(--v4-saffron)" }}>{formatInr(sipRequired)}/mo</span>
            </div>
          )}
          {shortfall && (
            <div style={{ fontFamily: "var(--v4-mono)", fontSize: 10, color: "var(--v4-ink-mute)" }}>
              Shortfall: <span style={{ color: "var(--v4-rust)" }}>{formatInr(shortfall)}</span>
            </div>
          )}
        </div>
      )}
    </div>
  );
}

function AmtItem({ label, value }) {
  return (
    <div>
      <div style={{ fontFamily: "var(--v4-mono)", fontSize: 8.5, letterSpacing: 1, color: "var(--v4-ink-faint)", textTransform: "uppercase", marginBottom: 2 }}>{label}</div>
      <div style={{ fontFamily: "var(--v4-display)", fontSize: 14, color: "var(--v4-ink)" }}>{value}</div>
    </div>
  );
}

const eyebrowStyle   = { fontFamily: "var(--v4-mono)", fontSize: 8, letterSpacing: 1.6, color: "var(--v4-ink-faint)", textTransform: "uppercase", marginBottom: 10 };
const snapCardStyle  = { background: "linear-gradient(165deg, var(--v4-s2), var(--v4-s1))", border: "1px solid var(--v4-line)", borderRadius: "var(--v4-r-lg)", overflow: "hidden", marginBottom: 12 };
const cardHeaderStyle = { padding: "11px 16px 8px", borderBottom: "1px solid var(--v4-line)" };
const monoLabelStyle  = { fontFamily: "var(--v4-mono)", fontSize: 8.5, letterSpacing: 1.1, color: "var(--v4-ink-mute)", textTransform: "uppercase" };
const statsRowStyle  = { display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(120px,1fr))", gap: 10, marginBottom: 14 };
const goalCardStyle  = { background: "linear-gradient(165deg, var(--v4-s2), var(--v4-s1))", border: "1px solid var(--v4-line)", borderRadius: "var(--v4-r-lg)", padding: "16px 18px" };
