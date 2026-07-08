/**
 * RetailLossesArticle — long-form body for the blog post
 * "Why Indian retail investors lose money — and how Nivesh Copilot helps".
 *
 * All statistics are sourced (SEBI / NCFE-RBI / AMFI / Business Standard); the
 * Sources block at the foot lists each. Charts are built from the app design
 * tokens (--danger-hex = loss, --mint = solution, --amber = reference line) so
 * they match the marketing surface and stay theme-aware.
 */
import { useNavigate } from "react-router-dom";
import { useIsMobile } from "@/hooks/use-is-mobile";

const HERO_STATS = [
  { n: "93%", l: "of F&O traders lost money", s: "FY22–FY24 · SEBI" },
  { n: "₹1.8L Cr", l: "wiped out in F&O", s: "aggregate, 3 years · SEBI" },
  { n: "70%", l: "of intraday traders lost money", s: "FY23 · SEBI" },
];

const GAP_BARS = [
  { k: "Adults NOT financially literate", v: 73 },
  { k: "F&O traders in the red", v: 93 },
  { k: "Intraday traders in the red", v: 70 },
  { k: "Equity MF investors who exit < 2 yrs", v: 50 },
];

// SIP stoppage ratio — Jul 2024 → Jan 2025 (Outlook Money / AMFI).
const SIP = [
  { x: "Jul 2024", v: 51 },
  { x: "Dec 2024", v: 83 },
  { x: "Jan 2025", v: 109 },
];

const MAPS = [
  { p: "No knowledge", s: "Investing as a plain-language chat — no jargon barrier for the ~73% who aren't financially literate." },
  { p: "Speculation trap", s: "Goal-anchored plans and a “what-if” backtest that shows, with real history, why patience beats punting." },
  { p: "Panic & churn", s: "Every nudge tied to your goal — reframing short-term dips and curbing panic-exits." },
  { p: "Wrong / no recommendation", s: "Data-scored, portfolio-aware picks that read your real holdings from your CAS." },
  { p: "Misselling for commission", s: "Advice driven by suitability, not commissions — the same engine powers honest advisor tools." },
];

// Map a SIP value (0–120%) to a y-coordinate in the 200-tall viewBox.
const sipY = (v: number) => Math.round(160 - (v / 120) * 140);

export default function RetailLossesArticle() {
  const navigate = useNavigate();
  const isMobile = useIsMobile();
  const pad = isMobile ? "0 4px" : "0";
  const px = [90, 330, 560];

  return (
    <div style={{ padding: pad }}>
      {/* HERO STAT TILES */}
      <div style={{ display: "grid", gridTemplateColumns: isMobile ? "1fr" : "repeat(3, 1fr)", gap: 14, margin: "8px 0 40px" }}>
        {HERO_STATS.map((t) => (
          <div key={t.l} className="nv-card" style={{ padding: 22, borderLeft: "3px solid var(--danger-hex)" }}>
            <div className="nv-serif" style={{ fontSize: isMobile ? 40 : 46, lineHeight: 1, letterSpacing: "-0.03em", color: "var(--danger-hex)" }}>{t.n}</div>
            <div style={{ fontSize: 14, fontWeight: 500, marginTop: 12 }}>{t.l}</div>
            <div className="nv-mono" style={{ fontSize: 11, color: "var(--ink-3)", marginTop: 4, letterSpacing: ".04em" }}>{t.s}</div>
          </div>
        ))}
      </div>

      <p style={pStyle(isMobile)}>
        India is living through a retail-investing boom. Demat accounts jumped from <b>3.6 crore in 2019 to
        19.4 crore in 2025</b> — roughly <b>4 crore new investors added in FY25 alone</b>, most of them
        first-timers from Tier-2 and Tier-3 cities. But the boom outran the knowledge to match it: only about
        <b> 27% of Indian adults are financially literate</b> (NCFE–RBI). Tens of millions arrived at the
        riskiest end of the market with the least preparation.
      </p>

      <h2 className="nv-serif" style={h2Style}>The gap behind the losses</h2>
      <p style={pStyle(isMobile)}>
        The damage shows up first where speculation is easiest. SEBI's own studies are blunt about it.
      </p>

      {/* GAP BAR CHART */}
      <div className="nv-card" style={{ padding: isMobile ? "22px 20px" : "26px 28px", margin: "8px 0 20px" }}>
        <div style={{ display: "flex", flexDirection: "column", gap: 16 }}>
          {GAP_BARS.map((b) => (
            <div key={b.k}>
              <div style={{ display: "flex", justifyContent: "space-between", alignItems: "baseline", marginBottom: 7 }}>
                <span style={{ fontSize: 13.5, color: "var(--ink-2)" }}>{b.k}</span>
                <span className="nv-serif" style={{ fontSize: 16, color: "var(--danger-hex)" }}>{b.v}%</span>
              </div>
              <div style={{ height: 12, background: "var(--bg-2)", borderRadius: 999, overflow: "hidden" }}>
                <div style={{ height: "100%", width: `${b.v}%`, background: "var(--danger-hex)", opacity: 0.9, borderRadius: 999 }} />
              </div>
            </div>
          ))}
        </div>
        <div className="nv-mono" style={{ fontSize: 11, color: "var(--ink-3)", marginTop: 18, letterSpacing: ".03em" }}>
          Only ~27% of Indian adults are financially literate — yet millions trade the riskiest products.
        </div>
      </div>

      <p style={pStyle(isMobile)}>
        <b>93% of individual F&amp;O traders lost money between FY22 and FY24</b>, with aggregate losses
        exceeding <b>₹1.8 lakh crore</b> over three years; the top 3.5% of loss-makers averaged a
        <b> ₹28 lakh loss each</b>. In FY25 the pattern held — roughly <b>₹1.05 lakh crore</b> of net F&amp;O
        losses, ~90% of participants in the red. In the cash market, <b>7 in 10 intraday traders lost money</b>
        in FY23, even as intraday participation jumped 4.6× — from 15 lakh to 69 lakh in four years.
      </p>

      <h2 className="nv-serif" style={h2Style}>Even patient money quits too early</h2>
      <p style={pStyle(isMobile)}>
        Mutual funds are the "safe" path — but behaviour undoes the maths. About <b>half of equity MF
        investors exit within two years</b>, and a quarter within six months, so compounding never gets to
        work. Worse, investors quit exactly when they should hold: as markets dipped, the SIP stoppage ratio
        climbed from <b>51% (Jul 2024) to 83% (Dec 2024), then spiked past 100% in Jan 2025</b> — more SIPs
        being cancelled than started.
      </p>

      {/* SIP TREND SVG */}
      <div className="nv-card" style={{ padding: isMobile ? "20px 16px" : "24px 28px", margin: "8px 0 20px" }}>
        <div className="nv-mono" style={{ fontSize: 10, letterSpacing: ".14em", color: "var(--ink-3)", textTransform: "uppercase", marginBottom: 10 }}>
          SIP stoppage ratio
        </div>
        <svg viewBox="0 0 640 200" width="100%" role="img"
          aria-label="SIP stoppage ratio rose from 51% in July 2024 to 83% in December 2024 to 109% in January 2025"
          style={{ display: "block" }}>
          {/* 100% reference line */}
          <line x1="40" y1={sipY(100)} x2="620" y2={sipY(100)} stroke="var(--amber)" strokeDasharray="4 4" strokeWidth="1.5" opacity="0.8" />
          <text x="620" y={sipY(100) - 7} textAnchor="end" fontSize="11" fill="var(--amber)" fontWeight="700">100% = more quitting than joining</text>
          {/* baseline */}
          <line x1="40" y1="160" x2="620" y2="160" stroke="var(--line-2)" strokeWidth="1" />
          {/* trend line */}
          <polyline points={SIP.map((d, i) => `${px[i]},${sipY(d.v)}`).join(" ")} fill="none" stroke="var(--danger-hex)" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round" />
          {SIP.map((d, i) => (
            <g key={d.x}>
              <circle cx={px[i]} cy={sipY(d.v)} r={i === 2 ? 6.5 : 5.5} fill={i === 2 ? "var(--danger-hex)" : "var(--bg-1)"} stroke="var(--danger-hex)" strokeWidth="2.5" />
              <text x={px[i]} y={sipY(d.v) - 13} textAnchor="middle" fontSize="14" fontWeight="700" fill="var(--danger-hex)">{d.v}%</text>
              <text x={px[i]} y="182" textAnchor="middle" fontSize="12" fontWeight="600" fill="var(--ink-3)">{d.x}</text>
            </g>
          ))}
        </svg>
        <div className="nv-mono" style={{ fontSize: 11, color: "var(--ink-3)", marginTop: 12, letterSpacing: ".03em" }}>
          When markets dipped, investors abandoned SIPs at the exact moment discipline pays most.
        </div>
      </div>

      <h2 className="nv-serif" style={h2Style}>And the advice is often conflicted</h2>
      <p style={pStyle(isMobile)}>
        Behind much of this is advice that isn't aligned with the investor. Banks and national distributors
        have long churned schemes and pushed high-commission products; a 2025 survey found <b>1,655 bank
        relationship managers said their seniors regularly asked them to mis-sell</b>. The problem is large
        enough that the RBI now requires banks and NBFCs to <b>fully refund customers for mis-sold products</b>
        from 1 January 2027. When the recommendation is optimised for commission, the investor gets the wrong
        product for their goal — and pays for it.
      </p>

      <p style={{ ...pStyle(isMobile), fontWeight: 500, color: "var(--ink)" }}>
        The losses trace to three compounding failures: <b>no knowledge</b>, <b>no unbiased goal-fit
        recommendation</b>, and <b>advice corrupted by commission</b>.
      </p>

      {/* SOLUTION */}
      <h2 className="nv-serif" style={{ ...h2Style, color: "var(--mint)" }}>How Nivesh Copilot helps</h2>
      <p style={pStyle(isMobile)}>
        Nivesh Copilot attacks all three — a data-grounded, goal-fit, conflict-free advisor in every pocket.
      </p>
      <div style={{ display: "grid", gridTemplateColumns: isMobile ? "1fr" : "repeat(2, 1fr)", gap: 12, margin: "10px 0 8px" }}>
        {MAPS.map((m, i) => (
          <div key={m.p} className="nv-card" style={{ padding: "16px 18px", borderLeft: "3px solid var(--mint)", gridColumn: !isMobile && i === MAPS.length - 1 && MAPS.length % 2 === 1 ? "1 / -1" : undefined }}>
            <div className="nv-mono" style={{ fontSize: 10, letterSpacing: ".08em", color: "var(--ink-3)", textTransform: "uppercase" }}>
              Problem · <span style={{ color: "var(--danger-hex)" }}>{m.p}</span>
            </div>
            <div style={{ color: "var(--mint)", fontWeight: 700, margin: "7px 0 3px", fontSize: 13 }}>→</div>
            <div style={{ fontSize: 14.5, lineHeight: 1.5 }}>{m.s}</div>
          </div>
        ))}
      </div>

      {/* CTA */}
      <div className="nv-card" style={{ padding: isMobile ? "24px 20px" : "30px 32px", margin: "28px 0 8px", textAlign: "center" }}>
        <h3 className="nv-serif" style={{ fontSize: isMobile ? 26 : 32, letterSpacing: "-0.02em", margin: 0 }}>
          See where your portfolio actually stands
        </h3>
        <p style={{ fontSize: 15, color: "var(--ink-2)", margin: "12px auto 0", maxWidth: 440, lineHeight: 1.6 }}>
          Read-only, SEBI-aligned analysis that grades your holdings and tells you what to fix — in plain language.
        </p>
        <div style={{ display: "flex", gap: 12, justifyContent: "center", flexWrap: "wrap", marginTop: 22 }}>
          <button className="nv-btn nv-btn-primary" style={{ padding: "14px 22px", fontSize: 15 }} onClick={() => navigate("/login")}>
            Check my portfolio free
          </button>
          <button className="nv-btn" style={{ padding: "14px 22px", fontSize: 15 }} onClick={() => navigate("/copilot")}>
            See the Copilot
          </button>
        </div>
      </div>

      {/* SOURCES */}
      <div style={{ borderTop: "1px solid var(--line-2)", marginTop: 28, paddingTop: 18 }}>
        <div className="nv-mono" style={{ fontSize: 10, letterSpacing: ".14em", color: "var(--ink-4)", textTransform: "uppercase", marginBottom: 10 }}>Sources</div>
        <p style={{ fontSize: 12.5, color: "var(--ink-3)", lineHeight: 1.7, margin: 0 }}>
          SEBI (Sep 2024) — 93% of F&amp;O traders lost money, ₹1.8L cr over FY22–24 · SEBI (Jul 2024) — 70% of
          intraday traders in loss · NCFE–RBI Financial Literacy Survey (2019) — 27% financially literate ·
          Outlook Business — demat accounts 3.6→19.4 cr (2019–25) · Business Standard / SEBI — ~50% of equity MF
          investors exit under 2 years · Outlook Money / AMFI — SIP stoppage ratio, Jul 2024–Jan 2025 ·
          Moneylife — bank mis-selling survey &amp; RBI refund directions.
        </p>
      </div>
    </div>
  );
}

const h2Style: React.CSSProperties = {
  fontSize: 28,
  letterSpacing: "-0.02em",
  margin: "34px 0 12px",
};

function pStyle(isMobile: boolean): React.CSSProperties {
  return {
    fontSize: isMobile ? 16 : 17,
    lineHeight: 1.7,
    color: "var(--ink-2)",
    margin: "0 0 18px",
  };
}
