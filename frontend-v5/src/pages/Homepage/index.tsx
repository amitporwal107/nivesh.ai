/**
 * Homepage — landing page, ported from screens-homepage.jsx
 * Wires the health preview card to real API data when available.
 */
import { useNavigate } from "react-router-dom";
import { useHealthAnalysis } from "@/hooks/use-insights";
import { usePortfolioSummary } from "@/hooks/use-portfolio";

function gradeLabel(score: number) {
  if (score >= 85) return "GRADE A";
  if (score >= 70) return "GRADE B";
  if (score >= 55) return "GRADE C";
  return "GRADE D";
}

function barColor(v: number) {
  if (v >= 70) return "var(--mint)";
  if (v >= 50) return "var(--amber)";
  return "var(--danger-hex)";
}

export default function HomepagePage() {
  const navigate = useNavigate();
  const { data: health } = useHealthAnalysis();
  const { data: summary } = usePortfolioSummary();

  // Extract real scores if available
  const h = health as any;
  const healthScore: number | null = h?.health_score ?? (summary as any)?.healthScore ?? null;
  const dimensions: Array<{ k: string; v: number }> | null = h?.dimensions
    ? Object.entries(h.dimensions as Record<string, number>).map(([k, v]) => ({ k, v: v as number }))
    : null;
  const insights: Array<{ title: string; source: string; severity: string }> | null =
    summary?.topInsights?.map((i: any) => ({
      title: i.title ?? i.headline ?? "",
      source: i.source ?? i.domain ?? "",
      severity: i.severity ?? "mint",
    })) ?? null;

  return (
    <div className="nv-frame" style={{ width: "100%", minHeight: "100vh" }}>
      {/* nav */}
      <div style={{ display: "flex", alignItems: "center", padding: "20px 56px", borderBottom: "1px solid var(--line-2)" }}>
        <div style={{ display: "flex", alignItems: "center", gap: 12 }}>
          <span className="nv-mark" style={{ width: 32, height: 32, fontSize: 19 }}>न</span>
          <span className="nv-serif" style={{ fontSize: 22 }}>Nivesh</span>
          <span className="nv-mono" style={{ fontSize: 10, letterSpacing: ".18em", color: "var(--ink-3)", textTransform: "uppercase" as const, marginLeft: 6 }}>COPILOT</span>
        </div>
        <div style={{ marginLeft: "auto", display: "flex", alignItems: "center", gap: 36 }}>
          <span onClick={() => navigate("/product")} style={{ fontSize: 14, color: "var(--ink-2)", cursor: "pointer" }}>Product</span>
          <span onClick={() => navigate("/for-advisors")} style={{ fontSize: 14, color: "var(--ink-2)", cursor: "pointer" }}>For advisors</span>
          <span onClick={() => navigate("/pricing")} style={{ fontSize: 14, color: "var(--ink-2)", cursor: "pointer" }}>Pricing</span>
          <span onClick={() => navigate("/login")} style={{ fontSize: 14, color: "var(--ink-2)", cursor: "pointer" }}>Sign in</span>
          <button className="nv-btn nv-btn-primary" style={{ padding: "9px 16px", fontSize: 13 }} onClick={() => navigate("/login")}>
            Check my portfolio →
          </button>
        </div>
      </div>

      {/* hero */}
      <div style={{ padding: "88px 56px 60px", maxWidth: 1280, margin: "0 auto", display: "grid", gridTemplateColumns: "1.05fr 1fr", gap: 80, alignItems: "center" }}>
        <div>
          <div style={{ display: "inline-flex", alignItems: "center", gap: 10, padding: "6px 14px 6px 8px", borderRadius: 999, border: "1px solid var(--line-2)", background: "var(--bg-1)", marginBottom: 28 }}>
            <span style={{ background: "var(--mint-soft)", color: "var(--mint)", fontSize: 10, fontFamily: "var(--mono)", letterSpacing: ".1em", padding: "3px 8px", borderRadius: 999, textTransform: "uppercase" as const }}>NEW</span>
            <span style={{ fontSize: 13, color: "var(--ink-2)" }}>Goal-aware rebalancing, live</span>
            <span style={{ color: "var(--ink-3)" }}>›</span>
          </div>
          <h1 className="nv-serif" style={{ fontSize: 84, lineHeight: 0.96, letterSpacing: "-0.035em", margin: 0 }}>
            Your portfolio,<br />
            <span style={{ fontStyle: "italic" }}>finally</span> legible<span style={{ color: "var(--mint)" }}>.</span>
          </h1>
          <p style={{ fontSize: 19, lineHeight: 1.55, color: "var(--ink-2)", marginTop: 28, maxWidth: 480, fontWeight: 400 }}>
            Nivesh reads every holding, scores its health and rewrites the report in plain language —
            so you know exactly what to fix and why.
          </p>
          <div style={{ display: "flex", gap: 12, marginTop: 40 }}>
            <button className="nv-btn nv-btn-primary" style={{ padding: "14px 22px", fontSize: 15 }} onClick={() => navigate("/login")}>
              Check my portfolio free
            </button>
            <button className="nv-btn" style={{ padding: "14px 22px", fontSize: 15 }}>Watch 90-second tour</button>
          </div>
          <div style={{ display: "flex", alignItems: "center", gap: 24, marginTop: 36 }}>
            {["SEBI-aligned", "Read-only access", "No card needed"].map((t) => (
              <div key={t} style={{ display: "flex", alignItems: "center", gap: 8, fontSize: 12, color: "var(--ink-3)", fontFamily: "var(--mono)", letterSpacing: ".04em" }}>
                <span style={{ width: 4, height: 4, borderRadius: "50%", background: "var(--mint)" }} />
                {t}
              </div>
            ))}
          </div>
        </div>

        {/* health preview card — real data when available */}
        <div className="nv-card" style={{ padding: 0, overflow: "hidden", position: "relative" }}>
          <div style={{ padding: "18px 22px", borderBottom: "1px solid rgb(var(--line) / 0.06)", display: "flex", alignItems: "center", gap: 12 }}>
            <span style={{ display: "flex", gap: 5 }}>
              <span style={{ width: 9, height: 9, borderRadius: "50%", background: "var(--ink-5)" }} />
              <span style={{ width: 9, height: 9, borderRadius: "50%", background: "var(--ink-5)" }} />
              <span style={{ width: 9, height: 9, borderRadius: "50%", background: "var(--ink-5)" }} />
            </span>
            <span className="nv-mono" style={{ fontSize: 11, color: "var(--ink-3)", letterSpacing: ".08em" }}>nivesh.app/health</span>
            <span className="nv-pill nv-pill-mint" style={{ marginLeft: "auto" }}>
              <span className="nv-dot" style={{ background: "var(--mint)" }} />
              {healthScore != null ? "LIVE" : "PREVIEW"}
            </span>
          </div>
          <div style={{ padding: "28px 24px 24px" }}>
            <div style={{ display: "flex", alignItems: "flex-end", justifyContent: "space-between", marginBottom: 18 }}>
              <div>
                <div className="nv-mono" style={{ fontSize: 10, letterSpacing: ".16em", color: "var(--ink-3)", textTransform: "uppercase" as const }}>Portfolio health</div>
                <div style={{ display: "flex", alignItems: "baseline", gap: 10, marginTop: 6 }}>
                  <span className="nv-serif" style={{ fontSize: 78, lineHeight: 0.9, letterSpacing: "-0.04em" }}>
                    {healthScore ?? "—"}
                  </span>
                  <span className="nv-mono" style={{ fontSize: 14, color: "var(--ink-3)" }}>/ 100</span>
                  {healthScore != null && (
                    <span className="nv-pill nv-pill-mint" style={{ marginLeft: 8 }}>{gradeLabel(healthScore)}</span>
                  )}
                </div>
              </div>
              {healthScore != null && (
                <span className="nv-mono" style={{ fontSize: 11, color: "var(--ink-3)" }}>your portfolio</span>
              )}
            </div>

            {/* segmented bar — from dimensions or placeholder */}
            {dimensions && dimensions.length > 0 ? (
              <div style={{ display: "flex", gap: 3, marginBottom: 22 }}>
                {dimensions.map(({ k, v }) => (
                  <div key={k} style={{ flex: 1 }}>
                    <div style={{ height: 36, background: "var(--bg-2)", borderRadius: 6, position: "relative" as const, overflow: "hidden" as const }}>
                      <div style={{ position: "absolute" as const, bottom: 0, left: 0, right: 0, height: `${v}%`, background: barColor(v), opacity: 0.9 }} />
                    </div>
                    <div className="nv-mono" style={{ fontSize: 9, color: "var(--ink-3)", marginTop: 6, textAlign: "center" as const, textTransform: "uppercase" as const, letterSpacing: ".06em" }}>
                      {k.replace(/_/g, " ").slice(0, 7)}
                    </div>
                  </div>
                ))}
              </div>
            ) : (
              <div style={{ display: "flex", gap: 3, marginBottom: 22 }}>
                {["risk", "concen", "diverse", "cost", "tax", "goals"].map((k) => (
                  <div key={k} style={{ flex: 1 }}>
                    <div style={{ height: 36, background: "var(--bg-2)", borderRadius: 6 }} />
                    <div className="nv-mono" style={{ fontSize: 9, color: "var(--ink-3)", marginTop: 6, textAlign: "center" as const, textTransform: "uppercase" as const, letterSpacing: ".06em" }}>{k}</div>
                  </div>
                ))}
              </div>
            )}

            {/* insight rows — from API or empty */}
            <div style={{ borderTop: "1px solid rgb(var(--line) / 0.06)" }}>
              {insights && insights.length > 0 ? (
                insights.slice(0, 3).map((r, i) => (
                  <div key={i} style={{ display: "flex", alignItems: "center", gap: 14, padding: "12px 2px", borderBottom: i < 2 ? "1px solid rgb(var(--line) / 0.06)" : "none" }}>
                    <span style={{ width: 3, alignSelf: "stretch", background: r.severity === "warm" ? "var(--amber)" : r.severity === "neg" ? "var(--danger-hex)" : "var(--mint)", borderRadius: 2 }} />
                    <div style={{ flex: 1 }}>
                      <div style={{ fontSize: 14, fontWeight: 500, letterSpacing: "-0.005em" }}>{r.title}</div>
                      <div className="nv-mono" style={{ fontSize: 10, color: "var(--ink-3)", letterSpacing: ".06em", marginTop: 3, textTransform: "uppercase" as const }}>{r.source}</div>
                    </div>
                    <span style={{ color: "var(--ink-3)", fontSize: 18 }}>›</span>
                  </div>
                ))
              ) : (
                <div style={{ padding: "18px 2px", textAlign: "center" as const }}>
                  <div className="nv-mono" style={{ fontSize: 11, color: "var(--ink-3)" }}>
                    Sign in to see your insights
                  </div>
                </div>
              )}
            </div>
          </div>
        </div>
      </div>

      {/* feature trio */}
      <div style={{ padding: "20px 56px 80px", maxWidth: 1280, margin: "0 auto" }}>
        <div style={{ display: "grid", gridTemplateColumns: "repeat(3, 1fr)", gap: 1, background: "rgb(var(--line) / 0.06)", border: "1px solid rgb(var(--line) / 0.06)", borderRadius: 18, overflow: "hidden" }}>
          {[
            { n: "01", t: "Read every holding", d: "Gmail CAS, statement PDF, or live broker. Equities, mutual funds, FDs, NPS — all reconciled in a single ledger." },
            { n: "02", t: "Score it across 20 checks", d: "Concentration, overlap, risk, cost, tax, goals. Each scored individually, then weighted into one A-to-D grade." },
            { n: "03", t: "Show you what to do", d: "Ranked actions with the exact fund or stock, the trade-off, and a one-tap simulation before you commit." },
          ].map((f) => (
            <div key={f.n} style={{ padding: 32, background: "var(--bg-1)" }}>
              <div className="nv-mono" style={{ fontSize: 11, color: "var(--mint)", letterSpacing: ".1em" }}>{f.n}</div>
              <div className="nv-serif" style={{ fontSize: 26, marginTop: 18, letterSpacing: "-0.02em" }}>{f.t}</div>
              <p style={{ fontSize: 14, color: "var(--ink-2)", lineHeight: 1.55, marginTop: 12, maxWidth: 320 }}>{f.d}</p>
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}
