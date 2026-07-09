/**
 * TaxHarvestingArticle — conversational guide to tax-gain/loss harvesting in
 * equity mutual funds. Tax figures reflect the FY25 regime (Budget 2024) and are
 * flagged as "confirm current rules". Worked example is illustrative.
 */
import { useNavigate } from "react-router-dom";
import { useIsMobile } from "@/hooks/use-is-mobile";
import ChatTeaser from "./ChatTeaser";
import { AskNivesh, Disclaimer, h2Style, pStyle, ulStyle } from "./TypesOfFundsArticle";

export default function TaxHarvestingArticle() {
  const navigate = useNavigate();
  const isMobile = useIsMobile();
  return (
    <div style={{ padding: isMobile ? "0 4px" : "0" }}>
      <ChatTeaser
        q="Is there a legal way to pay less tax on my equity funds?"
        a="Yes — it's called tax harvesting. Every year you're allowed ₹1.25 lakh of long-term equity gains tax-free. If you never use it, you lose it. Booking gains up to that limit each year quietly resets your tax bill. Here's how."
      />

      <h2 className="nv-serif" style={h2Style}>What is tax harvesting?</h2>
      <p style={pStyle(isMobile)}>
        It's deliberately <b>selling and rebuying</b> to use up a tax allowance you'd otherwise waste. For equity
        mutual funds held over a year, long-term capital gains up to <b>₹1.25 lakh in a financial year are
        tax-free</b>; gains above that are taxed at 12.5%. Harvesting means realising gains up to that ₹1.25 lakh
        each year — paying ₹0 tax — and immediately reinvesting, which <b>raises your cost basis</b> so there's
        less taxable gain later.
      </p>

      <h2 className="nv-serif" style={h2Style}>A quick worked example</h2>
      <div className="nv-card" style={{ padding: isMobile ? "18px 18px" : "20px 24px", margin: "6px 0 18px" }}>
        <ul style={{ ...ulStyle(isMobile), margin: 0 }}>
          <li>You have ₹1.25 lakh of long-term gains sitting in a fund this year.</li>
          <li>You sell that much, pay <b>₹0 tax</b> (within the exemption), and buy the fund straight back.</li>
          <li>Your cost basis is now higher by ₹1.25 lakh — so a future sale has ₹1.25 lakh <em>less</em> taxable gain.</li>
          <li>Repeat annually and you steadily move money to a higher basis, tax-free along the way.</li>
        </ul>
        <div className="nv-mono" style={{ fontSize: 11, color: "var(--ink-3)", marginTop: 12, letterSpacing: ".03em" }}>Illustrative — your numbers, exit loads and holding periods will differ.</div>
      </div>

      <h2 className="nv-serif" style={h2Style}>The flip side: loss harvesting</h2>
      <p style={pStyle(isMobile)}>
        Sitting on a fund that's underwater? You can <b>book the loss</b> and set it off against other capital
        gains, trimming this year's tax — then redeploy into a better fund. A red holding can still do you a
        favour at tax time.
      </p>

      <h2 className="nv-serif" style={h2Style}>Before you get clever — the watch-outs</h2>
      <ul style={ulStyle(isMobile)}>
        <li><b>Exit loads &amp; short-term status:</b> selling within a year can trigger an exit load and 20% short-term tax — check the holding period first.</li>
        <li><b>Don't churn blindly:</b> the goal is the tax allowance, not constant trading. Do it once a year, near year-end.</li>
        <li><b>Rules change:</b> the ₹1.25 lakh limit and 12.5% rate are the current (post-Budget-2024) equity figures — confirm before acting.</li>
      </ul>

      <AskNivesh navigate={navigate} isMobile={isMobile} line="Ask Nivesh Copilot to scan your holdings for harvestable gains and losses before 31 March — it does the maths on your actual portfolio." />
      <Disclaimer />
    </div>
  );
}
