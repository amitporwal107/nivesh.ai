/**
 * TypesOfFundsArticle — conversational beginner's guide to the types of mutual
 * funds in India. Original content; evergreen definitions (no time-sensitive stats).
 */
import { useNavigate } from "react-router-dom";
import { useIsMobile } from "@/hooks/use-is-mobile";
import ChatTeaser from "./ChatTeaser";

const FAMILIES = [
  { t: "Equity funds", r: "Higher risk · 7+ yrs", d: "Own a basket of stocks. Large-cap (steadier), mid/small-cap (racier), flexi-cap (manager chooses), plus ELSS (tax-saver). This is your long-term growth engine." },
  { t: "Debt funds", r: "Lower risk · months–3 yrs", d: "Lend to governments and companies. Liquid and short-duration for parking cash; corporate-bond and gilt for a bit more yield. Calmer, for near-term money." },
  { t: "Hybrid funds", r: "Medium · 3–5 yrs", d: "A mix of equity and debt in one fund. Balanced-advantage and aggressive-hybrid options give you growth with a built-in cushion — good for first-timers." },
  { t: "Index funds & ETFs", r: "Market risk · 7+ yrs", d: "Skip the manager and just track an index like the Nifty 50. Very low cost, no bet on stock-picking skill — you get the market's return, minus a tiny fee." },
];

export default function TypesOfFundsArticle() {
  const navigate = useNavigate();
  const isMobile = useIsMobile();
  return (
    <div style={{ padding: isMobile ? "0 4px" : "0" }}>
      <ChatTeaser
        q="There are literally thousands of funds. Where do I even start?"
        a="Start with the type, not the name. There are really just a few families — pick the one that matches your goal and timeline, then choose a fund inside it. Here's the whole map."
      />

      <p style={pStyle(isMobile)}>
        A mutual fund pools money from lots of people, hands it to a professional manager, and buys a
        diversified basket of investments — so you don't have to pick stocks or bonds yourself. You own
        <b> units</b>, and their price (the <b>NAV</b>) moves with the basket. The trick to not feeling lost
        is realising that every fund belongs to one of a handful of families.
      </p>

      <h2 className="nv-serif" style={h2Style}>The four families you actually need to know</h2>
      <div style={{ display: "grid", gridTemplateColumns: isMobile ? "1fr" : "repeat(2, 1fr)", gap: 12, margin: "6px 0 22px" }}>
        {FAMILIES.map((f) => (
          <div key={f.t} className="nv-card" style={{ padding: "18px 18px", borderTop: "3px solid var(--mint)" }}>
            <div style={{ display: "flex", justifyContent: "space-between", alignItems: "baseline", gap: 8 }}>
              <span className="nv-serif" style={{ fontSize: 19 }}>{f.t}</span>
              <span className="nv-mono" style={{ fontSize: 10, color: "var(--mint)", letterSpacing: ".06em", textAlign: "right" }}>{f.r}</span>
            </div>
            <p style={{ fontSize: 13.5, lineHeight: 1.55, color: "var(--ink-3)", marginTop: 8 }}>{f.d}</p>
          </div>
        ))}
      </div>

      <h2 className="nv-serif" style={h2Style}>“Which one should I actually pick?”</h2>
      <p style={pStyle(isMobile)}>
        Work backwards from the money, not the fund. Ask two questions: <b>when do I need this money</b>, and
        <b> how much of a dip can I stomach?</b>
      </p>
      <ul style={ulStyle(isMobile)}>
        <li><b>Under 3 years</b> (emergency fund, a near goal) → debt / liquid. Safety first.</li>
        <li><b>3–5 years</b> → hybrid, or a mostly-debt mix. Some growth, some cushion.</li>
        <li><b>7+ years</b> (retirement, a child's education) → equity or index funds. Time smooths the bumps.</li>
        <li><b>Want to save tax under the old regime?</b> → ELSS (an equity fund with a 3-year lock-in and a Section-80C deduction).</li>
      </ul>

      <h2 className="nv-serif" style={h2Style}>A couple of rookie traps</h2>
      <p style={pStyle(isMobile)}>
        Don't buy ten funds that all hold the same top stocks — that's fake diversification at real cost.
        Don't judge a fund by last year's chart-topping return. And match the fund's risk to <em>your</em>
        timeline, not to whatever's trending. Boring and matched beats exciting and mismatched, every time.
      </p>

      <AskNivesh navigate={navigate} isMobile={isMobile} line="Not sure which family fits your goal? Tell Nivesh Copilot what you're saving for and by when — it'll map it for you." />
      <Disclaimer />
    </div>
  );
}

/* ---- shared bits reused across the conversational articles ---- */
export function AskNivesh({ navigate, isMobile, line }: { navigate: (p: string) => void; isMobile: boolean; line: string }) {
  return (
    <div className="nv-card" style={{ padding: isMobile ? "24px 20px" : "30px 32px", margin: "28px 0 8px", textAlign: "center", borderTop: "3px solid var(--mint)" }}>
      <h3 className="nv-serif" style={{ fontSize: isMobile ? 24 : 30, letterSpacing: "-0.02em", margin: 0 }}>
        Just ask, in plain language
      </h3>
      <p style={{ fontSize: 15, color: "var(--ink-2)", margin: "12px auto 0", maxWidth: 460, lineHeight: 1.6 }}>{line}</p>
      <div style={{ display: "flex", gap: 12, justifyContent: "center", flexWrap: "wrap", marginTop: 22 }}>
        <button className="nv-btn nv-btn-primary" style={{ padding: "14px 22px", fontSize: 15 }} onClick={() => navigate("/login")}>
          Ask Nivesh Copilot
        </button>
        <button className="nv-btn" style={{ padding: "14px 22px", fontSize: 15 }} onClick={() => navigate("/copilot")}>
          See the Copilot
        </button>
      </div>
    </div>
  );
}

export function Disclaimer() {
  return (
    <p style={{ fontSize: 12, color: "var(--ink-4)", lineHeight: 1.6, marginTop: 20 }}>
      Educational content, not personalised advice. Mutual fund investments are subject to market risks;
      read all scheme-related documents carefully. Tax rules can change — confirm the current position before acting.
    </p>
  );
}

export const h2Style: React.CSSProperties = { fontSize: 26, letterSpacing: "-0.02em", margin: "32px 0 12px" };
export function pStyle(isMobile: boolean): React.CSSProperties {
  return { fontSize: isMobile ? 16 : 17, lineHeight: 1.7, color: "var(--ink-2)", margin: "0 0 16px" };
}
export function ulStyle(isMobile: boolean): React.CSSProperties {
  return { fontSize: isMobile ? 16 : 17, lineHeight: 1.8, color: "var(--ink-2)", margin: "0 0 18px", paddingLeft: 22 };
}
