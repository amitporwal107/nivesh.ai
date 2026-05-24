/**
 * V4 Action Plan Dashboard — full plan board with all actions.
 * Endpoint: GET /api/plans/active
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

const ACTION_META = {
  EXIT:   { tone: "var(--v4-rust)",    label: "Exit",   icon: "↗" },
  ADD:    { tone: "var(--v4-moss)",    label: "Add",    icon: "+" },
  TRIM:   { tone: "var(--v4-gold)",   label: "Trim",   icon: "↘" },
  HOLD:   { tone: "var(--v4-indigo)", label: "Hold",   icon: "◆" },
  REVIEW: { tone: "var(--v4-saffron)", label: "Review", icon: "◎" },
};

const STATUS_STYLE = {
  PENDING:     { color: "var(--v4-saffron)", label: "Pending" },
  IN_PROGRESS: { color: "var(--v4-gold)",    label: "In progress" },
  COMPLETED:   { color: "var(--v4-moss)",    label: "Done" },
  SKIPPED:     { color: "var(--v4-ink-faint)", label: "Skipped" },
};

const PRIORITY_TONE = {
  high:   "var(--v4-rust)",
  medium: "var(--v4-gold)",
  low:    "var(--v4-moss)",
  1: "var(--v4-rust)",
  2: "var(--v4-gold)",
  3: "var(--v4-moss)",
};

export default function ActionPlan() {
  const navigate = useNavigate();
  const { user, loading: authLoading } = useAuth();
  const [loading, setLoading] = useState(true);
  const [plan, setPlan] = useState(null);
  const [err, setErr] = useState(null);
  const [filter, setFilter] = useState("ALL");

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
  const pendingCount = actions.filter(a => (a.status || "").toUpperCase() === "PENDING").length;
  const completedCount = actions.filter(a => (a.status || "").toUpperCase() === "COMPLETED").length;

  const typeCounts = actions.reduce((acc, a) => {
    const t = (a.type || "REVIEW").toUpperCase();
    acc[t] = (acc[t] || 0) + 1;
    return acc;
  }, {});

  const filters = ["ALL", ...Object.keys(typeCounts).sort()];
  const visible = filter === "ALL"
    ? actions
    : actions.filter(a => (a.type || "").toUpperCase() === filter);

  return (
    <DashboardShell>
      <div style={pageTitleStyle}>
        <div style={{ fontFamily: "var(--v4-display)", fontSize: 30, color: "var(--v4-ink)", marginBottom: 6 }}>
          Action Plan
        </div>
        <div style={{ fontSize: 13, color: "var(--v4-ink-dim)" }}>
          Every recommended action for your portfolio — prioritised by impact.
        </div>
      </div>

      {loading && (
        <div style={{ display: "flex", flexDirection: "column", gap: 12 }}>
          {[...Array(4)].map((_, i) => <Skeleton key={i} height={100} />)}
        </div>
      )}

      {!loading && err && (
        <EmptyState icon="⚡" title="Could not load plan" sub={err.message || String(err)} />
      )}

      {!loading && !plan?.plan && (
        <EmptyState
          title="No active plan"
          sub="Your personalised action plan will appear here after your portfolio is analysed. Upload a CAS to get started."
        />
      )}

      {!loading && plan?.plan && (
        <>
          {/* Stats */}
          <div style={statsGridStyle}>
            <StatTile label="Total actions" value={actions.length} />
            <StatTile
              label="Pending"
              value={pendingCount}
              tone={pendingCount > 0 ? "var(--v4-saffron)" : "var(--v4-ink-faint)"}
            />
            <StatTile
              label="Completed"
              value={completedCount}
              tone={completedCount > 0 ? "var(--v4-moss)" : "var(--v4-ink-faint)"}
            />
            {plan.plan?.version && (
              <StatTile label="Plan version" value={`v${plan.plan.version}`} />
            )}
          </div>

          {/* Type filter */}
          {filters.length > 2 && (
            <div style={filterBarStyle}>
              {filters.map(f => (
                <button
                  key={f}
                  type="button"
                  onClick={() => setFilter(f)}
                  style={f === filter ? { ...filterBtnStyle, ...filterBtnActiveStyle } : filterBtnStyle}
                >
                  {f === "ALL" ? "All" : (ACTION_META[f]?.label || f)}
                  {f !== "ALL" && typeCounts[f] && (
                    <span style={{ marginLeft: 5, opacity: 0.7 }}>({typeCounts[f]})</span>
                  )}
                </button>
              ))}
            </div>
          )}

          {/* Action list */}
          {visible.length === 0 ? (
            <EmptyState title="No actions in this category" />
          ) : (
            <section style={{ marginTop: 24 }}>
              <SectionHeader>
                {filter === "ALL" ? "All actions" : `${ACTION_META[filter]?.label || filter} actions`}
                <span style={{ fontFamily: "var(--v4-mono)", fontSize: 9, color: "var(--v4-ink-faint)" }}>
                  {visible.length} items
                </span>
              </SectionHeader>
              <div style={{ display: "flex", flexDirection: "column", gap: 10 }}>
                {visible.map((action, i) => (
                  <ActionCard key={action.action_id || action.id || i} action={action} />
                ))}
              </div>
            </section>
          )}
        </>
      )}
    </DashboardShell>
  );
}

function ActionCard({ action }) {
  const type = (action.type || "REVIEW").toUpperCase();
  const meta = ACTION_META[type] || ACTION_META.REVIEW;
  const statusKey = (action.status || "PENDING").toUpperCase();
  const statusMeta = STATUS_STYLE[statusKey] || STATUS_STYLE.PENDING;
  const priority = String(action.priority || "").toLowerCase();
  const priorityTone = PRIORITY_TONE[priority] || PRIORITY_TONE[action.priority] || "var(--v4-ink-faint)";

  const title = action.asset_name || action.title || action.action || "Action";
  const detail = action.reason_text || action.detail;
  const amount = action.amount;
  const confidence = action.confidence;

  return (
    <div style={actionCardStyle(meta.tone)}>
      <div style={{ display: "flex", alignItems: "flex-start", gap: 14 }}>
        {/* Type badge */}
        <div style={actionIconStyle(meta.tone)}>
          <span style={{ fontSize: 14 }}>{meta.icon}</span>
        </div>

        {/* Body */}
        <div style={{ flex: 1, minWidth: 0 }}>
          <div style={{ display: "flex", alignItems: "center", gap: 8, flexWrap: "wrap", marginBottom: 4 }}>
            <span style={{ fontFamily: "var(--v4-mono)", fontSize: 9, letterSpacing: 1.2, color: meta.tone, textTransform: "uppercase" }}>
              {meta.label}
            </span>
            {priority && (
              <span style={{ fontFamily: "var(--v4-mono)", fontSize: 9, color: priorityTone, letterSpacing: 1 }}>
                · {priority} priority
              </span>
            )}
            <span style={{ marginLeft: "auto", fontFamily: "var(--v4-mono)", fontSize: 9, color: statusMeta.color }}>
              {statusMeta.label}
            </span>
          </div>
          <div style={{ fontFamily: "var(--v4-display)", fontSize: 16, color: "var(--v4-ink)", marginBottom: 4 }}>
            {title}
          </div>
          {detail && (
            <div style={{ fontSize: 12, color: "var(--v4-ink-dim)", lineHeight: 1.55 }}>{detail}</div>
          )}
          {(amount || confidence) && (
            <div style={{ display: "flex", gap: 16, marginTop: 10 }}>
              {amount && (
                <div style={{ fontFamily: "var(--v4-mono)", fontSize: 10, color: "var(--v4-ink-mute)" }}>
                  Amount: <span style={{ color: "var(--v4-ink)" }}>{formatInr(amount)}</span>
                </div>
              )}
              {confidence && (
                <div style={{ fontFamily: "var(--v4-mono)", fontSize: 10, color: "var(--v4-ink-mute)" }}>
                  Confidence: <span style={{ color: "var(--v4-ink)" }}>{confidence}</span>
                </div>
              )}
            </div>
          )}
          {action.reason_codes?.length > 0 && (
            <div style={{ display: "flex", gap: 6, flexWrap: "wrap", marginTop: 8 }}>
              {action.reason_codes.slice(0, 3).map(code => (
                <span key={code} style={reasonCodeStyle}>{code}</span>
              ))}
            </div>
          )}
        </div>
      </div>
    </div>
  );
}

/* ─── Styles ─── */

const pageTitleStyle = { marginBottom: 32 };

const statsGridStyle = {
  display: "grid",
  gridTemplateColumns: "repeat(auto-fit, minmax(160px, 1fr))",
  gap: 14,
  marginBottom: 24,
};

const filterBarStyle = {
  display: "flex",
  gap: 8,
  flexWrap: "wrap",
  marginBottom: 4,
};

const filterBtnStyle = {
  fontFamily: "var(--v4-mono)",
  fontSize: 10,
  letterSpacing: 0.8,
  color: "var(--v4-ink-faint)",
  background: "var(--v4-s1)",
  border: "1px solid var(--v4-line)",
  padding: "7px 14px",
  borderRadius: 999,
  cursor: "pointer",
  textTransform: "uppercase",
};

const filterBtnActiveStyle = {
  color: "var(--v4-saffron)",
  borderColor: "rgba(255,146,72,0.4)",
  background: "rgba(255,146,72,0.08)",
};

const actionCardStyle = (tone) => ({
  background: "linear-gradient(165deg, var(--v4-s2), var(--v4-s1))",
  border: "1px solid var(--v4-line)",
  borderLeft: `3px solid ${tone}`,
  borderRadius: "var(--v4-r-md)",
  padding: "16px 18px",
});

const actionIconStyle = (tone) => ({
  width: 36,
  height: 36,
  borderRadius: 9,
  background: `${tone}18`,
  border: `1px solid ${tone}40`,
  display: "grid",
  placeItems: "center",
  flexShrink: 0,
  color: tone,
});

const reasonCodeStyle = {
  fontFamily: "var(--v4-mono)",
  fontSize: 9,
  letterSpacing: 0.6,
  color: "var(--v4-ink-faint)",
  background: "var(--v4-s1)",
  border: "1px solid var(--v4-line)",
  padding: "3px 8px",
  borderRadius: 4,
};
