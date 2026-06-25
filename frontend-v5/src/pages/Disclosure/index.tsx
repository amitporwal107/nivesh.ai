/**
 * Disclosure — public legal page (plain-language template).
 * Covers the SEBI / market-risk disclosure framing used across the app.
 */
import LegalDoc from "@/components/marketing/LegalDoc";

export default function DisclosurePage() {
  return (
    <LegalDoc
      kicker="Legal"
      title="Risk Disclosure"
      effective="June 2026"
      intro="Investing carries risk. This page sets out the disclosures you should read before acting on anything you see in Nivesh."
      sections={[
        {
          h: "Market risk",
          body: "Mutual funds and securities are subject to market risk. The value of your investments can go down as well as up, and you may get back less than you invested. Past performance is not indicative of future results.",
        },
        {
          h: "Nature of the analysis",
          body: "Nivesh's scores, grades and suggested actions are generated from your portfolio data and market information for your understanding. They are not a recommendation to buy or sell any specific security unless explicitly delivered under a SEBI-registered advisory engagement.",
        },
        {
          h: "Registration",
          body: "Nivesh operates under ARN-128459. Where investment advice is provided, it is provided in accordance with the applicable SEBI framework and the agreed Investment Policy Statement (IPS).",
        },
        {
          h: "Data accuracy",
          body: "Analysis depends on the accuracy of the statements and feeds you connect and of third-party market data. We reconcile carefully and flag gaps, but figures should be confirmed against your official statements before you act.",
        },
        {
          h: "No guaranteed outcomes",
          body: "Simulations and projections are illustrative. They do not guarantee any particular return, tax outcome, or result.",
        },
        {
          h: "Consult a professional",
          body: (
            <>For advice specific to your circumstances, consult a qualified, SEBI-registered adviser. Questions: <a href="mailto:support@niveshcopilot.com" style={{ color: "var(--mint)" }}>support@niveshcopilot.com</a>.</>
          ),
        },
      ]}
    />
  );
}
