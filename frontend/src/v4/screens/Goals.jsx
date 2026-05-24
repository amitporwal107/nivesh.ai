/**
 * V4 Goals Dashboard — goal cards + financial snapshot.
 * Endpoints:
 *   GET /api/goals          → list of goals with simulation
 *   GET /api/goals/snapshot → user's financial snapshot (age/income/risk)
 */
import React, { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import { useAuth } from "@/context/AuthContext";
import api from "../api/client";
import {
  DashboardShell,
  SectionHeader,
  StatTile,
  EmptyState,
  Skeleton,
  formatInr,
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

export default function Goals() {
  const navigate = useNavigate();
  const { user, loading: authLoading } = useAuth();
  const [loading, setLoading] = useState(true);
  const [goals, setGoals] = useState([]);
  const [snapshot, setSnapshot] = useState(null);
  const [err, setErr] = useState(null);

  useEffect(() => {
    if (!user) return;
    setLoading(true);
    Promise.allSettled([
      api.get("/api/goals"),
      api.get("/api/goals/snapshot"),
    ]).then(([goalsRes, snapRes]) => {
      if (goalsRes.status === "fulfilled") {
        const raw = goalsRes.value;
        setGoals(Array.isArray(raw) ? raw : raw?.goals || []);
      }
      if (snapRes.status === "fulfilled") setSnapshot(snapRes.value);
      if (goalsRes.status === "rejected" && snapRes.status === "rejected") {
        setErr(goalsRes.reason);
      }
      setLoading(false);
    });
  }, [user]);

  if (authLoading) return null;
  if (!user) { navigate("/onboarding", { replace: true }); return null; }

  const snap = snapshot?.snapshot || snapshot;

  return (
    <DashboardShell>
      <div style={pageTitleStyle}>
        <div style={{ fontFamily: "var(--v4-display)", fontSize: 30, color: "var(--v4-ink)", marginBottom: 6 }}>
          Goals
        </div>
        <div style={{ fontSize: 13, color: "var(--v4-ink-dim)" }}>
          Track your financial goals and see how your portfolio aligns.
        </div>
      </div>

      {loading && (
        <div style={{ display: "flex", flexDirection: "column", gap: 12 }}>
          {[...Array(3)].map((_, i) => <Skeleton key={i} height={120} />)}
        </div>
      )}

      {!loading && err && (
        <EmptyState icon="⚡" title="Could not load goals" sub={err.message || String(err)} />
      )}

      {!loading && !err && (
        <>
          {/* Financial snapshot */}
          {snap && (
            <section style={{ marginBottom: 36 }}>
              <SectionHeader>Your financial profile</SectionHeader>
              <div style={snapshotGridStyle}>
                {snap.age != null && (
                  <StatTile label="Age" value={snap.age} sub="years" />
                )}
                {snap.monthly_income != null && (
                  <StatTile label="Monthly income" value={formatInr(snap.monthly_income)} />
                )}
                {snap.monthly_expenses != null && (
                  <StatTile label="Monthly expenses" value={formatInr(snap.monthly_expenses)} />
                )}
                {snap.risk_profile && (
                  <StatTile
                    label="Risk profile"
                    value={RISK_LABELS[snap.risk_profile] || snap.risk_profile}
                  />
                )}
                {snap.net_worth != null && (
                  <StatTile label="Net worth" value={formatInr(snap.net_worth)} />
                )}
              </div>
            </section>
          )}

          {/* Goals list */}
          {goals.length === 0 ? (
            <EmptyState
              icon="◎"
              title="No goals set yet"
              sub="Add your financial goals in the profile section. We'll track your progress and suggest optimisations."
            />
          ) : (
            <section>
              <SectionHeader>
                {goals.length} {goals.length === 1 ? "goal" : "goals"}
              </SectionHeader>
              <div style={{ display: "flex", flexDirection: "column", gap: 14 }}>
                {goals.map((goal, i) => (
                  <GoalCard key={goal.id || goal.goal_id || i} goal={goal} />
                ))}
              </div>
            </section>
          )}
        </>
      )}
    </DashboardShell>
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

  const progressPct = (target && current)
    ? Math.min(100, (Number(current) / Number(target)) * 100)
    : null;

  const years = goal.target_year
    ? goal.target_year - new Date().getFullYear()
    : goal.horizon_years;

  return (
    <div style={goalCardStyle}>
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start", marginBottom: 12, flexWrap: "wrap", gap: 8 }}>
        <div>
          <div style={{ fontFamily: "var(--v4-display)", fontSize: 18, color: "var(--v4-ink)", marginBottom: 4 }}>
            {name}
          </div>
          {goal.category && (
            <div style={{ fontFamily: "var(--v4-mono)", fontSize: 9, letterSpacing: 1, color: "var(--v4-ink-faint)", textTransform: "uppercase" }}>
              {goal.category}
            </div>
          )}
        </div>
        <div style={{ textAlign: "right" }}>
          {onTrackPct != null && (
            <div style={{ fontFamily: "var(--v4-display)", fontSize: 20, color: tone }}>
              {Math.round(onTrackPct)}%
            </div>
          )}
          <div style={{ fontFamily: "var(--v4-mono)", fontSize: 9, color: tone, letterSpacing: 1 }}>
            {onTrackPct >= 80 ? "ON TRACK" : onTrackPct >= 50 ? "NEEDS WORK" : "AT RISK"}
          </div>
        </div>
      </div>

      {/* Amounts */}
      <div style={{ display: "flex", gap: 24, marginBottom: 14, flexWrap: "wrap" }}>
        {target && (
          <div>
            <div style={{ fontFamily: "var(--v4-mono)", fontSize: 9, color: "var(--v4-ink-faint)", marginBottom: 2 }}>TARGET</div>
            <div style={{ fontFamily: "var(--v4-display)", fontSize: 15, color: "var(--v4-ink)" }}>{formatInr(target)}</div>
          </div>
        )}
        {current && (
          <div>
            <div style={{ fontFamily: "var(--v4-mono)", fontSize: 9, color: "var(--v4-ink-faint)", marginBottom: 2 }}>CURRENT</div>
            <div style={{ fontFamily: "var(--v4-display)", fontSize: 15, color: "var(--v4-ink)" }}>{formatInr(current)}</div>
          </div>
        )}
        {years != null && years > 0 && (
          <div>
            <div style={{ fontFamily: "var(--v4-mono)", fontSize: 9, color: "var(--v4-ink-faint)", marginBottom: 2 }}>HORIZON</div>
            <div style={{ fontFamily: "var(--v4-display)", fontSize: 15, color: "var(--v4-ink)" }}>{years}y</div>
          </div>
        )}
      </div>

      {/* Progress bar */}
      {progressPct != null && (
        <div style={{ marginBottom: 14 }}>
          <div style={{ height: 6, borderRadius: 3, background: "var(--v4-line-strong)", overflow: "hidden" }}>
            <div style={{ height: "100%", width: `${progressPct}%`, background: tone, borderRadius: 3, transition: "width 0.5s var(--v4-ease)" }} />
          </div>
          <div style={{ fontFamily: "var(--v4-mono)", fontSize: 9, color: "var(--v4-ink-faint)", marginTop: 3 }}>
            {progressPct.toFixed(1)}% funded
          </div>
        </div>
      )}

      {/* Simulation hints */}
      {(sipRequired || shortfall) && (
        <div style={{ display: "flex", gap: 20, padding: "10px 14px", background: "var(--v4-s1)", border: "1px solid var(--v4-line)", borderRadius: "var(--v4-r-sm)", flexWrap: "wrap" }}>
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

/* ─── Styles ─── */

const pageTitleStyle = { marginBottom: 32 };

const snapshotGridStyle = {
  display: "grid",
  gridTemplateColumns: "repeat(auto-fit, minmax(160px, 1fr))",
  gap: 14,
};

const goalCardStyle = {
  background: "linear-gradient(165deg, var(--v4-s2), var(--v4-s1))",
  border: "1px solid var(--v4-line)",
  borderRadius: "var(--v4-r-lg)",
  padding: "20px 22px",
};
