/**
 * V4 Action Plan — Plan board with todo / done / skip groups.
 * Endpoint: GET /api/plans/active
 */
import React, { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import { useAuth } from "@/context/AuthContext";
import api from "../api/client";
import {
  DashboardShell, EmptyState, Skeleton, HlBar, formatInr,
} from "../components/DashboardShell";

const ACTION_META = {
  EXIT:   { tone: "var(--v4-rust)",     label: "Exit",   icon: "↗" },
  ADD:    { tone: "var(--v4-moss)",     label: "Add",    icon: "+" },
  TRIM:   { tone: "var(--v4-gold)",    label: "Trim",   icon: "↘" },
  HOLD:   { tone: "var(--v4-indigo)",  label: "Hold",   icon: "◆" },
  REVIEW: { tone: "var(--v4-saffron)", label: "Review", icon: "◎" },
};

export default function ActionPlan() {
  const navigate = useNavigate();
  const { user, loading: authLoading } = useAuth();

  const [loading, setLoading] = useState(true);
  const [plan, setPlan]       = useState(null);
  const [err, setErr]         = useState(null);
  const [done, setDone]       = useState(new Set());
  const [skipped, setSkipped] = useState(new Set());

  useEffect(() => {
    if (!user) return;
    setLoading(true);
    api.get("/api/plans/active")
      .then(setPlan)
      .catch(setErr)
      .finally(() => setLoading(false));
  }, [user]);

  if (authLoading) return null;
  if (!user) { navigate("/onboarding", { replace: true }); return null; }

  const actions = plan?.plan?.actions || [];
  /* Health projection — prefer explicit before/after, else infer from improvements dict. */
  const baseScore =
    plan?.health_before ??
    plan?.plan?.health_score_before ??
    plan?.portfolio_score ??
    null;
  const projectedScore =
    plan?.health_after ??
    plan?.plan?.health_score_after ??
    (baseScore != null ? baseScore + (plan?.plan?.improvements?.health_delta || 0) : null);

  /* partition: local state wins over API status */
  const todoList    = actions.filter(a => {
    const id = a.action_id || a.id;
    const apiStatus = (a.status || "").toUpperCase();
    if (done.has(id) || skipped.has(id)) return false;
    return apiStatus !== "COMPLETED" && apiStatus !== "SKIPPED";
  });
  const doneList    = actions.filter(a => {
    const id = a.action_id || a.id;
    return done.has(id) || (a.status || "").toUpperCase() === "COMPLETED";
  });
  const skippedList = actions.filter(a => {
    const id = a.action_id || a.id;
    if (done.has(id)) return false;
    return skipped.has(id) || (a.status || "").toUpperCase() === "SKIPPED";
  });

  const totalActions = todoList.length + doneList.length;
  const doneCount    = doneList.length;
  const progressPct  = totalActions > 0 ? (doneCount / totalActions) * 100 : 0;

  const markDone = (id) => {
    setDone(s => new Set([...s, id]));
    setSkipped(s => { const n = new Set(s); n.delete(id); return n; });
  };
  const markSkip = (id) => {
    setSkipped(s => new Set([...s, id]));
    setDone(s => { const n = new Set(s); n.delete(id); return n; });
  };
  const undoDone = (id) => setDone(s => { const n = new Set(s); n.delete(id); return n; });

  return (
    <DashboardShell title="Action Plan">
      {loading && (
        <div style={{ display: "flex", flexDirection: "column", gap: 12 }}>
          {[...Array(4)].map((_, i) => <Skeleton key={i} height={100} />)}
        </div>
      )}
      {!loading && err && <EmptyState icon="⚡" title="Could not load plan" sub={err.message || String(err)} />}
      {!loading && !plan?.plan && (
        <EmptyState
          title="No active plan"
          sub="Your personalised action plan will appear here after your portfolio is analysed. Upload a CAS to get started."
        />
      )}

      {!loading && plan?.plan && (
        <>
          {/* Hero — projected health score (matches prototype "lifts health to 94") */}
          <div style={heroCardStyle}>
            <div style={{ display: "flex", alignItems: "center", gap: 18, flexWrap: "wrap" }}>
              <svg viewBox="0 0 92 92" width={92} height={92} style={{ flexShrink: 0 }}>
                <circle cx="46" cy="46" r="34" fill="none" stroke="var(--v4-line-strong)" strokeWidth="9" />
                <circle
                  cx="46" cy="46" r="34" fill="none"
                  stroke="var(--v4-moss)"
                  strokeWidth="9"
                  strokeDasharray={`${(progressPct / 100) * 2 * Math.PI * 34} ${2 * Math.PI * 34}`}
                  strokeLinecap="round"
                  transform="rotate(-90 46 46)"
                  style={{ transition: "stroke-dasharray .7s var(--v4-ease)" }}
                />
                <text x="46" y="42" textAnchor="middle" fontFamily="var(--v4-display)" fontSize="22" fontWeight="600" fill="var(--v4-ink)">
                  {projectedScore != null ? Math.round(projectedScore) : baseScore != null ? Math.round(baseScore) : "—"}
                </text>
                <text x="46" y="58" textAnchor="middle" fontFamily="monospace" fontSize="7" letterSpacing="1" fill="var(--v4-ink-faint)">
                  PROJECTED
                </text>
              </svg>
              <div style={{ flex: 1 }}>
                <div style={{ fontFamily: "var(--v4-display)", fontSize: 19, fontWeight: 600, letterSpacing: "-.02em", color: "var(--v4-ink)", marginBottom: 5 }}>
                  {projectedScore != null && baseScore != null && projectedScore > baseScore
                    ? <>Your plan lifts health to <span style={{ color: "var(--v4-moss)" }}>{Math.round(projectedScore)}</span></>
                    : totalActions === 0
                      ? "No actions in this plan"
                      : doneCount === totalActions
                        ? "All actions complete"
                        : `${totalActions} actions to lift your portfolio`}
                </div>
                <p style={{ fontSize: 12, color: "var(--v4-ink-dim)", margin: "0 0 9px", lineHeight: 1.5 }}>
                  {doneCount} of {totalActions} actions done · gathered across dashboards.
                </p>
                {/* Progress bar (gradient gold→saffron per prototype) */}
                <div style={{ height: 7, borderRadius: 4, background: "var(--v4-s3)", overflow: "hidden" }}>
                  <div style={{ height: "100%", width: `${progressPct}%`, background: "linear-gradient(90deg, var(--v4-gold), var(--v4-saffron))", borderRadius: 4, transition: "width .5s var(--v4-ease)" }} />
                </div>
              </div>
            </div>
          </div>

          {/* TO DO */}
          {todoList.length > 0 && (
            <Group
              label="TO DO"
              count={todoList.length}
              labelTone="var(--v4-saffron)"
              actions={todoList}
              markDone={markDone}
              markSkip={markSkip}
              showActions
            />
          )}

          {/* DONE */}
          {doneList.length > 0 && (
            <Group
              label="DONE"
              count={doneList.length}
              labelTone="var(--v4-moss)"
              actions={doneList}
              undoDone={undoDone}
              showDoneUndo
            />
          )}

          {/* SKIPPED */}
          {skippedList.length > 0 && (
            <Group
              label="SKIPPED"
              count={skippedList.length}
              labelTone="var(--v4-ink-faint)"
              actions={skippedList}
            />
          )}
        </>
      )}
    </DashboardShell>
  );
}

function Group({ label, count, labelTone, actions, markDone, markSkip, undoDone, showActions, showDoneUndo }) {
  return (
    <div style={{ marginBottom: 18 }}>
      <HlBar tone={labelTone}>{label} · {count}</HlBar>
      <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
        {actions.map(action => {
          const id = action.action_id || action.id;
          return (
            <PlanActionCard
              key={id}
              action={action}
              onDone={showActions ? () => markDone(id) : null}
              onSkip={showActions ? () => markSkip(id) : null}
              onUndo={showDoneUndo ? () => undoDone(id) : null}
            />
          );
        })}
      </div>
    </div>
  );
}

function PlanActionCard({ action, onDone, onSkip, onUndo }) {
  const type = (action.type || "REVIEW").toUpperCase();
  const meta = ACTION_META[type] || ACTION_META.REVIEW;
  const title = action.asset_name || action.title || action.action || "Action";
  const detail = action.reason_text || action.detail;
  const amount = action.amount;
  const priority = String(action.priority || "").toLowerCase();

  return (
    <div style={planCardStyle(meta.tone)}>
      <div style={{ display: "flex", alignItems: "flex-start", gap: 12 }}>
        <div style={iconStyle(meta.tone)}>{meta.icon}</div>
        <div style={{ flex: 1, minWidth: 0 }}>
          <div style={{ display: "flex", gap: 6, marginBottom: 3, flexWrap: "wrap", alignItems: "center" }}>
            <span style={{ fontFamily: "var(--v4-mono)", fontSize: 8.5, letterSpacing: 1.2, color: meta.tone, textTransform: "uppercase" }}>{meta.label}</span>
            {priority && <span style={{ fontFamily: "var(--v4-mono)", fontSize: 8.5, color: "var(--v4-ink-faint)", letterSpacing: 0.8 }}>· {priority}</span>}
            {amount && <span style={{ marginLeft: "auto", fontFamily: "var(--v4-display)", fontSize: 12, color: "var(--v4-ink)" }}>{formatInr(amount)}</span>}
          </div>
          <div style={{ fontFamily: "var(--v4-display)", fontSize: 15, color: "var(--v4-ink)", marginBottom: detail ? 3 : 0 }}>{title}</div>
          {detail && <div style={{ fontSize: 12, color: "var(--v4-ink-dim)", lineHeight: 1.5 }}>{detail}</div>}
          {(onDone || onSkip || onUndo) && (
            <div style={{ display: "flex", gap: 8, marginTop: 10 }}>
              {onDone && <button type="button" onClick={onDone} style={btnDone}>Mark done</button>}
              {onSkip && <button type="button" onClick={onSkip} style={btnSkip}>Skip</button>}
              {onUndo && <button type="button" onClick={onUndo} style={btnSkip}>Undo</button>}
            </div>
          )}
        </div>
      </div>
    </div>
  );
}

const heroCardStyle = { background: "linear-gradient(168deg, var(--v4-hero-a), var(--v4-hero-b))", border: "1px solid var(--v4-line-strong)", borderRadius: 16, padding: "16px 18px", marginBottom: 20 };
const planCardStyle = (tone) => ({ background: "linear-gradient(165deg, var(--v4-s2), var(--v4-s1))", border: "1px solid var(--v4-line)", borderLeft: `3px solid ${tone}`, borderRadius: "var(--v4-r-md)", padding: "14px 16px" });
const iconStyle = (tone) => ({ width: 30, height: 30, borderRadius: 7, background: `${tone}18`, border: `1px solid ${tone}40`, display: "grid", placeItems: "center", flexShrink: 0, color: tone, fontSize: 13 });
const btnDone = { fontFamily: "var(--v4-mono)", fontSize: 9, letterSpacing: 0.8, textTransform: "uppercase", padding: "6px 14px", borderRadius: 999, cursor: "pointer", background: "rgba(99,190,123,.12)", border: "1px solid rgba(99,190,123,.35)", color: "var(--v4-moss)" };
const btnSkip = { fontFamily: "var(--v4-mono)", fontSize: 9, letterSpacing: 0.8, textTransform: "uppercase", padding: "6px 14px", borderRadius: 999, cursor: "pointer", background: "var(--v4-s1)", border: "1px solid var(--v4-line)", color: "var(--v4-ink-faint)" };
