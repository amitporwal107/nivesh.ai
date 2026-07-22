/**
 * Terms — public legal page (plain-language template).
 */
import LegalDoc from "@/components/marketing/LegalDoc";

export default function TermsPage() {
  return (
    <LegalDoc
      kicker="Legal"
      title="Terms of Service"
      effective="July 2026"
      intro="These terms cover your use of Nivesh. In short: we give you analysis and tools to understand your portfolio; the decisions, and the trades, remain yours."
      sections={[
        {
          h: "The service",
          body: "Nivesh reconciles the portfolio you connect, scores its health, and surfaces suggested actions. We provide analysis and simulations — we do not execute trades or hold your assets.",
        },
        {
          h: "Not investment advice",
          body: "Nivesh's output is information and analysis, not personalised investment advice unless explicitly provided under a SEBI-registered advisory engagement. You are responsible for your own investment decisions. See our Disclosure for details.",
        },
        {
          h: "Your account",
          body: "Keep your login secure and use connected accounts (Google, broker) that you are authorised to use. You are responsible for activity under your account.",
        },
        {
          h: "Acceptable use",
          body: "Don't misuse the service — no attempting to break, overload, reverse-engineer, or access data that isn't yours. We may suspend accounts that do.",
        },
        {
          h: "Data & privacy",
          body: (
            <>How we handle your data — including Google user data accessed via Gmail — is described in our{" "}
              <a href="/privacy" style={{ color: "var(--mint)" }}>Privacy Policy</a>. Our use and transfer of
              information received from Google APIs adheres to the Google API Services User Data Policy,
              including its Limited Use requirements. Sensitive data is encrypted in transit and at rest, and
              you can revoke any connected account or delete your data at any time.</>
          ),
        },
        {
          h: "Availability & changes",
          body: "We work to keep Nivesh available and accurate, but we provide it 'as is' without warranty of uninterrupted or error-free operation. We may update features and these terms; we'll flag material changes.",
        },
        {
          h: "Liability",
          body: "To the extent permitted by law, Nivesh is not liable for investment losses or for indirect or consequential damages arising from use of the service. Markets carry risk; past performance does not guarantee future results.",
        },
        {
          h: "Contact",
          body: (
            <>Questions about these terms? Write to <a href="mailto:support@niveshcopilot.com" style={{ color: "var(--mint)" }}>support@niveshcopilot.com</a>.</>
          ),
        },
      ]}
    />
  );
}
