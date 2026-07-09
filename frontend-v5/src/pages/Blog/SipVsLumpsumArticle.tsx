/**
 * SipVsLumpsumArticle — conversational guide: SIP vs lump sum. Original content;
 * any rupee figures are clearly illustrative, not forecasts.
 */
import { useNavigate } from "react-router-dom";
import { useIsMobile } from "@/hooks/use-is-mobile";
import ChatTeaser from "./ChatTeaser";
import { AskNivesh, Disclaimer, h2Style, pStyle, ulStyle } from "./TypesOfFundsArticle";

export default function SipVsLumpsumArticle() {
  const navigate = useNavigate();
  const isMobile = useIsMobile();
  return (
    <div style={{ padding: isMobile ? "0 4px" : "0" }}>
      <ChatTeaser
        q="Got a ₹3 lakh bonus. Should I SIP it or just dump it all in?"
        a="Depends on where the money is and how you'll sleep. Already have the cash and a long horizon? Lump sum usually wins mathematically. Nervous, or it's from monthly salary? SIP. Here's the honest breakdown."
      />

      <h2 className="nv-serif" style={h2Style}>First, the actual difference</h2>
      <p style={pStyle(isMobile)}>
        A <b>lump sum</b> puts all your money to work on day one. A <b>SIP</b> (Systematic Investment Plan)
        drips a fixed amount in every month, automatically. Same funds, different <em>timing</em> — and timing
        is the whole debate.
      </p>

      <h2 className="nv-serif" style={h2Style}>When lump sum wins</h2>
      <p style={pStyle(isMobile)}>
        If the money is <b>already sitting in your bank</b> and you won't need it for years, getting it invested
        sooner usually beats waiting — markets rise more often than they fall, so time in the market does the
        heavy lifting. Drip-feeding cash you already have often just means it earns savings-account interest
        while it waits.
      </p>

      <h2 className="nv-serif" style={h2Style}>When SIP wins</h2>
      <ul style={ulStyle(isMobile)}>
        <li><b>The money arrives monthly</b> (from salary) — you can't lump-sum what you don't have yet.</li>
        <li><b>Markets feel scary / near highs</b> — spreading entries averages your cost and removes the "did I buy at the top?" regret.</li>
        <li><b>You want it on autopilot</b> — a SIP is a standing instruction, so discipline doesn't depend on willpower.</li>
      </ul>
      <p style={pStyle(isMobile)}>
        The quiet superpower of a SIP shows up in a falling market: the same ₹10,000 buys <em>more</em> units
        when prices drop. That only works if you <b>don't stop it</b> when things look grim — which is exactly
        when most people cancel.
      </p>

      <h2 className="nv-serif" style={h2Style}>The middle path most people miss: an STP</h2>
      <p style={pStyle(isMobile)}>
        Sitting on a big amount but nervous about one-shotting it? Park it in a <b>liquid fund</b> and set up a
        <b> Systematic Transfer Plan</b> to move a slice into equity each week or month. You get lump-sum-style
        deployment with SIP-style nerves — best of both.
      </p>

      <div className="nv-card" style={{ padding: isMobile ? "20px 18px" : "22px 26px", margin: "8px 0 20px", borderLeft: "3px solid var(--mint)" }}>
        <div className="nv-mono" style={{ fontSize: 10, letterSpacing: ".12em", color: "var(--mint)", textTransform: "uppercase", marginBottom: 12 }}>The rule of thumb</div>
        <ul style={{ ...ulStyle(isMobile), margin: 0 }}>
          <li>Money already in hand + long horizon + steady nerves → <b>lump sum</b> (or an STP over 3–6 months).</li>
          <li>Money from monthly income, or you'd panic at a dip → <b>SIP</b>, and keep it running.</li>
        </ul>
      </div>

      <AskNivesh navigate={navigate} isMobile={isMobile} line="Tell Nivesh Copilot the amount, the source, and your timeline — it'll tell you SIP, lump sum, or a staggered plan, and why." />
      <Disclaimer />
    </div>
  );
}
