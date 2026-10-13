/**
 * Portfolio screens — small pieces shared by Analysis, Recommend, Plan and
 * Ledger. Mostly layout; NoPlan is the one piece that reads data itself.
 */
import type { ReactNode } from "react";
import { useHoldingsEnriched } from "@/hooks/use-portfolio";
import { useRefreshPlan } from "@/hooks/use-recommendations";
import { Btn, EmptyBlock, ErrorBlock, LoadingBlock, fmtPct } from "../../components/ui";
import { useCopilotShell } from "../../lib/shell-context";
import { loadError } from "./data";

/** Screen header on the left, the "ask the Copilot" pill on the right. */
export function HeaderRow({ askLabel, onAsk, children }: { askLabel: string; onAsk: () => void; children: ReactNode }) {
  return (
    <div className="flex flex-wrap items-end justify-between" style={{ gap: 14 }}>
      <div className="min-w-0" style={{ flex: "1 1 320px" }}>{children}</div>
      <button type="button" className="cp-chip" style={{ borderColor: "var(--mint-line)", color: "var(--mint)" }} onClick={onAsk}>
        {askLabel}
      </button>
    </div>
  );
}

/** The mint "Nivesh read" card: one sentence, then short supporting lines. */
export function NiveshRead({ title, bullets = [], testId }: { title: ReactNode; bullets?: string[]; testId?: string }) {
  const { mobile } = useCopilotShell();
  return (
    <div data-testid={testId} className="flex" style={{ gap: 14, padding: mobile ? "16px" : "18px 20px", borderRadius: 14, border: "1px solid var(--mint-line)", background: "var(--mint-soft)" }}>
      <span className="nv-mark" style={{ flex: "none" }} aria-hidden="true">न</span>
      <div className="flex min-w-0 flex-col" style={{ gap: 8 }}>
        <span className="cp-eyebrow" style={{ color: "var(--mint)" }}>Nivesh read</span>
        <span className="cp-pretty" style={{ fontFamily: "var(--display)", fontSize: mobile ? 20 : 23, lineHeight: 1.25, overflowWrap: "anywhere" }}>{title}</span>
        {bullets.map((b) => (
          <span key={b} style={{ fontSize: 13, lineHeight: 1.5, color: "var(--cp-ink-2)" }}>· {b}</span>
        ))}
      </div>
    </div>
  );
}

/** Empty state for an account with no holdings: one way forward. */
export function NoPortfolio({ body }: { body: string }) {
  const { go } = useCopilotShell();
  return (
    <div data-testid="no-portfolio">
      <EmptyBlock
        title="No portfolio yet"
        body={body}
        action={<Btn variant="primary" onClick={() => go("onboarding")}>Import your portfolio</Btn>}
      />
    </div>
  );
}

/** The plan engine will not propose steps until the account has a risk profile. */
export function NeedsRiskProfile() {
  const { go } = useCopilotShell();
  return (
    <div data-testid="needs-risk-profile">
      <EmptyBlock
        title="Set up your risk profile first"
        body="Personalised steps need a risk profile. It takes about two minutes."
        action={<Btn variant="primary" onClick={() => go("page/settings")}>Set up risk profile</Btn>}
      />
    </div>
  );
}

/**
 * Shown when the account has no active plan. Tells an empty portfolio apart
 * from "holdings, but no plan built yet"; the second can build one.
 *
 * Building uses POST /api/plans/refresh (useRefreshPlan): it generates a plan
 * and saves it as the active one in a single call.
 */
export function NoPlan({ body }: { body: string }) {
  const enriched = useHoldingsEnriched();
  const build = useRefreshPlan();
  const why = loadError(build.error);
  const whyText = typeof why === "string" ? why : why instanceof Error ? why.message : "";
  if (enriched.isPending) return <LoadingBlock label="Checking your portfolio" rows={2} />;
  if (enriched.isError) return <ErrorBlock title="Your portfolio didn’t load" error={loadError(enriched.error)} onRetry={() => enriched.refetch()} />;
  if (enriched.data.holdings.length === 0) {
    return <NoPortfolio body="Import a statement or connect a broker and Nivesh will work out what is worth doing." />;
  }
  return (
    <div data-testid="no-plan">
      <EmptyBlock
        title="No plan yet"
        body={body}
        action={
          <div className="flex flex-col items-start" style={{ gap: 8 }}>
            <Btn variant="primary" disabled={build.isPending} onClick={() => build.mutate()}>
              {build.isPending ? "Building your plan…" : "Build my plan"}
            </Btn>
            {build.isError && (
              <span role="alert" style={{ fontSize: 12, color: "var(--cp-danger)" }}>
                The plan could not be built{whyText ? ` — ${whyText}` : ""}. Try again.
              </span>
            )}
          </div>
        }
      />
    </div>
  );
}

/** A percentage with a thin bar under it, scaled against `max`. For table cells. */
export function WeightCell({ pct, max }: { pct: number | null; max: number }) {
  return (
    <span style={{ display: "block" }}>
      {fmtPct(pct)}
      {pct != null && max > 0 && (
        <span aria-hidden="true" style={{ display: "block", height: 4, marginTop: 4, borderRadius: 2, background: "var(--bg-3)" }}>
          <span style={{ display: "block", height: "100%", width: `${Math.min(100, Math.max(0, (pct / max) * 100))}%`, borderRadius: 2, background: "var(--cp-indigo)" }} />
        </span>
      )}
    </span>
  );
}

export interface TabItem<T extends string> {
  id: T;
  label: string;
}

/** Underlined tab strip; scrolls sideways on a phone. */
export function Tabs<T extends string>({ tabs, value, onChange, label, idPrefix }: {
  tabs: Array<TabItem<T>>;
  value: T;
  onChange: (id: T) => void;
  label: string;
  /** Tab ids are `${idPrefix}-tab-${id}`; the panel should be `${idPrefix}-panel`. */
  idPrefix: string;
}) {
  return (
    <div role="tablist" aria-label={label} className="cp-scroll flex overflow-x-auto" style={{ gap: 24, borderBottom: "1px solid var(--cp-line)" }}>
      {tabs.map((t) => {
        const on = t.id === value;
        return (
          <button
            key={t.id}
            type="button"
            role="tab"
            id={`${idPrefix}-tab-${t.id}`}
            data-testid={`${idPrefix}-tab-${t.id}`}
            aria-selected={on}
            aria-controls={`${idPrefix}-panel`}
            onClick={() => onChange(t.id)}
            style={{ padding: "10px 0 12px", fontSize: 14, whiteSpace: "nowrap", background: "none", border: 0, borderBottom: `2px solid ${on ? "var(--cp-ink)" : "transparent"}`, color: on ? "var(--cp-ink)" : "var(--cp-ink-3)", cursor: "pointer", fontFamily: "var(--sans)" }}
          >
            {t.label}
          </button>
        );
      })}
    </div>
  );
}

/** "Show all 47" / "Show fewer" under a list that starts shortened. */
export function ShowAll({ total, limit, expanded, onToggle, noun }: { total: number; limit: number; expanded: boolean; onToggle: () => void; noun: string }) {
  if (total <= limit) return null;
  return (
    <div style={{ padding: "10px 16px" }}>
      <button type="button" aria-expanded={expanded} onClick={onToggle} style={{ fontSize: 13, color: "var(--cp-ink-2)", background: "none", border: 0, padding: 0, cursor: "pointer" }}>
        {expanded ? `Show the first ${limit}` : `Show all ${total} ${noun}`} ›
      </button>
    </div>
  );
}
