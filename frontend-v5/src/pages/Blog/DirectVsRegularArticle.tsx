/**
 * DirectVsRegularArticle — conversational deep-dive on Direct vs Regular mutual
 * fund plans. Cost-drag figures are illustrative (₹10L, 20y, 12% vs 11%).
 */
import { useNavigate } from "react-router-dom";
import { useIsMobile } from "@/hooks/use-is-mobile";
import ChatTeaser from "./ChatTeaser";
import { AskNivesh, Disclaimer, h2Style, pStyle, ulStyle } from "./TypesOfFundsArticle";

const COST = { direct: 96.5, regular: 80.6 }; // ₹ lakh final corpus, illustrative

export default function DirectVsRegularArticle() {
  const navigate = useNavigate();
  const isMobile = useIsMobile();
  const regPct = Math.round((COST.regular / COST.direct) * 100);
  return (
    <div style={{ padding: isMobile ? "0 4px" : "0" }}>
      <ChatTeaser
        q="My app shows 'Direct' and 'Regular' versions of the same fund. What's the catch?"
        a="Same fund, same manager, same portfolio — but Regular quietly pays a distributor commission every year, so its fee is higher. Over decades that gap can cost you lakhs. Go Direct and you simply keep more. Here's the maths."
      />

      <h2 className="nv-serif" style={h2Style}>What's actually different</h2>
      <p style={pStyle(isMobile)}>
        A <b>Regular</b> plan bakes a trail commission for a distributor or agent into the fund's annual expense
        ratio. A <b>Direct</b> plan cuts out that commission, so its expense ratio is lower — often by roughly
        <b> 0.5% to 1% a year</b>. Everything else — the holdings, the fund manager, the returns before fees — is
        identical.
      </p>

      <h2 className="nv-serif" style={h2Style}>“0.5% sounds tiny. Does it really matter?”</h2>
      <p style={pStyle(isMobile)}>
        It compounds — and that's brutal over a long horizon. Here's the same ₹10 lakh, left for 20 years, at 12%
        (Direct) versus 11% (Regular, ~1% higher fee):
      </p>
      <div className="nv-card" style={{ padding: isMobile ? "22px 20px" : "26px 28px", margin: "6px 0 18px" }}>
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
          A ~1% higher fee ≈ <b style={{ color: "var(--danger-hex)" }}>₹16 lakh</b> less at the finish. Illustrative (₹10L, 20 years, 12% vs 11%).
        </div>
      </div>

      <h2 className="nv-serif" style={h2Style}>“But I like having an advisor”</h2>
      <p style={pStyle(isMobile)}>
        Fair — and you can have both. The alternative to a commission-paid distributor is a <b>fee-only,
        SEBI-registered adviser</b> you pay directly: you still buy Direct plans, and the advice is aligned with
        you rather than with whichever fund pays the fattest trail. You're not choosing between "advice" and
        "cheap" — you're choosing who the advice actually serves.
      </p>

      <h2 className="nv-serif" style={h2Style}>How to move to Direct</h2>
      <ul style={ulStyle(isMobile)}>
        <li><b>New money:</b> just start Direct — pick the "Direct — Growth" plan when you invest.</li>
        <li><b>Existing Regular holdings:</b> switching is technically a redemption + fresh purchase, so mind capital-gains tax and any exit load. Often it's cleanest to point <em>new</em> SIPs to Direct and move old units when the tax impact is small.</li>
      </ul>

      <AskNivesh navigate={navigate} isMobile={isMobile} line="Ask Nivesh Copilot to flag which of your funds are Regular plans and the exact rupee drag versus their Direct twins." />
      <Disclaimer />
    </div>
  );
}
