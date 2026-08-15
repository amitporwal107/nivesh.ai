/**
 * Webinar — public landing + registration page for the "How Nivesh Copilot was
 * built with Claude" session. Public marketing surface, no auth, no backend.
 *
 * Registration is handled by an external provider (calendar invite, join link and
 * reminder emails are what actually fight the no-show rate — a self-hosted form
 * gives none of those). Set REGISTRATION_URL below and the CTA becomes a real
 * button; until then the page says so plainly and offers a mailto channel.
 *
 * That degradation is deliberate and mirrors the Contact page, which uses mailto
 * rather than a form it has no endpoint to submit: nothing here pretends to do
 * something it can't. Both states are covered by e2e/tests/webinar-unauth.spec.ts.
 */
import MarketingShell from "@/components/marketing/MarketingShell";
import { useIsMobile } from "@/hooks/use-is-mobile";

// ─── configure these two, then redeploy ──────────────────────────────────────
/** External registration URL (Zoom / Luma / Google Form). Empty → "opening shortly". */
const REGISTRATION_URL = "https://us05web.zoom.us/j/84646655700?pwd=kliwwXoazg6cblOtqKJQSHUQa2Xl2m.1";
/** Human-readable date + time. Empty → "Date to be announced". */
const WEBINAR_DATE = "Monday 17 August 2026 · 8:00 PM IST";
// ─────────────────────────────────────────────────────────────────────────────

const CONTACT_EMAIL = "support@niveshcopilot.com";

const AGENDA = [
  {
    mins: "3 min",
    t: "Cold open — no slides",
    d: "A real research question, answered live from exchange filings, before a word of introduction.",
  },
  {
    mins: "10 min",
    t: "Demo 1 — the product",
    d: "A portfolio question that returns widgets instead of prose, a filings-grounded answer, and a statement PDF becoming a live portfolio. Every claim clicks through to its source document.",
  },
  {
    mins: "8 min",
    t: "What the system actually is",
    d: "Two independently deployable systems, an intent router feeding ten specialist nodes, and a compliance node every answer passes before it reaches a user.",
  },
  {
    mins: "14 min",
    t: "Demo 2 — building a feature live",
    d: "Spec, code, test and gate, on the real repository, on stage. Six role agents with their own definitions of done, handing work to each other through a directory.",
  },
  {
    mins: "8 min",
    t: "Demo 3 — the guardrail that says no",
    d: "Watch the agent try to finish without testing, and get refused by a hook that will not let the turn end. This is the part nobody else demonstrates.",
  },
  {
    mins: "12 min",
    t: "What it got wrong, then your questions",
    d: "Real failures with real consequences — a confident wrong answer and a config default that broke production twice — and an open Q&A.",
  },
];

const AUDIENCE = [
  { t: "Engineers and founders", d: "who suspect AI-assisted development falls apart past a weekend prototype, and want to see whether it does." },
  { t: "Technical leaders", d: "deciding how much autonomy to hand an agent, and where that autonomy has to stop." },
  { t: "Fintech and wealth-tech teams", d: "working with Indian market data, filings, and the compliance surface around advice." },
];

export default function WebinarPage() {
  const isMobile = useIsMobile();
  const pad = isMobile ? "0 20px" : "0 56px";
  const dateLabel = WEBINAR_DATE || "Date to be announced";

  return (
    <MarketingShell>
      {/* hero */}
      <div
        data-testid="webinar-hero"
        style={{ maxWidth: 900, margin: "0 auto", padding: isMobile ? "48px 20px 24px" : "80px 56px 32px", textAlign: "center" as const }}
      >
        <div className="nv-mono" style={{ fontSize: 11, letterSpacing: ".16em", color: "var(--mint)", textTransform: "uppercase" as const }}>
          Live webinar · 60 minutes
        </div>
        <h1
          className="nv-serif"
          style={{ fontSize: isMobile ? 36 : 60, lineHeight: 1.03, letterSpacing: "-0.035em", margin: "14px 0 0" }}
        >
          I built a production fintech platform with Claude<span style={{ color: "var(--mint)" }}>.</span>
        </h1>
        <p style={{ fontSize: isMobile ? 17 : 19, lineHeight: 1.6, color: "var(--ink-2)", margin: "24px auto 0", maxWidth: 620 }}>
          Not a slide deck about AI coding. Three live demos on the real repository behind
          Nivesh Copilot — including the guardrail that stops the agent from claiming it's
          done when it isn't.
        </p>
        <div className="nv-mono" style={{ fontSize: 13, color: "var(--ink-2)", marginTop: 22 }}>
          {dateLabel}
        </div>
      </div>

      {/* registration CTA */}
      <div style={{ maxWidth: 900, margin: "0 auto", padding: isMobile ? "8px 20px 16px" : "8px 56px 24px" }}>
        <div data-testid="webinar-cta" className="nv-card-2" style={{ padding: isMobile ? "26px 22px" : "34px 40px", textAlign: "center" as const }}>
          {REGISTRATION_URL ? (
            <>
              <div className="nv-serif" style={{ fontSize: isMobile ? 22 : 26, letterSpacing: "-0.02em" }}>
                Join the webinar
              </div>
              <p style={{ fontSize: 15, color: "var(--ink-2)", lineHeight: 1.6, margin: "10px auto 20px", maxWidth: 460 }}>
                Free to attend, and there's no registration step — the button opens Zoom
                directly at 8:00 PM. Add it to your own calendar now so it doesn't slip.
              </p>
              <a
                data-testid="webinar-cta-link"
                href={REGISTRATION_URL}
                target="_blank"
                rel="noopener noreferrer"
                className="nv-btn nv-btn-primary"
                style={{ display: "inline-block", padding: "13px 30px", fontSize: 15, textDecoration: "none" }}
              >
                Join on Zoom ›
              </a>
            </>
          ) : (
            <>
              <div className="nv-serif" style={{ fontSize: isMobile ? 22 : 26, letterSpacing: "-0.02em" }}>
                Registration opens shortly
              </div>
              <p
                data-testid="webinar-cta-pending"
                style={{ fontSize: 15, color: "var(--ink-2)", lineHeight: 1.6, margin: "10px auto 20px", maxWidth: 500 }}
              >
                The date and booking link aren't set yet, so there's nothing here that would
                pretend to take your registration. Email us and we'll send the invite the
                moment it's live — you'll be first on the list.
              </p>
              <a
                href={`mailto:${CONTACT_EMAIL}?subject=${encodeURIComponent("Webinar — notify me")}`}
                className="nv-mono"
                style={{ fontSize: 14, color: "var(--mint)", textDecoration: "none" }}
              >
                {CONTACT_EMAIL} ›
              </a>
            </>
          )}
        </div>
      </div>

      {/* agenda */}
      <div style={{ maxWidth: 1000, margin: "0 auto", padding: isMobile ? "24px 20px" : "40px 56px" }}>
        <div className="nv-mono" style={{ fontSize: 11, letterSpacing: ".16em", color: "var(--mint)", textTransform: "uppercase" as const, marginBottom: 18 }}>
          Run of show
        </div>
        <div data-testid="webinar-agenda" style={{ display: "grid", gap: 12 }}>
          {AGENDA.map((a) => (
            <div
              key={a.t}
              data-testid="agenda-item"
              className="nv-card"
              style={{
                padding: isMobile ? "18px 20px" : "22px 26px",
                display: "grid",
                gridTemplateColumns: isMobile ? "1fr" : "88px 1fr",
                gap: isMobile ? 8 : 22,
                alignItems: "start",
              }}
            >
              <span className="nv-mono" style={{ fontSize: 12, color: "var(--ink-2)", whiteSpace: "nowrap" as const }}>
                {a.mins}
              </span>
              <div>
                <div className="nv-serif" style={{ fontSize: isMobile ? 19 : 21, letterSpacing: "-0.02em" }}>{a.t}</div>
                <p style={{ fontSize: 14, color: "var(--ink-2)", lineHeight: 1.6, margin: "8px 0 0" }}>{a.d}</p>
              </div>
            </div>
          ))}
        </div>
      </div>

      {/* who it's for */}
      <div style={{ maxWidth: 1000, margin: "0 auto", padding: isMobile ? "16px 20px 40px" : "24px 56px 64px" }}>
        <div className="nv-mono" style={{ fontSize: 11, letterSpacing: ".16em", color: "var(--mint)", textTransform: "uppercase" as const, marginBottom: 18 }}>
          Who it's for
        </div>
        <div style={{ display: "grid", gridTemplateColumns: isMobile ? "1fr" : "repeat(3, 1fr)", gap: 16 }}>
          {AUDIENCE.map((a) => (
            <div key={a.t} className="nv-card" style={{ padding: isMobile ? "20px 22px" : 26 }}>
              <div className="nv-serif" style={{ fontSize: 20, letterSpacing: "-0.02em" }}>{a.t}</div>
              <p style={{ fontSize: 14, color: "var(--ink-2)", lineHeight: 1.6, margin: "10px 0 0" }}>{a.d}</p>
            </div>
          ))}
        </div>

        <p style={{ fontSize: 14, color: "var(--ink-2)", lineHeight: 1.7, margin: isMobile ? "28px 0 0" : "36px auto 0", maxWidth: 640, textAlign: "center" as const, padding: pad }}>
          Everything demonstrated runs against a staging environment with a seeded demo
          account. No customer data appears on screen at any point.
        </p>
      </div>
    </MarketingShell>
  );
}
