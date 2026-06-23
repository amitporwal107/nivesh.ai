/**
 * Product — public marketing page describing what Nivesh does.
 * Grounded in real platform capabilities: CAS/broker ingestion, 20-check
 * health scoring, the Copilot, goal-aware rebalancing, tax harvesting.
 * Full-bleed, no sidebar (rendered outside RequireAuth).
 */
import { useNavigate } from "react-router-dom";
import MarketingShell from "@/components/marketing/MarketingShell";

const PILLARS = [
  {
    n: "01",
    t: "Read every holding",
    d: "Connect Gmail to pull CAS statements, upload a statement PDF, or link a live broker. Equities, mutual funds, FDs and NPS are reconciled into one ledger — holding by holding, to the rupee.",
    points: ["Gmail CAS sync", "NSDL / CDSL eCAS", "Live broker connect"],
  },
  {
    n: "02",
    t: "Score it across 20 checks",
    d: "Each holding is scored on concentration, overlap, risk, cost, tax efficiency and goal-fit. The checks roll up into six composite dimensions and a single A-to-D portfolio grade.",
    points: ["6 composite dimensions", "A–D health grade", "Per-holding breakdown"],
  },
  {
    n: "03",
    t: "Show you what to do",
    d: "Ranked actions name the exact fund or stock, the trade-off, and the expected impact — with a one-tap simulation so you see the result before you commit a single trade.",
    points: ["Ranked action plan", "Trade simulation", "Plain-language why"],
  },
];

const DIMENSIONS = [
  { k: "Risk", d: "Volatility, beta and drawdown exposure measured against your risk profile." },
  { k: "Concentration", d: "Single-stock, single-fund and sector limits, with overlap across funds flagged." },
  { k: "Diversification", d: "Asset-class and style spread — are you actually diversified or just holding more?" },
  { k: "Cost", d: "Expense ratios, exit loads and the drag of regular vs. direct plans." },
  { k: "Tax", d: "FIFO gains, harvestable losses and holding-period thresholds before you sell." },
  { k: "Goals", d: "Whether your allocation still matches the goals and horizon you set." },
];

const FEATURES = [
  {
    tag: "COPILOT",
    t: "Ask anything, get a grounded answer",
    d: "The Copilot reasons over your real holdings through specialist lenses — risk, tax, goals, concentration and more. Every answer cites the data it used; nothing is made up.",
  },
  {
    tag: "MARKETS",
    t: "A daily read on the market",
    d: "Market Pulse gives an editorial verdict, breadth and index moves — then tells you what it means for the portfolio you actually hold, not a generic index.",
  },
  {
    tag: "GOALS",
    t: "Goal-aware rebalancing",
    d: "Set goals and horizons once. Nivesh tracks drift against your targets and proposes the smallest set of trades to get back on plan.",
  },
  {
    tag: "TAX",
    t: "Harvest losses before March 31",
    d: "FIFO-accurate gain and loss tracking surfaces exactly what you can harvest, and what it saves you, while there's still time in the financial year.",
  },
];

export default function ProductPage() {
  const navigate = useNavigate();

  return (
    <MarketingShell active="product">
      {/* hero */}
      <div style={{ maxWidth: 1280, margin: "0 auto", padding: "80px 56px 40px", textAlign: "center" as const }}>
        <div style={{ display: "inline-flex", alignItems: "center", gap: 10, padding: "6px 14px 6px 8px", borderRadius: 999, border: "1px solid var(--line-2)", background: "var(--bg-1)", marginBottom: 28 }}>
          <span style={{ background: "var(--mint-soft)", color: "var(--mint)", fontSize: 10, fontFamily: "var(--mono)", letterSpacing: ".1em", padding: "3px 8px", borderRadius: 999, textTransform: "uppercase" as const }}>PRODUCT</span>
          <span style={{ fontSize: 13, color: "var(--ink-2)" }}>Read-only · SEBI-aligned</span>
        </div>
        <h1 className="nv-serif" style={{ fontSize: 72, lineHeight: 0.98, letterSpacing: "-0.035em", margin: 0 }}>
          One copilot for your<br />
          <span style={{ fontStyle: "italic" }}>whole</span> portfolio<span style={{ color: "var(--mint)" }}>.</span>
        </h1>
        <p style={{ fontSize: 19, lineHeight: 1.55, color: "var(--ink-2)", margin: "28px auto 0", maxWidth: 600 }}>
          Nivesh reconciles every holding you own, scores its health across twenty checks,
          and rewrites the report in plain language — so you always know what to fix and why.
        </p>
        <div style={{ display: "flex", gap: 12, marginTop: 40, justifyContent: "center" }}>
          <button className="nv-btn nv-btn-primary" style={{ padding: "14px 22px", fontSize: 15 }} onClick={() => navigate("/login")}>
            Check my portfolio free
          </button>
          <button className="nv-btn" style={{ padding: "14px 22px", fontSize: 15 }} onClick={() => navigate("/pricing")}>
            See pricing
          </button>
        </div>
      </div>

      {/* three pillars */}
      <div style={{ maxWidth: 1280, margin: "0 auto", padding: "40px 56px" }}>
        <div style={{ display: "grid", gridTemplateColumns: "repeat(3, 1fr)", gap: 1, background: "rgb(var(--line) / 0.06)", border: "1px solid rgb(var(--line) / 0.06)", borderRadius: 18, overflow: "hidden" }}>
          {PILLARS.map((f) => (
            <div key={f.n} style={{ padding: 32, background: "var(--bg-1)" }}>
              <div className="nv-mono" style={{ fontSize: 11, color: "var(--mint)", letterSpacing: ".1em" }}>{f.n}</div>
              <div className="nv-serif" style={{ fontSize: 26, marginTop: 18, letterSpacing: "-0.02em" }}>{f.t}</div>
              <p style={{ fontSize: 14, color: "var(--ink-2)", lineHeight: 1.55, marginTop: 12 }}>{f.d}</p>
              <div style={{ display: "flex", flexDirection: "column", gap: 8, marginTop: 18 }}>
                {f.points.map((p) => (
                  <div key={p} style={{ display: "flex", alignItems: "center", gap: 8, fontSize: 12, color: "var(--ink-3)", fontFamily: "var(--mono)", letterSpacing: ".04em" }}>
                    <span style={{ width: 4, height: 4, borderRadius: "50%", background: "var(--mint)" }} />
                    {p}
                  </div>
                ))}
              </div>
            </div>
          ))}
        </div>
      </div>

      {/* scoring dimensions */}
      <div style={{ maxWidth: 1280, margin: "0 auto", padding: "48px 56px" }}>
        <div style={{ textAlign: "center" as const, marginBottom: 40 }}>
          <div className="nv-mono" style={{ fontSize: 11, letterSpacing: ".16em", color: "var(--ink-3)", textTransform: "uppercase" as const }}>The health score</div>
          <h2 className="nv-serif" style={{ fontSize: 42, letterSpacing: "-0.03em", margin: "10px 0 0" }}>Six dimensions, one grade.</h2>
          <p style={{ fontSize: 16, color: "var(--ink-2)", margin: "14px auto 0", maxWidth: 540, lineHeight: 1.55 }}>
            Twenty individual checks roll into six composite dimensions, then into a single
            grade you can act on — every score traceable back to the holding that drove it.
          </p>
        </div>
        <div style={{ display: "grid", gridTemplateColumns: "repeat(3, 1fr)", gap: 16 }}>
          {DIMENSIONS.map((d) => (
            <div key={d.k} className="nv-card" style={{ padding: 24 }}>
              <div className="nv-serif" style={{ fontSize: 22, letterSpacing: "-0.02em" }}>{d.k}</div>
              <p style={{ fontSize: 13, color: "var(--ink-2)", lineHeight: 1.55, marginTop: 10 }}>{d.d}</p>
            </div>
          ))}
        </div>
      </div>

      {/* feature rows */}
      <div style={{ maxWidth: 1280, margin: "0 auto", padding: "32px 56px" }}>
        <div style={{ display: "grid", gridTemplateColumns: "repeat(2, 1fr)", gap: 16 }}>
          {FEATURES.map((f) => (
            <div key={f.tag} className="nv-card" style={{ padding: 32 }}>
              <span className="nv-pill nv-pill-mint">{f.tag}</span>
              <div className="nv-serif" style={{ fontSize: 28, letterSpacing: "-0.02em", marginTop: 18 }}>{f.t}</div>
              <p style={{ fontSize: 15, color: "var(--ink-2)", lineHeight: 1.6, marginTop: 12, maxWidth: 440 }}>{f.d}</p>
            </div>
          ))}
        </div>
      </div>

      {/* trust band */}
      <div style={{ maxWidth: 1280, margin: "0 auto", padding: "48px 56px" }}>
        <div className="nv-card-2" style={{ padding: "32px 40px", display: "flex", alignItems: "center", justifyContent: "space-between", flexWrap: "wrap" as const, gap: 24 }}>
          {[
            { t: "Read-only access", d: "We never place trades or move money." },
            { t: "Encrypted · never stored", d: "Statements are parsed in memory, not warehoused." },
            { t: "SEBI-aligned", d: "Analysis follows the IPS and risk-disclosure framework." },
            { t: "No card needed", d: "Check your portfolio health for free." },
          ].map((t) => (
            <div key={t.t} style={{ flex: "1 1 200px" }}>
              <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
                <span style={{ width: 6, height: 6, borderRadius: "50%", background: "var(--mint)" }} />
                <span style={{ fontSize: 14, fontWeight: 500 }}>{t.t}</span>
              </div>
              <p style={{ fontSize: 12, color: "var(--ink-3)", marginTop: 8, lineHeight: 1.5 }}>{t.d}</p>
            </div>
          ))}
        </div>
      </div>

      {/* CTA */}
      <div style={{ maxWidth: 1280, margin: "0 auto", padding: "24px 56px 16px", textAlign: "center" as const }}>
        <h2 className="nv-serif" style={{ fontSize: 44, letterSpacing: "-0.03em", margin: 0 }}>See your grade in two minutes.</h2>
        <p style={{ fontSize: 16, color: "var(--ink-2)", margin: "14px auto 0", maxWidth: 460 }}>
          Connect once. Get a full, plain-language read on everything you hold.
        </p>
        <div style={{ display: "flex", gap: 12, marginTop: 32, justifyContent: "center" }}>
          <button className="nv-btn nv-btn-primary" style={{ padding: "14px 22px", fontSize: 15 }} onClick={() => navigate("/login")}>
            Check my portfolio free
          </button>
          <button className="nv-btn" style={{ padding: "14px 22px", fontSize: 15 }} onClick={() => navigate("/for-advisors")}>
            I&apos;m an advisor
          </button>
        </div>
      </div>
    </MarketingShell>
  );
}
