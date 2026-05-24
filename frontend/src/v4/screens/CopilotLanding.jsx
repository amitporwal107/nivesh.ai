/**
 * V4 Copilot Landing — matches the HTML prototype layout.
 *
 * Layout: own topnav (no sidebar) → health ring (expandable) →
 *   clickable insight cards → top recommendation → prompt chips →
 *   sticky bottom chat bar.
 *
 * Endpoints:
 *   GET /api/insights/v3-portfolio      → health score + component breakdown
 *   GET /api/intelligence/portfolio     → insight cards (kind → dashboard path)
 *   GET /api/plans/active               → top recommendation card
 *   GET /api/copilot/suggested-prompts  → prompt chips
 */
import React, { useCallback, useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import { useAuth } from "@/context/AuthContext";
import api, { ApiError } from "../api/client";
import { getActivePortfolio } from "../api/portfolioIngestion";
import { formatInr } from "../components/DashboardShell";

/* kind field from /api/intelligence/portfolio → dashboard path */
const KIND_PATH = {
  OVERLAP: "/diversification",
  FUND_OVERLAP: "/diversification",
  SECTOR_CONCENTRATION: "/concentration",
  AMC_CONCENTRATION: "/concentration",
  AMC_CONCENTRATION_EXIT: "/concentration",
  STOCK_CONCENTRATION: "/concentration",
  COMPANY_CONCENTRATION: "/concentration",
  HIGH_BETA: "/risk",
  HIGH_VOLATILITY: "/risk",
  RISK: "/risk",
  COST_REDUCTION: "/plan",
  COST_LEAK_SWITCH_TO_DIRECT: "/plan",
  WEAK_MF: "/plan",
  TAX_HARVEST: "/plan",
  REBALANCE: "/plan",
  UNDERPERFORMER_REPLACEMENT: "/plan",
};

const GRADE_TONE = (grade) => {
  if (!grade) return "var(--v4-ink-mute)";
  const g = String(grade).toUpperCase();
  if (g.startsWith("A")) return "var(--v4-moss)";
  if (g.startsWith("B")) return "var(--v4-gold)";
  if (g.startsWith("C")) return "var(--v4-gold)";
  return "var(--v4-rust)";
};

const GRADE_LABEL = (grade) => {
  if (!grade) return "—";
  const g = String(grade).toUpperCase();
  if (g === "A+" || g === "A") return "Healthy";
  if (g === "B+" || g === "B") return "Good";
  if (g === "C") return "Needs work";
  return "At risk";
};

const IMPACT_TONE = { high: "var(--v4-rust)", medium: "var(--v4-gold)", low: "var(--v4-moss)" };

const COMPONENT_LABELS = {
  diversification: "Diversification",
  risk: "Risk",
  cost: "Cost",
  performance: "Performance",
};

const COMPONENT_PATHS = {
  diversification: "/diversification",
  risk: "/risk",
  cost: "/plan",
  performance: null,
};

export default function CopilotLanding() {
  const navigate = useNavigate();
  const { user, loading: authLoading, logout } = useAuth();

  const [loading, setLoading]         = useState(true);
  const [health, setHealth]           = useState(null);
  const [intelligence, setIntelligence] = useState(null);
  const [activePlan, setActivePlan]   = useState(null);
  const [prompts, setPrompts]         = useState([]);
  const [showBreakdown, setShowBreakdown] = useState(false);

  /* chat state */
  const [chatText, setChatText] = useState("");
  const [sending, setSending]   = useState(false);
  const [reply, setReply]       = useState(null);
  const [chatErr, setChatErr]   = useState(null);

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
      ]);
      if (cancelled) return;
      const [h, i, p, sp] = results;
      if (h.status  === "fulfilled") setHealth(h.value);
      if (i.status  === "fulfilled") setIntelligence(i.value);
      if (p.status  === "fulfilled") setActivePlan(p.value);
      if (sp.status === "fulfilled") {
        const arr = Array.isArray(sp.value) ? sp.value : sp.value?.prompts || [];
        setPrompts(arr.slice(0, 6));
      }
      setLoading(false);
    })();
    return () => { cancelled = true; };
  }, [user]);

  const sendChat = useCallback(async (msg) => {
    const m = (msg || chatText).trim();
    if (!m) return;
    setSending(true); setChatErr(null); setReply(null);
    try {
      const res = await api.post("/api/chat/send", { message: m });
      setReply({ user: m, assistant: res?.reply || res?.message || "(no reply)" });
      setChatText("");
    } catch (e) {
      setChatErr(e instanceof ApiError ? `${e.status} ${e.detail || e.message}` : e.message || "Could not reach the copilot.");
    } finally { setSending(false); }
  }, [chatText]);

  if (authLoading) return null;
  if (!user) { navigate("/onboarding", { replace: true }); return null; }

  /* ── Derived data ── */
  const healthObj   = health?.health || health;
  const score       = healthObj?.health_score ?? healthObj?.score ?? null;
  const grade       = healthObj?.grade ?? null;
  const summary     = healthObj?.summary ?? null;
  const lowConf     = healthObj?.low_confidence ?? false;
  const components  = healthObj?.components ?? {};
  const gradeTone   = GRADE_TONE(grade);
  const gradeLabel  = GRADE_LABEL(grade);

  const topRecs  = intelligence?.top_recommendations || [];
  const insightCards = topRecs
    .filter(r => KIND_PATH[r.kind] || KIND_PATH[(r.kind || "").toUpperCase()])
    .slice(0, 3);

  const topAction = activePlan?.plan?.actions?.find(a => (a.status || "").toUpperCase() === "PENDING")
    || activePlan?.plan?.actions?.[0]
    || null;

  /* SVG ring calc */
  const pct   = score != null ? Math.max(0, Math.min(100, Number(score))) : 0;
  const DASH  = 213.6;
  const filled = (pct / 100) * DASH;

  return (
    <div style={pageStyle}>
      {/* ── Topnav ── */}
      <header style={topnavStyle}>
        <div style={brandStyle}>
          <div style={markStyle}>न</div>
          <span style={{ fontFamily: "var(--v4-display)", fontWeight: 600, fontSize: 16, color: "var(--v4-ink)" }}>Nivesh</span>
          <span style={{ fontFamily: "var(--v4-mono)", fontSize: 8, letterSpacing: 1.2, color: "var(--v4-ink-faint)", textTransform: "uppercase" }}>Copilot</span>
        </div>
        <span style={nidpPillStyle}>⬀ NIDP connected</span>
      </header>

      {/* ── Scrollable content ── */}
      <div style={scrollStyle}>
        <div style={wrapStyle}>

          {/* Portfolio Analysed eyebrow */}
          <div style={eyebrowStyle}>⬀ Portfolio analysed · NIDP-grounded</div>

          {/* ── Health ring card ── */}
          <div style={healthCardStyle}>
            <div style={{ display: "flex", alignItems: "center", gap: 22, flexWrap: "wrap" }}>
              {/* SVG ring */}
              <svg viewBox="0 0 92 92" width={100} height={100} style={{ flexShrink: 0 }}>
                <circle cx="46" cy="46" r="34" fill="none" stroke="var(--v4-line-strong)" strokeWidth="9" />
                <circle
                  cx="46" cy="46" r="34" fill="none"
                  stroke={loading ? "var(--v4-line-strong)" : gradeTone}
                  strokeWidth="9"
                  strokeDasharray={loading ? "0 213.6" : `${filled} ${DASH}`}
                  strokeLinecap="round"
                  transform="rotate(-90 46 46)"
                  style={{ transition: "stroke-dasharray .6s var(--v4-ease)" }}
                />
                <text x="46" y="43" textAnchor="middle" fontFamily="var(--v4-display)" fontSize="24" fontWeight="600" fill="var(--v4-ink)">
                  {score != null ? Math.round(score) : "—"}
                </text>
                <text x="46" y="59" textAnchor="middle" fontFamily="monospace" fontSize="7.5" letterSpacing="1.5" fill="var(--v4-ink-faint)">
                  / 100
                </text>
              </svg>

              <div style={{ flex: 1, minWidth: 180 }}>
                <div style={{ fontFamily: "var(--v4-display)", fontSize: 22, fontWeight: 600, color: "var(--v4-ink)", marginBottom: 6 }}>
                  Grade {grade || "—"} · {gradeLabel}
                </div>
                <p style={{ fontSize: 13, color: "var(--v4-ink-dim)", lineHeight: 1.6, margin: 0 }}>
                  {loading ? "Computing your health score…" : summary || "Your portfolio has been analysed."}
                </p>
              </div>

              {/* ⓘ toggle */}
              {Object.keys(components).length > 0 && (
                <button
                  type="button"
                  style={infoToggleStyle}
                  onClick={() => setShowBreakdown(v => !v)}
                >
                  {showBreakdown ? "Hide" : "ⓘ"}
                </button>
              )}
            </div>

            {/* Expandable breakdown */}
            {showBreakdown && Object.keys(components).length > 0 && (
              <div style={breakdownStyle}>
                <div style={{ fontFamily: "var(--v4-mono)", fontSize: 10, color: "var(--v4-ink-faint)", marginBottom: 10, letterSpacing: 0.6 }}>
                  Health = {Object.entries(components)
                    .map(([k, v]) => `${Math.round((v.weight || 0) * 100)}% ${COMPONENT_LABELS[k] || k}`)
                    .join(" + ")}
                </div>
                <div style={componentGridStyle}>
                  {Object.entries(components).map(([key, comp]) => {
                    const path = COMPONENT_PATHS[key];
                    const s = comp.score ?? comp.weighted_score ?? null;
                    return (
                      <div
                        key={key}
                        style={componentTileStyle(!!path)}
                        onClick={path ? () => navigate(path) : undefined}
                      >
                        <div style={{ fontFamily: "var(--v4-mono)", fontSize: 9, color: "var(--v4-ink-faint)", marginBottom: 4, textTransform: "uppercase", letterSpacing: 1 }}>
                          {COMPONENT_LABELS[key] || key}
                        </div>
                        <div style={{ fontFamily: "var(--v4-display)", fontSize: 20, color: s >= 70 ? "var(--v4-moss)" : s >= 50 ? "var(--v4-gold)" : "var(--v4-rust)" }}>
                          {s != null ? Math.round(s) : "—"}
                        </div>
                      </div>
                    );
                  })}
                </div>
                {lowConf && (
                  <div style={lowConfWarningStyle}>
                    ⚠ Some primitives estimated — score may refine as data enriches.
                  </div>
                )}
              </div>
            )}
          </div>

          {/* ── Insight cards ── */}
          {insightCards.length > 0 && (
            <>
              <div style={hlStyle}>Top insights · tap to open dashboard</div>
              <div style={{ display: "flex", flexDirection: "column", gap: 9, marginBottom: 18 }}>
                {insightCards.map((rec, i) => {
                  const kind = (rec.kind || "").toUpperCase();
                  const path = KIND_PATH[kind] || KIND_PATH[rec.kind];
                  const tone = IMPACT_TONE[String(rec.impact || "medium").toLowerCase()] || IMPACT_TONE.medium;
                  return (
                    <div key={rec.id || i} style={insightRowStyle} onClick={() => path && navigate(path)}>
                      <div style={{ width: 3, alignSelf: "stretch", background: tone, borderRadius: 2, flexShrink: 0 }} />
                      <div style={{ flex: 1, minWidth: 0 }}>
                        <div style={{ fontSize: 13.5, fontWeight: 500, color: "var(--v4-ink)", marginBottom: 3 }}>
                          {rec.title || rec.headline || "Insight"}
                        </div>
                        {path && (
                          <div style={{ fontFamily: "var(--v4-mono)", fontSize: 8.5, letterSpacing: 1, color: "var(--v4-ink-mute)", textTransform: "uppercase" }}>
                            {path.replace("/", "")} dashboard
                          </div>
                        )}
                      </div>
                      <span style={impactBadgeStyle(tone)}>{String(rec.impact || "medium").toUpperCase()}</span>
                      <span style={{ color: "var(--v4-ink-faint)", fontSize: 14 }}>›</span>
                    </div>
                  );
                })}
              </div>
            </>
          )}

          {/* ── Top recommendation card ── */}
          {topAction && (
            <div style={topRecCardStyle}>
              <div style={{ fontFamily: "var(--v4-mono)", fontSize: 8.5, letterSpacing: 1.2, color: "var(--v4-saffron)", textTransform: "uppercase", marginBottom: 5 }}>
                ⬀ Top recommendation
              </div>
              <div style={{ fontSize: 14, fontWeight: 500, color: "var(--v4-ink)", marginBottom: 4 }}>
                {topAction.asset_name || topAction.title || "Pending action"}
              </div>
              {topAction.reason_text && (
                <div style={{ fontSize: 12, color: "var(--v4-ink-dim)", marginBottom: 12, lineHeight: 1.55 }}>
                  {topAction.reason_text}
                </div>
              )}
              <div style={{ display: "flex", gap: 8, flexWrap: "wrap" }}>
                <button style={ctaPrimaryStyle} type="button" onClick={() => navigate("/plan")}>
                  See the plan
                </button>
              </div>
            </div>
          )}

          {/* ── Prompt chips + chat ── */}
          {prompts.length > 0 && (
            <>
              <div style={hlStyle}>Or ask me anything</div>
              <div style={{ display: "flex", flexWrap: "wrap", gap: 7, marginBottom: 20 }}>
                {prompts.map((p) => {
                  const label = p.label || p.text || p.query;
                  const query = p.query || p.text || p.label;
                  return (
                    <button key={label} type="button" style={chipStyle} onClick={() => sendChat(query)} disabled={sending}>
                      {label}
                    </button>
                  );
                })}
              </div>
            </>
          )}

          {/* Chat reply */}
          {reply && (
            <div style={replyCardStyle}>
              <div style={{ fontFamily: "var(--v4-mono)", fontSize: 9, letterSpacing: 1.2, color: "var(--v4-ink-faint)", marginBottom: 5 }}>YOU</div>
              <div style={{ fontSize: 13, color: "var(--v4-ink-dim)", marginBottom: 12 }}>{reply.user}</div>
              <div style={{ fontFamily: "var(--v4-mono)", fontSize: 9, letterSpacing: 1.2, color: "var(--v4-saffron)", marginBottom: 5 }}>COPILOT</div>
              <div style={{ fontSize: 14, color: "var(--v4-ink)", lineHeight: 1.55, whiteSpace: "pre-wrap" }}>{reply.assistant}</div>
            </div>
          )}
          {chatErr && <div style={{ color: "var(--v4-rust)", fontSize: 12, marginBottom: 16 }}>{chatErr}</div>}

        </div>
      </div>

      {/* ── Sticky bottom chat bar ── */}
      <div style={chatBarStyle}>
        <span style={{ color: "var(--v4-ink-faint)", fontSize: 18, lineHeight: 1 }}>+</span>
        <input
          type="text"
          value={chatText}
          onChange={e => setChatText(e.target.value)}
          onKeyDown={e => { if (e.key === "Enter" && !sending) sendChat(); }}
          placeholder="Ask about your portfolio…"
          style={chatInputStyle}
          disabled={sending}
        />
        <button
          type="button"
          onClick={() => sendChat()}
          disabled={sending || !chatText.trim()}
          style={chatSendStyle}
        >
          {sending ? "…" : "↑"}
        </button>
      </div>
    </div>
  );
}

/* ── Styles ──────────────────────────────────────────────── */

const pageStyle = {
  minHeight: "100vh", background: "var(--v4-bg)", color: "var(--v4-ink)",
  display: "flex", flexDirection: "column",
};

const topnavStyle = {
  display: "flex", alignItems: "center", justifyContent: "space-between",
  padding: "14px 22px", borderBottom: "1px solid var(--v4-line)",
  position: "sticky", top: 0, background: "rgba(11,10,8,.96)",
  backdropFilter: "blur(10px)", zIndex: 20, flexShrink: 0,
};

const brandStyle = { display: "flex", alignItems: "center", gap: 9 };

const markStyle = {
  width: 28, height: 28, borderRadius: 8,
  background: "linear-gradient(150deg, var(--v4-saffron), var(--v4-saffron-lo))",
  display: "grid", placeItems: "center",
  fontFamily: "var(--v4-display)", fontWeight: 600, color: "#2a1605", fontSize: 14,
};

const nidpPillStyle = {
  fontFamily: "var(--v4-mono)", fontSize: 8.5, letterSpacing: 1, textTransform: "uppercase",
  color: "var(--v4-moss)", background: "rgba(136,171,102,.1)",
  border: "1px solid rgba(136,171,102,.3)", padding: "4px 10px", borderRadius: 5,
};

const scrollStyle = { flex: 1, overflowY: "auto" };

const wrapStyle = { maxWidth: 620, margin: "0 auto", padding: "24px 22px 80px" };

const eyebrowStyle = {
  fontFamily: "var(--v4-mono)", fontSize: 8, letterSpacing: 1.6,
  color: "var(--v4-saffron)", textTransform: "uppercase", marginBottom: 14,
};

const healthCardStyle = {
  background: "linear-gradient(168deg, var(--v4-hero-a), var(--v4-hero-b))",
  border: "1px solid var(--v4-line-strong)",
  borderRadius: 16, padding: "20px", marginBottom: 16,
};

const infoToggleStyle = {
  fontFamily: "var(--v4-mono)", fontSize: 10, letterSpacing: 0.8,
  color: "var(--v4-ink-mute)", background: "var(--v4-s2)",
  border: "1px solid var(--v4-line)", padding: "5px 11px", borderRadius: 7,
  cursor: "pointer", textTransform: "uppercase", flexShrink: 0,
};

const breakdownStyle = {
  marginTop: 16, paddingTop: 14,
  borderTop: "1px solid var(--v4-line)",
};

const componentGridStyle = {
  display: "grid", gridTemplateColumns: "1fr 1fr", gap: 8,
};

const componentTileStyle = (clickable) => ({
  background: "var(--v4-s0)", border: "1px solid var(--v4-line)",
  borderRadius: 10, padding: "10px 12px", textAlign: "center",
  cursor: clickable ? "pointer" : "default",
  transition: clickable ? "border-color .15s" : undefined,
});

const lowConfWarningStyle = {
  fontFamily: "var(--v4-mono)", fontSize: 9, letterSpacing: 0.5,
  color: "var(--v4-gold)", marginTop: 10, lineHeight: 1.5,
};

const hlStyle = {
  display: "flex", alignItems: "center", gap: 8,
  fontFamily: "var(--v4-mono)", fontSize: 8, letterSpacing: 1.6,
  color: "var(--v4-ink-faint)", textTransform: "uppercase", marginBottom: 9,
};

const insightRowStyle = {
  display: "flex", alignItems: "center", gap: 12, padding: "13px 14px",
  background: "linear-gradient(165deg, var(--v4-s2), var(--v4-s1))",
  border: "1px solid var(--v4-line)", borderRadius: 13, cursor: "pointer",
};

const impactBadgeStyle = (tone) => ({
  fontFamily: "var(--v4-mono)", fontSize: 7.5, letterSpacing: 0.8,
  padding: "3px 7px", borderRadius: 5, textTransform: "uppercase", flexShrink: 0,
  color: tone,
  background: `${tone}18`,
  border: `1px solid ${tone}40`,
});

const topRecCardStyle = {
  background: "linear-gradient(168deg, rgba(255,146,72,.08), rgba(255,146,72,.02))",
  border: "1px solid rgba(255,146,72,.2)",
  borderRadius: 16, padding: "14px 15px", marginBottom: 18, cursor: "pointer",
};

const ctaPrimaryStyle = {
  fontSize: 12, fontWeight: 600,
  background: "linear-gradient(150deg, var(--v4-saffron), var(--v4-saffron-dk))",
  color: "#2a1605", padding: "8px 14px", borderRadius: 9, border: "none", cursor: "pointer",
};

const chipStyle = {
  fontSize: 11.5, color: "var(--v4-ink-dim)",
  background: "var(--v4-s2)", border: "1px solid var(--v4-line)",
  padding: "7px 12px", borderRadius: 9, cursor: "pointer",
};

const replyCardStyle = {
  background: "linear-gradient(168deg, var(--v4-s2), var(--v4-s1))",
  border: "1px solid var(--v4-line)", borderRadius: 13, padding: "16px 18px", marginBottom: 14,
};

const chatBarStyle = {
  display: "flex", alignItems: "center", gap: 10,
  padding: "12px 22px", borderTop: "1px solid var(--v4-line)",
  background: "rgba(11,10,8,.92)", backdropFilter: "blur(10px)",
  position: "sticky", bottom: 0, flexShrink: 0,
};

const chatInputStyle = {
  flex: 1, fontSize: 13, color: "var(--v4-ink-mute)",
  background: "var(--v4-s1)", border: "1px solid var(--v4-line)",
  borderRadius: 16, padding: "9px 14px", outline: "none",
};

const chatSendStyle = {
  width: 32, height: 32, borderRadius: 9,
  background: "linear-gradient(150deg, var(--v4-saffron), var(--v4-saffron-dk))",
  color: "#2a1605", border: "none", cursor: "pointer",
  fontSize: 15, display: "grid", placeItems: "center", flexShrink: 0,
};
