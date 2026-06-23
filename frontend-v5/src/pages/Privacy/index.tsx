/**
 * Privacy — public legal page (plain-language template).
 * Grounded in how the product actually handles data: read-only access,
 * Gmail CAS parsing in memory, no warehousing of statements.
 */
import LegalDoc from "@/components/marketing/LegalDoc";

export default function PrivacyPage() {
  return (
    <LegalDoc
      kicker="Legal"
      title="Privacy Policy"
      effective="June 2026"
      intro="Nivesh is built read-only. We read your portfolio to analyse it — we never trade, move money, or sell your data. This page explains what we collect, why, and how you stay in control."
      sections={[
        {
          h: "What we collect",
          body: (
            <ul style={{ margin: 0, paddingLeft: 18 }}>
              <li>Account basics — your name and email, from Google sign-in.</li>
              <li>Portfolio data — holdings, transactions and statements you connect via Gmail CAS, an uploaded PDF, or a linked broker.</li>
              <li>Usage data — how you interact with the app, to improve it.</li>
            </ul>
          ),
        },
        {
          h: "How we use Gmail access",
          body: "When you connect Gmail, access is read-only and scoped to finding CAS statements. We do not send mail, and we do not read anything other than the statements needed to build your portfolio. You can revoke access at any time from your Google account.",
        },
        {
          h: "How statements are handled",
          body: "Statements are parsed to extract holdings and transactions, and encrypted in transit. We store the structured portfolio we derive so we can show you your analysis over time; we do not warehouse the raw statement files beyond what is needed to process them.",
        },
        {
          h: "Who we share with",
          body: "We do not sell your data. We share it only with the infrastructure providers needed to run the service (e.g. cloud hosting), under contract, and where the law requires it.",
        },
        {
          h: "Your rights",
          body: "You can access, export or delete your data, and revoke any connected account, at any time. Delete your account and we remove your personal data, subject to records we must keep by law.",
        },
        {
          h: "Contact",
          body: (
            <>Reach our team at <a href="mailto:support@nivesh.ai" style={{ color: "var(--mint)" }}>support@nivesh.ai</a> for any privacy request.</>
          ),
        },
      ]}
    />
  );
}
