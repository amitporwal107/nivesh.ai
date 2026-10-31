/** `kpis`: a strip of figures (label, value, an optional line under it), each in its tone. */
import type { KpisBlock } from "../schema";
import { toneColor } from "../format";
import type { BlockProps } from "./common";

const ARROW: Record<string, string> = { up: "▲", down: "▼", warn: "!" };

export function KpisView({ b, compact }: BlockProps<KpisBlock>) {
  return (
    <ul data-testid="va-kpis" className="m-0 grid list-none p-0" style={{ gridTemplateColumns: `repeat(auto-fill, minmax(${compact ? 112 : 132}px, 1fr))`, gap: 8 }}>
      {b.items.map((it, i) => {
        const missing = it.value == null || it.value === "";
        const value = missing ? "—" : typeof it.value === "number" ? new Intl.NumberFormat("en-IN", { maximumFractionDigits: 2 }).format(it.value) : it.value;
        return (
          <li key={`${it.label}-${i}`} data-testid="va-kpi" data-tone={it.tone ?? "neutral"} className="flex min-w-0 flex-col"
            style={{ gap: 3, padding: compact ? "8px 10px" : "10px 12px", borderRadius: 10, border: "1px solid var(--cp-line)", background: "var(--bg-2)" }}>
            <span data-testid="va-kpi-label" style={{ fontSize: 11.5, lineHeight: 1.3, color: "var(--cp-ink-3)", overflowWrap: "anywhere" }}>{it.label}</span>
            <span className="cp-num" style={{ fontSize: compact ? 15 : 17, lineHeight: 1.2, color: missing ? "var(--cp-ink-3)" : toneColor(it.tone), overflowWrap: "anywhere" }}>
              {it.tone && ARROW[it.tone] && !missing && <span aria-hidden style={{ fontSize: "0.65em", marginRight: 4, verticalAlign: "0.15em" }}>{ARROW[it.tone]}</span>}
              <span data-testid="va-kpi-value">{value}</span>
              {missing && <span className="sr-only"> not available</span>}
            </span>
            {it.sub && <span data-testid="va-kpi-sub" style={{ fontSize: 11, lineHeight: 1.35, color: "var(--cp-ink-3)", overflowWrap: "anywhere" }}>{it.sub}</span>}
          </li>
        );
      })}
    </ul>
  );
}
