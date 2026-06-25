/**
 * LegalDoc — shared prose layout for the legal marketing pages
 * (Privacy, Terms, Disclosure). Renders a title, an effective-date line,
 * an editable template notice, and a list of titled sections.
 *
 * NOTE: the section copy passed in is a plain-language TEMPLATE, not legal
 * advice. Each legal page flags that it must be reviewed by counsel / compliance
 * before it is treated as binding.
 */
import { ReactNode } from "react";
import MarketingShell from "@/components/marketing/MarketingShell";

export type LegalSection = { h: string; body: ReactNode };

export default function LegalDoc({
  kicker,
  title,
  effective,
  intro,
  sections,
}: {
  kicker: string;
  title: string;
  effective: string;
  intro: string;
  sections: LegalSection[];
}) {
  return (
    <MarketingShell>
      <div style={{ maxWidth: 820, margin: "0 auto", padding: "72px 56px 24px" }}>
        <div className="nv-mono" style={{ fontSize: 11, letterSpacing: ".16em", color: "var(--mint)", textTransform: "uppercase" as const }}>{kicker}</div>
        <h1 className="nv-serif" style={{ fontSize: 56, lineHeight: 1.0, letterSpacing: "-0.035em", margin: "12px 0 0" }}>{title}</h1>
        <div className="nv-mono" style={{ fontSize: 12, color: "var(--ink-3)", marginTop: 16, letterSpacing: ".04em" }}>Effective {effective} · ARN-128459</div>
        <p style={{ fontSize: 18, lineHeight: 1.6, color: "var(--ink-2)", marginTop: 24 }}>{intro}</p>

        <div className="nv-card-2" style={{ padding: "14px 18px", marginTop: 24, display: "flex", gap: 10, alignItems: "flex-start" }}>
          <span style={{ color: "var(--amber)", fontSize: 14, lineHeight: 1.4 }}>⚠</span>
          <p className="nv-mono" style={{ fontSize: 11, color: "var(--ink-3)", lineHeight: 1.55, letterSpacing: ".02em" }}>
            Template — plain-language summary for review. Final wording must be approved by
            legal &amp; compliance before launch; this is not legal advice.
          </p>
        </div>

        <div style={{ marginTop: 8 }}>
          {sections.map((s, i) => (
            <div key={s.h} style={{ paddingTop: 36, borderTop: i === 0 ? "none" : "1px solid rgb(var(--line) / 0.06)", marginTop: i === 0 ? 24 : 0 }}>
              <h2 className="nv-serif" style={{ fontSize: 26, letterSpacing: "-0.02em", margin: "0 0 12px" }}>
                <span className="nv-mono" style={{ fontSize: 13, color: "var(--ink-4)", marginRight: 12 }}>{String(i + 1).padStart(2, "0")}</span>
                {s.h}
              </h2>
              <div style={{ fontSize: 15, lineHeight: 1.7, color: "var(--ink-2)" }}>{s.body}</div>
            </div>
          ))}
        </div>

        <div className="nv-mono" style={{ fontSize: 11, color: "var(--ink-4)", marginTop: 44, letterSpacing: ".04em" }}>
          Questions? <a href="mailto:support@niveshcopilot.com" style={{ color: "var(--mint)" }}>support@niveshcopilot.com</a>
        </div>
      </div>
    </MarketingShell>
  );
}
