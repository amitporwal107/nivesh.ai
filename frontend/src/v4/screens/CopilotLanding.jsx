import React, { useCallback, useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import { useAuth } from "@/context/AuthContext";
import api, { ApiError } from "../api/client";
import {
  getActivePortfolio,
} from "../api/portfolioIngestion";
import { DashboardShell } from "../components/DashboardShell";

/**
 * V4 AI Copilot Landing — the post-onboarding home screen.
 *
 * Composes 4 existing V2/V3 endpoints to render the "chat-first" landing the
 * V4 mockup specifies:
 *   GET /api/insights/v3-portfolio         → hero health score + grade
 *   GET /api/intelligence/portfolio        → top recommendations / insights
 *   GET /api/plans/active                  → top recommendation card (1st PENDING action)
 *   GET /api/copilot/suggested-prompts     → suggested prompt chips
 *   GET /api/portfolio/me                  → top-holdings summary
 *
 * Chat: clicking send posts to /api/chat/send (non-streaming) and shows the
 * reply inline. Full SSE streaming + multi-turn UX is deferred to a richer
 * Copilot screen in a later milestone; the composer here is intentionally
 * simple to unblock M3 without growing scope.
 */

const GRADE_BAND = (grade) => {
  if (!grade) return { tone: "var(--v4-ink-mute)", label: "—" };
  const g = String(grade).toUpperCase();
  if (g.startsWith("A")) return { tone: "var(--v4-moss)", label: "Healthy" };
  if (g.startsWith("B")) return { tone: "var(--v4-gold)", label: "Good" };
  if (g.startsWith("C")) return { tone: "var(--v4-gold)", label: "Needs work" };
  return { tone: "var(--v4-rust)", label: "At risk" };
};

const SEVERITY_TONE = {
  high: "var(--v4-rust)",
  medium: "var(--v4-gold)",
  low: "var(--v4-moss)",
};

export default function CopilotLanding() {
  const navigate = useNavigate();
  const { user, loading: authLoading } = useAuth();
  const [loading, setLoading] = useState(true);
  const [health, setHealth] = useState(null);
  const [intelligence, setIntelligence] = useState(null);
  const [activePlan, setActivePlan] = useState(null);
  const [prompts, setPrompts] = useState([]);
  const [portfolio, setPortfolio] = useState(null);

  useEffect(() => {
    if (!user) return;
    let cancelled = false;
    setLoading(true);
    (async () => {
      const results = await Promise.allSettled([
        api.get("/api/insights/v3-portfolio"),
        api.get("/api/intelligence/portfolio", { query: { narrate: true } }),
        api.get("/api/plans/active"),
        api.get("/api/copilot/suggested-prompts"),
        getActivePortfolio(),
      ]);
      if (cancelled) return;
      const [h, i, p, sp, pf] = results;
      if (h.status === "fulfilled") setHealth(h.value);
      if (i.status === "fulfilled") setIntelligence(i.value);
      if (p.status === "fulfilled") setActivePlan(p.value);
      if (sp.status === "fulfilled") {
        // Endpoint returns either { prompts: [...] } or a raw array.
        const arr = Array.isArray(sp.value) ? sp.value : sp.value?.prompts || [];
        setPrompts(arr.slice(0, 6));
      }
      if (pf.status === "fulfilled") setPortfolio(pf.value);
      setLoading(false);
    })();
    return () => {
      cancelled = true;
    };
  }, [user]);

  if (authLoading) return null;
  if (!user) {
    navigate("/onboarding", { replace: true });
    return null;
  }

  const healthScore =
    health?.health?.health_score ??
    health?.score ??
    health?.health_score ??
    null;
  const grade = health?.health?.grade ?? health?.grade ?? null;
  const summary = health?.health?.summary ?? health?.summary ?? null;
  const band = GRADE_BAND(grade);

  const topRecs =
    intelligence?.top_recommendations ||
    intelligence?.intelligence?.top_recommendations ||
    [];
  const topAction =
    activePlan?.plan?.actions?.find((a) => a.status === "PENDING") ||
    activePlan?.plan?.actions?.[0] ||
    null;
  const topHoldings =
    portfolio?.portfolio?.top_holdings || portfolio?.top_holdings || [];

  return (
    <DashboardShell>
      <main style={mainStyle}>
        <HeroScore
          loading={loading}
          score={healthScore}
          grade={grade}
          band={band}
          summary={summary}
          insightsCount={topRecs.length}
        />

        {topRecs.length > 0 && (
          <section style={{ marginTop: 32 }}>
            <SectionHeader>Top insights</SectionHeader>
            <div style={insightsGridStyle}>
              {topRecs.slice(0, 3).map((rec, i) => (
                <InsightCard key={`${rec.title || i}`} rec={rec} />
              ))}
            </div>
          </section>
        )}

        {topAction && (
          <section style={{ marginTop: 32 }}>
            <SectionHeader>One action worth doing this week</SectionHeader>
            <TopActionCard action={topAction} onSeePlan={() => navigate("/plan")} />
          </section>
        )}

        {topHoldings.length > 0 && (
          <section style={{ marginTop: 32 }}>
            <SectionHeader>Your top positions</SectionHeader>
            <TopPositionsList holdings={topHoldings} />
          </section>
        )}

        <ChatComposer suggestedPrompts={prompts} />

        <div style={footerStrapStyle}>
          🔒 Bank-grade encryption · 🛡️ Read-only · ⚖️ SEBI-aware
        </div>
      </main>
    </DashboardShell>
  );
}

/* ───────── Sub-components ───────── */

function SectionHeader({ children }) {
  return (
    <div
      style={{
        fontFamily: "var(--v4-mono)",
        fontSize: 10,
        letterSpacing: 1.6,
        color: "var(--v4-ink-faint)",
        textTransform: "uppercase",
        marginBottom: 14,
        display: "flex",
        alignItems: "center",
        gap: 10,
      }}
    >
      {children}
      <span style={{ flex: 1, height: 1, background: "var(--v4-line)" }} />
    </div>
  );
}

function HeroScore({ loading, score, grade, band, summary, insightsCount }) {
  const pct = score != null ? Math.max(0, Math.min(100, Number(score))) : 0;
  const dash = 213.6;
  const stroke = (pct / 100) * dash;

  return (
    <section style={heroCardStyle}>
      <div style={{ display: "flex", alignItems: "center", gap: 28, flexWrap: "wrap" }}>
        <div style={{ position: "relative", width: 120, height: 120 }}>
          <svg viewBox="0 0 80 80" width="120" height="120">
            <circle cx="40" cy="40" r="34" stroke="var(--v4-line-strong)" strokeWidth="6" fill="none" />
            <circle
              cx="40"
              cy="40"
              r="34"
              stroke={band.tone}
              strokeWidth="6"
              fill="none"
              strokeDasharray={`${stroke} ${dash}`}
              strokeLinecap="round"
              transform="rotate(-90 40 40)"
              style={{ transition: "stroke-dasharray .6s var(--v4-ease)" }}
            />
            <text
              x="40"
              y="44"
              textAnchor="middle"
              fontFamily="var(--v4-display)"
              fontSize="22"
              fontWeight="600"
              fill="var(--v4-ink)"
            >
              {score != null ? Math.round(score) : "—"}
            </text>
          </svg>
        </div>
        <div style={{ flex: 1, minWidth: 240 }}>
          <div
            style={{
              fontFamily: "var(--v4-mono)",
              fontSize: 10,
              letterSpacing: 1.4,
              color: "var(--v4-ink-faint)",
              textTransform: "uppercase",
              marginBottom: 6,
            }}
          >
            PORTFOLIO HEALTH
          </div>
          <div style={{ fontFamily: "var(--v4-display)", fontSize: 30, color: "var(--v4-ink)", marginBottom: 6 }}>
            Grade {grade || "—"} — {band.label}
          </div>
          <div style={{ fontSize: 14, color: "var(--v4-ink-dim)", lineHeight: 1.55 }}>
            {loading
              ? "Computing your health score…"
              : summary ||
                (insightsCount
                  ? `${insightsCount} ${insightsCount === 1 ? "thing is" : "things are"} worth your attention.`
                  : "We'll surface insights here as soon as your data is processed.")}
          </div>
        </div>
      </div>
    </section>
  );
}

function InsightCard({ rec }) {
  const sev = String(rec.impact || rec.severity || "medium").toLowerCase();
  const tone = SEVERITY_TONE[sev] || SEVERITY_TONE.medium;
  return (
    <div style={insightCardStyle}>
      <div
        style={{
          width: 4,
          background: tone,
          borderRadius: 4,
          marginRight: 14,
          alignSelf: "stretch",
        }}
      />
      <div style={{ flex: 1, minWidth: 0 }}>
        <div
          style={{
            fontFamily: "var(--v4-display)",
            fontSize: 15,
            color: "var(--v4-ink)",
            marginBottom: 4,
            lineHeight: 1.35,
          }}
        >
          {rec.title || rec.headline || "Insight"}
        </div>
        {rec.detail && (
          <div style={{ fontSize: 12, color: "var(--v4-ink-mute)", lineHeight: 1.5 }}>
            {rec.detail}
          </div>
        )}
        <div
          style={{
            fontFamily: "var(--v4-mono)",
            fontSize: 9,
            letterSpacing: 1.2,
            color: tone,
            textTransform: "uppercase",
            marginTop: 8,
          }}
        >
          {sev}
        </div>
      </div>
    </div>
  );
}

function TopActionCard({ action, onSeePlan }) {
  const verb = (action.type || action.kind || "ACT").toString().toUpperCase();
  const title = action.title || action.asset_name || action.action || "Pending action";
  const detail = action.detail || action.reason_text;
  return (
    <div style={topActionCardStyle}>
      <div
        style={{
          fontFamily: "var(--v4-mono)",
          fontSize: 9,
          letterSpacing: 1.4,
          color: "var(--v4-saffron)",
          textTransform: "uppercase",
          marginBottom: 8,
        }}
      >
        {verb}
      </div>
      <div style={{ fontFamily: "var(--v4-display)", fontSize: 20, color: "var(--v4-ink)", marginBottom: 8 }}>
        {title}
      </div>
      {detail && (
        <div style={{ fontSize: 13, color: "var(--v4-ink-dim)", lineHeight: 1.55, marginBottom: 16 }}>
          {detail}
        </div>
      )}
      <div style={{ display: "flex", gap: 10, flexWrap: "wrap" }}>
        <button style={ctaPrimaryStyle} onClick={onSeePlan}>
          See the plan →
        </button>
      </div>
    </div>
  );
}

function TopPositionsList({ holdings }) {
  return (
    <div style={topHoldingsListStyle}>
      {holdings.slice(0, 6).map((h, i) => {
        const name = h.name || h.scheme || h.asset_name || "—";
        const value = h.value;
        const pct = h.pct != null ? Number(h.pct) : null;
        return (
          <div key={`${name}-${i}`} style={topHoldingRowStyle}>
            <div
              style={{
                fontFamily: "var(--v4-mono)",
                fontSize: 10,
                color: "var(--v4-ink-faint)",
                width: 18,
                flex: "none",
              }}
            >
              {i + 1}
            </div>
            <div style={{ flex: 1, minWidth: 0 }}>
              <div
                style={{
                  color: "var(--v4-ink)",
                  fontSize: 13,
                  whiteSpace: "nowrap",
                  overflow: "hidden",
                  textOverflow: "ellipsis",
                }}
                title={name}
              >
                {name}
              </div>
            </div>
            <div style={{ textAlign: "right", flex: "none" }}>
              <div style={{ fontFamily: "var(--v4-display)", fontSize: 13, color: "var(--v4-ink)" }}>
                {formatInr(value)}
              </div>
              {pct != null && (
                <div style={{ fontFamily: "var(--v4-mono)", fontSize: 10, color: "var(--v4-ink-faint)" }}>
                  {pct.toFixed(1)}%
                </div>
              )}
            </div>
          </div>
        );
      })}
    </div>
  );
}

function ChatComposer({ suggestedPrompts }) {
  const [text, setText] = useState("");
  const [sending, setSending] = useState(false);
  const [reply, setReply] = useState(null);
  const [err, setErr] = useState(null);

  const send = useCallback(
    async (msg) => {
      const m = (msg || text).trim();
      if (!m) return;
      setSending(true);
      setErr(null);
      setReply(null);
      try {
        const res = await api.post("/api/chat/send", { message: m });
        setReply({ user: m, assistant: res?.reply || res?.message || "(no reply)" });
        setText("");
      } catch (e) {
        setErr(
          e instanceof ApiError
            ? `${e.status} ${e.detail || e.message}`
            : e.message || "Could not reach the copilot.",
        );
      } finally {
        setSending(false);
      }
    },
    [text],
  );

  return (
    <section style={{ marginTop: 36 }}>
      <SectionHeader>Ask the copilot</SectionHeader>
      {suggestedPrompts && suggestedPrompts.length > 0 && (
        <div style={{ display: "flex", gap: 8, flexWrap: "wrap", marginBottom: 14 }}>
          {suggestedPrompts.map((p) => {
            const label = p.label || p.text || p.query;
            const query = p.query || p.text || p.label;
            return (
              <button
                key={label}
                type="button"
                style={promptChipStyle}
                onClick={() => send(query)}
                disabled={sending}
              >
                {label}
              </button>
            );
          })}
        </div>
      )}
      <div style={composerStyle}>
        <input
          type="text"
          value={text}
          onChange={(e) => setText(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Enter" && !sending) send();
          }}
          placeholder="Ask me anything about your portfolio…"
          style={composerInputStyle}
          disabled={sending}
        />
        <button
          type="button"
          onClick={() => send()}
          disabled={sending || !text.trim()}
          style={composerSendStyle}
        >
          {sending ? "…" : "Send"}
        </button>
      </div>
      {err && (
        <div style={{ marginTop: 10, color: "var(--v4-rust)", fontSize: 12 }}>{err}</div>
      )}
      {reply && (
        <div style={replyCardStyle}>
          <div style={{ fontFamily: "var(--v4-mono)", fontSize: 9, letterSpacing: 1.2, color: "var(--v4-ink-faint)", marginBottom: 6 }}>
            YOU
          </div>
          <div style={{ fontSize: 13, color: "var(--v4-ink-dim)", marginBottom: 14 }}>{reply.user}</div>
          <div style={{ fontFamily: "var(--v4-mono)", fontSize: 9, letterSpacing: 1.2, color: "var(--v4-saffron)", marginBottom: 6 }}>
            COPILOT
          </div>
          <div style={{ fontSize: 14, color: "var(--v4-ink)", lineHeight: 1.55, whiteSpace: "pre-wrap" }}>
            {reply.assistant}
          </div>
        </div>
      )}
    </section>
  );
}

/* ───────── helpers ───────── */

function formatInr(n) {
  if (n == null || n === "") return "—";
  const v = typeof n === "number" ? n : Number(String(n).replace(/,/g, ""));
  if (!Number.isFinite(v)) return "—";
  if (v >= 1e7) return `₹${(v / 1e7).toFixed(2)} Cr`;
  if (v >= 1e5) return `₹${(v / 1e5).toFixed(2)} L`;
  if (v >= 1e3) return `₹${(v / 1e3).toFixed(1)} K`;
  return `₹${Math.round(v).toLocaleString("en-IN")}`;
}

/* ───────── Styles ───────── */

const mainStyle = {
  maxWidth: 1080,
  margin: "0 auto",
  padding: "44px 32px 80px",
};

const heroCardStyle = {
  background: "linear-gradient(168deg, var(--v4-hero-a), var(--v4-hero-b))",
  border: "1px solid var(--v4-line-strong)",
  borderRadius: "var(--v4-r-xl)",
  padding: "30px 30px",
};

const insightsGridStyle = {
  display: "grid",
  gridTemplateColumns: "repeat(auto-fit, minmax(280px, 1fr))",
  gap: 14,
};

const insightCardStyle = {
  display: "flex",
  background: "linear-gradient(165deg, var(--v4-s2), var(--v4-s1))",
  border: "1px solid var(--v4-line)",
  borderRadius: "var(--v4-r-lg)",
  padding: "18px 18px",
};

const topActionCardStyle = {
  background: "linear-gradient(168deg, rgba(255,146,72,0.10), rgba(255,146,72,0.02))",
  border: "1px solid rgba(255,146,72,0.32)",
  borderRadius: "var(--v4-r-lg)",
  padding: "24px 22px",
};

const topHoldingsListStyle = {
  display: "flex",
  flexDirection: "column",
  border: "1px solid var(--v4-line)",
  borderRadius: "var(--v4-r-md)",
  overflow: "hidden",
};

const topHoldingRowStyle = {
  display: "flex",
  gap: 14,
  alignItems: "center",
  padding: "12px 16px",
  borderBottom: "1px solid var(--v4-line)",
  background: "var(--v4-s1)",
};

const composerStyle = {
  display: "flex",
  gap: 10,
  alignItems: "center",
  background: "var(--v4-s1)",
  border: "1px solid var(--v4-line-strong)",
  borderRadius: 999,
  padding: "8px 10px 8px 18px",
};

const composerInputStyle = {
  flex: 1,
  background: "transparent",
  border: "none",
  outline: "none",
  color: "var(--v4-ink)",
  fontSize: 14,
  fontFamily: "var(--v4-sans)",
  padding: "8px 0",
};

const composerSendStyle = {
  fontSize: 13,
  fontWeight: 600,
  background: "linear-gradient(150deg, var(--v4-saffron), var(--v4-saffron-dk))",
  color: "#2a1605",
  padding: "10px 18px",
  borderRadius: 999,
  border: "none",
  cursor: "pointer",
};

const promptChipStyle = {
  fontFamily: "var(--v4-mono)",
  fontSize: 11,
  letterSpacing: 0.6,
  color: "var(--v4-ink-dim)",
  background: "var(--v4-s2)",
  border: "1px solid var(--v4-line)",
  padding: "7px 12px",
  borderRadius: 999,
  cursor: "pointer",
  textTransform: "uppercase",
};

const replyCardStyle = {
  marginTop: 16,
  background: "linear-gradient(168deg, var(--v4-s2), var(--v4-s1))",
  border: "1px solid var(--v4-line)",
  borderRadius: "var(--v4-r-md)",
  padding: "18px 20px",
};

const ctaPrimaryStyle = {
  fontSize: 13,
  fontWeight: 600,
  background: "linear-gradient(150deg, var(--v4-saffron), var(--v4-saffron-dk))",
  color: "#2a1605",
  padding: "11px 18px",
  borderRadius: 10,
  border: "none",
  cursor: "pointer",
};

const footerStrapStyle = {
  fontFamily: "var(--v4-mono)",
  fontSize: 10,
  letterSpacing: 1.2,
  color: "var(--v4-ink-faint)",
  textTransform: "uppercase",
  textAlign: "center",
  marginTop: 40,
};
