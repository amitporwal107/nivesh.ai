/**
 * Strategy Builder — the thesis and the evidence ledger (PRD §16.3, §16.5).
 *
 * The thesis lists only the evidence that applies to the chosen direction. The ledger is every item the plan
 * weighed, grouped under the seven groups of §16.3, each group collapsed to its counts until opened
 * (aria-expanded). An item shows its direction as a word AND a shape (supports ▲, conflicts ▼, neutral ●,
 * unavailable ∅), its value as the route sent it, its interpretation, and its source with the source's own
 * as-of date. An unavailable item says why. Nothing is scored or re-weighed here.
 */
import { useId, useState } from "react";
import { fmtDay } from "../../trading/parts";
import type { DeskPersona } from "../context";
import { TrustLine } from "../trust";
import { GROUPS, GROUP_TITLE, type EvidenceItem, type StrategyPlan } from "./plan-contract";
import { DASH, noteStyle, valueText } from "./plan-format";
import { Section } from "../../../components/ui";

const DIRECTION_SHAPE: Record<EvidenceItem["direction"], { word: string; glyph: string; color: string }> = {
  supports: { word: "Supports", glyph: "▲", color: "var(--mint)" },
  conflicts: { word: "Conflicts", glyph: "▼", color: "var(--cp-danger)" },
  neutral: { word: "Neutral", glyph: "●", color: "var(--cp-ink-3)" },
  unavailable: { word: "Unavailable", glyph: "∅", color: "var(--amber)" },
};

export function Thesis({ plan, persona }: { plan: StrategyPlan; persona: DeskPersona }) {
  const plain = persona === "investor";
  const t = plan.thesis;
  const list = (rows: Array<{ group: string; key: string; interpretation: string }>, empty: string, testId: string) => (
    rows.length ? (
      <ul data-testid={testId} className="m-0 flex flex-col" style={{ gap: 4, paddingLeft: 18 }}>
        {rows.map((r) => <li key={`${r.group}.${r.key}`} style={{ fontSize: 13, lineHeight: 1.5 }}><span className="cp-num" style={{ fontSize: 11, color: "var(--cp-ink-3)" }}>{r.group}.{r.key}</span> {r.interpretation}</li>)}
      </ul>
    ) : <span data-testid={testId} style={noteStyle}>{empty}</span>
  );
  return (
    <Section title={plain ? "Why this view" : "Thesis"} note={`${t.supports.length} supporting · ${t.conflicts.length} conflicting · ${t.unavailable.length} unavailable`}>
      <div data-testid="thesis" className="flex min-w-0 flex-col" style={{ gap: 12 }}>
        <div className="flex flex-col" style={{ gap: 4 }}><span className="cp-eyebrow">▲ {plain ? "For" : "Supports"}</span>{list(t.supports, "Nothing on record supports this view.", "thesis-supports")}</div>
        <div className="flex flex-col" style={{ gap: 4 }}><span className="cp-eyebrow">▼ {plain ? "Against" : "Conflicts"}</span>{list(t.conflicts, "Nothing on record conflicts with this view.", "thesis-conflicts")}</div>
        {t.unavailable.length > 0 && (
          <div className="flex flex-col" style={{ gap: 4 }}>
            <span className="cp-eyebrow">∅ {plain ? "Could not be checked" : "Unavailable inputs"}</span>
            <span data-testid="thesis-unavailable" style={noteStyle}>{t.unavailable.join(", ")}. Each is listed in the ledger with its reason.</span>
          </div>
        )}
        {t.note && <span style={noteStyle}>{t.note}</span>}
      </div>
    </Section>
  );
}

function ItemRow({ it }: { it: EvidenceItem }) {
  const d = DIRECTION_SHAPE[it.direction];
  return (
    <li data-testid={`ev-${it.group}-${it.key}`} data-direction={it.direction} className="flex min-w-0 flex-col" style={{ gap: 3, padding: "10px 0", borderTop: "1px solid var(--cp-line)" }}>
      <span className="flex flex-wrap items-baseline" style={{ gap: "2px 10px" }}>
        <span data-testid="ev-direction" style={{ color: d.color, fontSize: 12, fontWeight: 500, whiteSpace: "nowrap" }}><span aria-hidden>{d.glyph} </span>{d.word}</span>
        <span className="cp-num" style={{ fontSize: 12, color: "var(--cp-ink-2)" }}>{it.key.replace(/_/g, " ")}</span>
        {it.direction !== "unavailable" && <span data-testid="ev-value" className="cp-num" style={{ fontSize: 12.5, overflowWrap: "anywhere" }}>{valueText(it.value)}</span>}
      </span>
      <span data-testid="ev-interpretation" style={{ fontSize: 12.5, lineHeight: 1.5, color: "var(--cp-ink-2)" }}>{it.direction === "unavailable" ? `Why not: ${it.interpretation}` : it.interpretation}</span>
      <span data-testid="ev-source" className="cp-mono-note" style={{ overflowWrap: "anywhere" }}>
        {it.source && it.source !== "none" ? it.source : "No source"} · {it.source_as_of ? `as of ${fmtDay(it.source_as_of)}` : "no date"}{it.version ? ` · ${it.version}` : ""}
      </span>
    </li>
  );
}

function Group({ group, items, counts, persona, open, onToggle }: {
  group: string; items: EvidenceItem[]; counts: Record<string, number | undefined>; persona: DeskPersona; open: boolean; onToggle: () => void;
}) {
  const panel = useId();
  const title = GROUP_TITLE[group] ?? { trader: group, plain: group };
  return (
    <li data-testid={`ev-group-${group}`} style={{ borderTop: "1px solid var(--cp-line)" }}>
      <button
        type="button" aria-expanded={open} aria-controls={panel} data-testid={`ev-group-${group}-toggle`} onClick={onToggle}
        className="flex w-full items-baseline justify-between"
        style={{ gap: 12, padding: "12px 4px", border: 0, background: "none", cursor: "pointer", textAlign: "left", color: "inherit", fontFamily: "var(--sans)" }}
      >
        <span style={{ fontSize: 14, fontWeight: 500 }}>{persona === "investor" ? title.plain : title.trader}</span>
        <span data-testid={`ev-group-${group}-counts`} className="cp-mono-note" style={{ textAlign: "right" }}>
          ▲ {counts.supports ?? 0} · ▼ {counts.conflicts ?? 0} · ● {counts.neutral ?? 0} · ∅ {counts.unavailable ?? 0} <span aria-hidden>{open ? "▴" : "▾"}</span>
        </span>
      </button>
      {open && (
        <ul id={panel} className="m-0 flex flex-col" style={{ padding: "0 4px 8px", listStyle: "none" }}>
          {items.length ? items.map((it) => <ItemRow key={`${it.group}.${it.key}`} it={it} />) : <li style={noteStyle}>No items in this group.</li>}
        </ul>
      )}
    </li>
  );
}

export function EvidenceLedger({ plan, persona }: { plan: StrategyPlan; persona: DeskPersona }) {
  const [open, setOpen] = useState<Set<string>>(() => new Set());
  const toggle = (g: string) => setOpen((s) => { const n = new Set(s); if (n.has(g)) n.delete(g); else n.add(g); return n; });
  const groups = [...GROUPS, ...[...new Set(plan.evidence.map((e) => e.group))].filter((g) => !(GROUPS as readonly string[]).includes(g))];
  const all = open.size === groups.length;
  return (
    <Section title={persona === "investor" ? "Everything checked" : "Evidence ledger"} note={`${plan.evidence.length} items · seven groups`}>
      <div data-testid="evidence-ledger" className="flex min-w-0 flex-col" style={{ gap: 8 }}>
        <div className="flex justify-end">
          <button type="button" data-testid="ev-toggle-all" className="cp-chip" onClick={() => setOpen(all ? new Set() : new Set(groups))}>{all ? "Collapse all" : "Expand all"}</button>
        </div>
        <ul className="m-0" style={{ padding: 0, listStyle: "none" }}>
          {groups.map((g) => (
            <Group key={g} group={g} items={plan.evidence.filter((e) => e.group === g)} counts={plan.evidence_summary[g] ?? {}} persona={persona} open={open.has(g)} onToggle={() => toggle(g)} />
          ))}
        </ul>
        <TrustLine testId="ledger-trust" source="The sources named on each item" mode="eod" asOf={plan.data_as_of.price ? fmtDay(plan.data_as_of.price) : DASH} maker="rules" method={plan.rules_version} />
      </div>
    </Section>
  );
}
