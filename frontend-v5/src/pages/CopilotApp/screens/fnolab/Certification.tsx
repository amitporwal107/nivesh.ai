/**
 * F&O lab · 11 Agent Certification Center (?screen=cert). Design: the "Agent Certification Center" screen of
 * Nivesh F&O Desk, today state.
 *
 * Not built: certification records need the certification service (PRD v2.1 P3.1). No route serves agent, strategy or
 * adapter certifications, so the screen shows none and lists the PRD §14.6 status ladder. backend/nidp/shared/
 * certification.py certifies data-lake DATES into nidp.certified_dates; that is not agent certification.
 */
import { Section } from "../../components/ui";
import { GapNote, SourceCards, type SourceItem } from "./parts";

const SOURCES: SourceItem[] = [
  { k: "Certification service", sub: "Not built · P3.1", tone: "danger" },
  { k: "Data-lake certification", sub: "Dates only · not agent", tone: "amber" },
  { k: "Fault-injection suite", sub: "Not built · P3.1", tone: "danger" },
  { k: "Preregistration", sub: "F&O studies B2, B3 · no agent scope", tone: "amber" },
];

const LADDER: Array<{ k: string; v: string }> = [
  { k: "NOT_CERTIFIED", v: "Every agent, strategy and broker context today" },
  { k: "RESEARCH_CERTIFIED", v: "Gate B evidence: walk-forward, leakage tests, baselines" },
  { k: "PAPER_CERTIFIED", v: "Conservative paper fills, preregistered sample met" },
  { k: "SHADOW_CERTIFIED", v: "Decisions on live data, no orders" },
  { k: "RESTRICTED_LIVE_CERTIFIED", v: "Gate D plus two human approvals" },
  { k: "SUSPENDED", v: "Automatic (version, data or policy change) or manual" },
  { k: "RETIRED", v: "Kept read-only for audit" },
];

export function Certification() {
  return (
    <div className="flex flex-col" style={{ gap: 14 }}>
      <SourceCards items={SOURCES} />
      <div className="flex flex-wrap" style={{ gap: 12, alignItems: "flex-start" }}>
        <div className="flex flex-col" style={{ flex: "1.3 1 380px", minWidth: 0, gap: 12 }}>
          <div data-testid="fnolab-cert-empty" className="cp-card flex flex-col" style={{ gap: 10, padding: "18px" }}>
            <span className="cp-eyebrow">Certification records</span>
            <span style={{ fontFamily: "var(--display)", fontSize: 28, lineHeight: 1.1 }}>
              No agent, strategy or broker context is <span style={{ color: "var(--amber)" }}>certified</span> yet.
            </span>
            <span style={{ fontSize: 13.5, lineHeight: 1.55, color: "var(--cp-ink-2)" }}>
              Everything is NOT_CERTIFIED. A record appears here only when the certification service exists and evidence is filed for one exact scope: agent version, strategy, universe, broker adapter and risk policy.
            </span>
            <span data-testid="fnolab-cert-datalake" style={{ padding: "10px 12px", borderRadius: 10, border: "1px solid var(--amber-line)", background: "var(--amber-soft)", fontSize: 13, lineHeight: 1.45, color: "var(--amber)" }}>
              The existing certification module (nidp/shared/certification.py) certifies data-lake dates only. It is not agent certification, so it does not appear here.
            </span>
          </div>
          <GapNote tag="P3.1" title="No certification service" testId="fnolab-cert-gap">
            Scoped records, the ten certification domains, the fault-injection tests and the promotion path from research to restricted live all need the certification service and its evidence store.
          </GapNote>
        </div>
        <div style={{ flex: "1 1 300px", minWidth: 0 }}>
          <Section title="Status ladder · PRD §14.6" flush>
            <div data-testid="fnolab-cert-ladder" className="flex flex-col">
              {LADDER.map((l, i) => (
                <div key={l.k} data-testid="fnolab-cert-status" className="grid" style={{ gridTemplateColumns: "minmax(0,1.3fr) minmax(0,1fr)", gap: 12, padding: "10px 16px", borderBottom: "1px solid var(--cp-line)" }}>
                  <span style={{ fontFamily: "var(--mono)", fontSize: 11, color: i === 0 ? "var(--amber)" : "var(--cp-ink-3)", overflowWrap: "anywhere" }}>{l.k}</span>
                  <span style={{ fontSize: 12.5, color: "var(--cp-ink-3)" }}>{l.v}</span>
                </div>
              ))}
            </div>
          </Section>
        </div>
      </div>
    </div>
  );
}
