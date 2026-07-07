/**
 * MFBestPracticesArticle — long-form body for the blog post
 * "Mutual fund investing: 7 best practices that actually build wealth".
 *
 * Investor-education piece. Hard statistics are sourced (AMFI/SEBI/Brinson) and
 * listed in the Sources block; the cost-drag figures are clearly labelled as an
 * illustration. Visuals reuse the app design tokens (--mint = keep/positive,
 * --ink-3 = muted comparison, --amber = reference) so they stay theme-aware.
 */
import { useNavigate } from "react-router-dom";
import { useIsMobile } from "@/hooks/use-is-mobile";

// Allocation guide by time horizon.
const HORIZONS = [
  { h: "Under 3 years", mix: "Mostly debt / liquid", why: "Capital safety first — equity can fall right when you need the money." },
  { h: "3–7 years", mix: "Balanced (~50–60% equity)", why: "Room to grow, cushioned by debt against a bad year." },
  { h: "7+ years", mix: "Equity-heavy (~70–80%)", why: "Long enough for volatility to average out and compounding to win." },
];

// Illustrative cost drag: ₹10L, 20 years, 12% (Direct) vs 11% (Regular, ~1% higher fee).
const COST = { direct: 96.5, regular: 80.6 }; // ₹ lakh final corpus

// Best-practice → Copilot capability.
const MAPS = [
  { p: "Goal first", s: "The goal engine anchors every suggestion to your real objective and time horizon — the fund fits the plan, not the other way round." },
  { p: "SIP discipline", s: "Goal-linked nudges reframe market dips, so you keep SIPs running exactly when they buy the most units." },
  { p: "Right allocation", s: "Scores your equity / debt / gold mix against your risk profile and flags when it drifts off target." },
  { p: "Direct, not Regular", s: "Flags Regular-plan cost leakage and the exact rupee drag versus the identical Direct plan." },
  { p: "No hidden overlap", s: "Detects funds that quietly hold the same stocks, so you stop paying active fees twice." },
  { p: "Stay invested", s: "A what-if backtest shows, with real history, why time in the market beats timing it." },
];

export default function MFBestPracticesArticle() {
  const navigate = useNavigate();
  const isMobile = useIsMobile();
  const pad = isMobile ? "0 4px" : "0";
  const regPct = Math.round((COST.regular / COST.direct) * 100); // Regular bar as % of Direct

  return (
    <div style={{ padding: pad }}>
      <p style={pStyle(isMobile)}>
        A mutual fund is the simplest way for most Indians to own a diversified, professionally managed
        portfolio — no stock-picking, no market-timing required. But the fund is only half the story. Whether
        you actually <b>build wealth</b> comes down to a handful of habits. Here are the seven that matter most,
        and the quiet mistakes that cost the most.
      </p>

      <h2 className="nv-serif" style={h2Style}>1 · Start from the goal, not the fund</h2>
      <p style={pStyle(isMobile)}>
        The first question is never "which fund is best?" — it's "what is this money for, and when do I need it?"
        A three-year goal (a car, a down-payment) and a twenty-year goal (retirement) belong in completely
        different funds. Your <b>time horizon</b> decides how much equity you can hold; the fund is just the
        vehicle. Pick the destination first, then the vehicle.
      </p>

      <h2 className="nv-serif" style={h2Style}>2 · Automate with SIPs — and don’t stop them</h2>
      <p style={pStyle(isMobile)}>
        A Systematic Investment Plan turns investing into a standing instruction: a fixed amount, every month,
        automatically. It removes the two hardest decisions — how much, and when — and averages your cost across
        highs and lows. The catch is discipline. When markets fell, investors cancelled SIPs at exactly the
        wrong moment: the <b>SIP stoppage ratio climbed from 51% (Jul 2024) to over 100% by Jan 2025</b> — more
        SIPs stopped than started. A falling market is precisely when your SIP buys the most units. Keep it running.
      </p>

      <h2 className="nv-serif" style={h2Style}>3 · Get your asset allocation right — the biggest lever</h2>
      <p style={pStyle(isMobile)}>
        How you split money across <b>equity, debt and gold</b> matters more than which specific fund you pick.
        The classic Brinson study found that asset allocation explains the large majority of the variation in a
        portfolio’s long-term returns. Match the mix to your horizon, then rebalance once a year to bring it back:
      </p>
      <div style={{ display: "grid", gridTemplateColumns: isMobile ? "1fr" : "repeat(3, 1fr)", gap: 12, margin: "6px 0 20px" }}>
        {HORIZONS.map((row) => (
          <div key={row.h} className="nv-card" style={{ padding: "18px 18px", borderTop: "3px solid var(--mint)" }}>
            <div className="nv-mono" style={{ fontSize: 10, letterSpacing: ".1em", color: "var(--mint)", textTransform: "uppercase" }}>{row.h}</div>
            <div className="nv-serif" style={{ fontSize: 18, letterSpacing: "-0.01em", margin: "8px 0 6px" }}>{row.mix}</div>
            <div style={{ fontSize: 13, lineHeight: 1.5, color: "var(--ink-3)" }}>{row.why}</div>
          </div>
        ))}
      </div>

      <h2 className="nv-serif" style={h2Style}>4 · Choose Direct plans over Regular</h2>
      <p style={pStyle(isMobile)}>
        Every fund comes in two versions. A <b>Regular</b> plan pays a trail commission to a distributor; a
        <b> Direct</b> plan doesn’t — so its expense ratio is lower, often by roughly 0.5–1% a year. That gap
        sounds trivial and compounds brutally. Same fund, same manager — you simply keep more by going Direct.
      </p>
      <div className="nv-card" style={{ padding: isMobile ? "22px 20px" : "26px 28px", margin: "8px 0 20px" }}>
        <div className="nv-mono" style={{ fontSize: 10, letterSpacing: ".14em", color: "var(--ink-3)", textTransform: "uppercase", marginBottom: 16 }}>
          What a ~1% higher fee costs — ₹10 lakh, 20 years
        </div>
        {[
          { k: "Direct plan (net ~12%)", v: COST.direct, w: 100, c: "var(--mint)", strong: true },
          { k: "Regular plan (net ~11%)", v: COST.regular, w: regPct, c: "var(--ink-3)", strong: false },
        ].map((b) => (
          <div key={b.k} style={{ marginBottom: 12 }}>
            <div style={{ display: "flex", justifyContent: "space-between", alignItems: "baseline", marginBottom: 6 }}>
              <span style={{ fontSize: 13.5, color: "var(--ink-2)" }}>{b.k}</span>
              <span className="nv-serif" style={{ fontSize: 17, color: b.strong ? "var(--mint)" : "var(--ink-2)" }}>₹{b.v}L</span>
            </div>
            <div style={{ height: 14, background: "var(--bg-2)", borderRadius: 999, overflow: "hidden" }}>
              <div style={{ height: "100%", width: `${b.w}%`, background: b.c, opacity: b.strong ? 0.95 : 0.55, borderRadius: 999 }} />
            </div>
          </div>
        ))}
        <div className="nv-mono" style={{ fontSize: 11, color: "var(--ink-3)", marginTop: 14, letterSpacing: ".03em" }}>
          A ~1% higher fee ≈ <b style={{ color: "var(--danger-hex)" }}>₹16 lakh</b> less at the finish. Illustrative
          (₹10L lumpsum, 20 years, 12% vs 11% net).
        </div>
      </div>

      <h2 className="nv-serif" style={h2Style}>5 · Diversify — but don’t over-diversify</h2>
      <p style={pStyle(isMobile)}>
        Diversification lowers risk, but past a point it only adds cost and clutter. <b>Four to six</b> well-chosen
        funds across categories is plenty. Holding a dozen usually means they overlap — several funds quietly
        owning the same top stocks — so you pay active fees for what is effectively an index. Check the overlap
        before you add another fund.
      </p>

      <h2 className="nv-serif" style={h2Style}>6 · Stop chasing last year’s winner</h2>
      <p style={pStyle(isMobile)}>
        The most expensive habit is buying whatever topped the charts last year. Winners rotate; today’s #1 is
        often tomorrow’s laggard, and “past performance is not indicative of future results” is a rule, not a
        disclaimer. Judge a fund on consistency, cost, mandate and fit — not one hot year. About <b>half of
        equity MF investors exit within two years</b>, often to chase the next winner, and never let compounding
        do its work.
      </p>

      <h2 className="nv-serif" style={h2Style}>7 · Give it time, and review — don’t refresh</h2>
      <p style={{ ...pStyle(isMobile), marginBottom: 6 }}>
        Equity funds reward patience. Give equity money at least <b>five to seven years</b>, and check your
        portfolio once or twice a year against your goals — not once a day against the market. Daily watching
        breeds panic decisions; an annual review breeds good ones. The biggest driver of returns you can actually
        control is simply <b>staying invested</b>.
      </p>

      {/* SOLUTION */}
      <h2 className="nv-serif" style={{ ...h2Style, color: "var(--mint)" }}>How Nivesh Copilot helps</h2>
      <p style={pStyle(isMobile)}>
        Every one of these habits is easier with a data-grounded, goal-fit copilot doing the watching for you.
      </p>
      <div style={{ display: "grid", gridTemplateColumns: isMobile ? "1fr" : "repeat(2, 1fr)", gap: 12, margin: "10px 0 8px" }}>
        {MAPS.map((m, i) => (
          <div key={m.p} className="nv-card" style={{ padding: "16px 18px", borderLeft: "3px solid var(--mint)", gridColumn: !isMobile && i === MAPS.length - 1 && MAPS.length % 2 === 1 ? "1 / -1" : undefined }}>
            <div className="nv-mono" style={{ fontSize: 10, letterSpacing: ".08em", color: "var(--mint)", textTransform: "uppercase" }}>{m.p}</div>
            <div style={{ fontSize: 14.5, lineHeight: 1.5, marginTop: 7 }}>{m.s}</div>
          </div>
        ))}
      </div>

      {/* CTA */}
      <div className="nv-card" style={{ padding: isMobile ? "24px 20px" : "30px 32px", margin: "28px 0 8px", textAlign: "center" }}>
        <h3 className="nv-serif" style={{ fontSize: isMobile ? 26 : 32, letterSpacing: "-0.02em", margin: 0 }}>
          Put these to work on your own portfolio
        </h3>
        <p style={{ fontSize: 15, color: "var(--ink-2)", margin: "12px auto 0", maxWidth: 460, lineHeight: 1.6 }}>
          Read-only, SEBI-aligned analysis that grades your funds on allocation, overlap, cost and goal-fit —
          then tells you exactly what to fix, in plain language.
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
        <div className="nv-mono" style={{ fontSize: 10, letterSpacing: ".14em", color: "var(--ink-4)", textTransform: "uppercase", marginBottom: 10 }}>Sources &amp; notes</div>
        <p style={{ fontSize: 12.5, color: "var(--ink-3)", lineHeight: 1.7, margin: 0 }}>
          Outlook Money / AMFI — SIP stoppage ratio, Jul 2024–Jan 2025 · Business Standard / SEBI — ~50% of
          equity MF investors exit under two years · Brinson, Hood &amp; Beebower — asset allocation and the
          variation in long-term portfolio returns. Cost-drag figures are <b>illustrative</b> (₹10 lakh lumpsum,
          20 years, 12% vs 11% net) to show how a ~1% fee compounds, not a forecast. Mutual fund investments are
          subject to market risks; read all scheme-related documents carefully.
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
