/**
 * Top Movers v5 "Technical state" card: the 0-10 bullish technical score for the anchor session (the pinned event, else the
 * move day), which of the ten points passed, and all six indicator groups with every condition, its value and pass/fail.
 * Data: `analysis.tech_state` (anchored to the pinned event) with `detail.tech_state` as the move-day fallback.
 * A condition the feed cannot evaluate (`on` null) is drawn as informational and says why; it is never drawn as "not met".
 */
import type { CSSProperties } from "react";
import type { MoverTechState } from "@/services/adapters/movers.adapter";

const cv = (k: string) => `var(--${k})`;
const MON = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];
const fdy = (t: string) => { const d = new Date(`${t.slice(0, 10)}T00:00:00Z`); return `${String(d.getUTCDate()).padStart(2, "0")} ${MON[d.getUTCMonth()]} '${String(d.getUTCFullYear()).slice(2)}`; };
const bucketColor = (b?: string) => (b === "WEAK" ? "ink-3" : b === "MODERATE" ? "indigo" : b === "STRONG" ? "amber" : "mint");
const mono: CSSProperties = { fontFamily: "var(--mono)" };
const card: CSSProperties = { borderRadius: 14, background: "var(--bg-1)", border: "1px solid var(--line)", boxShadow: "var(--shadow-card)", padding: "18px 20px", display: "flex", flexDirection: "column", gap: 16 };

export function MoversTech({ state, eventLabel, pinned, deliveryCoverage }: {
  state: MoverTechState | null | undefined;
  eventLabel?: string | null;
  pinned: boolean;
  deliveryCoverage?: { sessions: number; total: number } | null;
}) {
  if (!state) return null;
  if (!state.available) {
    return (
      <section data-testid="mv-tech" style={card}>
        <span style={{ ...mono, fontSize: 11, letterSpacing: ".14em", color: "var(--ink-3)" }}>TECHNICAL STATE</span>
        <p role="status" data-testid="mv-tech-unavailable-card" style={{ margin: 0, ...mono, fontSize: 11, letterSpacing: ".08em", color: "var(--ink-3)" }}>
          {state.reason === "NEEDS_50_SESSIONS_OF_HISTORY"
            ? "NOT ENOUGH PRICE HISTORY BEFORE THIS SESSION: THE SCORE NEEDS 50 SESSIONS"
            : "TECHNICAL STATE UNAVAILABLE FOR THIS SESSION"}
        </p>
      </section>
    );
  }
  const score = state.score ?? 0, max = state.max ?? 10, c = bucketColor(state.bucket);
  const rt = !!state.round_trip, rtd = state.round_trip_detail;
  const unknown = (state.pts ?? []).filter((p) => p.on == null).length;
  return (
    <section data-testid="mv-tech" style={card}>
      <div style={{ display: "flex", alignItems: "center", gap: 10, flexWrap: "wrap" }}>
        <span style={{ ...mono, fontSize: 11, letterSpacing: ".14em", color: "var(--ink-3)" }}>
          {`TECHNICAL STATE · CLOSE OF ${state.anchor ? fdy(state.anchor).toUpperCase() : "—"}${eventLabel ? ` · ${eventLabel.toUpperCase()}` : ""}`}
        </span>
        <span data-testid="mv-tech-rt" style={{ padding: "2px 8px", borderRadius: 999, border: `1px solid ${rt ? cv("rose-line") : cv("line-2")}`, color: rt ? cv("rose") : cv("ink-3"), ...mono, fontSize: 10, letterSpacing: ".08em" }}>
          {rt && rtd ? `ROUND TRIP · ${rtd.cp.toUpperCase()} · ${rtd.days}D` : "NO ROUND TRIP IN PRIOR 5 SESSIONS"}
        </span>
        <span style={{ flex: 1 }} />
        <span style={{ ...mono, fontSize: 10, letterSpacing: ".1em", color: "var(--ink-4)" }}>{pinned ? "PINNED EVENT · CLICK AGAIN FOR T" : "MOVE DAY · PIN A MARKER TO CHANGE"}</span>
      </div>

      <div style={{ display: "flex", flexWrap: "wrap", gap: "16px 32px", alignItems: "flex-end" }}>
        <div style={{ display: "flex", flexDirection: "column", gap: 4 }}>
          <span data-testid="mv-tech-score" style={{ fontFamily: "var(--display)", fontSize: 56, lineHeight: 1, color: cv(c) }}>{score}<span style={{ fontSize: 24, color: "var(--ink-3)" }}>/{max}</span></span>
          <span style={{ ...mono, fontSize: 10.5, letterSpacing: ".12em", color: cv(c) }}>{`BULLISH TECHNICAL SCORE · ${state.bucket} · ${score} OF ${max} POINTS`}</span>
        </div>
        <span style={{ flex: "1 1 360px", fontFamily: "var(--display)", fontSize: 24, lineHeight: 1.25, textWrap: "pretty" }}>
          {`${rt ? "Round trip active" : "No round trip"}, ${(state.bucket ?? "").toLowerCase()} technical state: ${score} of ${max} conditions met.`}
          {unknown > 0 ? ` ${unknown} ${unknown === 1 ? "condition" : "conditions"} could not be evaluated and ${unknown === 1 ? "is" : "are"} not counted.` : ""}
        </span>
      </div>

      <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fill,minmax(170px,1fr))", gap: 6 }}>
        {(state.pts ?? []).map((p) => (
          <span key={p.k} data-testid="mv-tech-pt" data-on={String(p.on)} style={{
            display: "flex", alignItems: "center", gap: 8, padding: "6px 10px", borderRadius: 999, ...mono, fontSize: 10, letterSpacing: ".06em",
            border: `1px solid ${p.on ? cv("mint-line") : cv("line-2")}`, background: p.on ? cv("mint-soft") : "transparent", color: p.on ? cv("ink") : cv("ink-3") }}>
            <span style={{ width: 7, height: 7, borderRadius: "50%", flex: "none", background: p.on == null ? cv("indigo") : p.on ? cv("mint") : cv("ink-4") }} />{p.k}
          </span>
        ))}
      </div>

      <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit,minmax(min(100%,300px),1fr))", gap: 12 }}>
        {(state.families ?? []).map((f) => {
          const scored = f.rows.filter((r) => r.on != null), ps = scored.filter((r) => r.on).length, sh = ps / Math.max(1, scored.length);
          return (
            <div key={f.name} data-testid="mv-tech-family" style={{ border: "1px solid var(--line)", borderRadius: 12, padding: "12px 14px", background: "var(--bg-0)", display: "flex", flexDirection: "column" }}>
              <div style={{ display: "flex", alignItems: "center", gap: 8, paddingBottom: 8 }}>
                <span style={{ ...mono, fontSize: 10.5, letterSpacing: ".1em", color: "var(--ink)" }}>{f.name}</span>
                <span style={{ flex: 1 }} />
                <span style={{ ...mono, fontSize: 10, letterSpacing: ".08em", color: sh >= 0.6 ? cv("mint") : sh >= 0.34 ? cv("amber") : cv("ink-3") }}>{`${ps} / ${scored.length} PASS`}</span>
              </div>
              {f.rows.map((r) => (
                <div key={r.k} style={{ display: "grid", gridTemplateColumns: "8px minmax(0,1fr) auto", gap: 8, alignItems: "center", padding: "5px 0", borderTop: "1px solid var(--line)" }}>
                  <span style={{ width: 7, height: 7, borderRadius: "50%", background: r.on == null ? cv("indigo") : r.on ? cv("mint") : cv("ink-4") }} />
                  <span style={{ ...mono, fontSize: 10, letterSpacing: ".05em", color: r.on === false ? cv("ink-3") : cv("ink-2") }}>{r.k}</span>
                  <span style={{ ...mono, fontSize: 11.5, textAlign: "right", color: r.on == null ? cv("indigo") : r.on ? cv("ink") : cv("ink-3"), maxWidth: 190, whiteSpace: "normal" }}>{r.v}</span>
                </div>
              ))}
            </div>
          );
        })}
      </div>

      <div style={{ display: "flex", flexWrap: "wrap", gap: 14, ...mono, fontSize: 9.5, letterSpacing: ".08em", color: "var(--ink-3)" }}>
        {([["mint", "BULLISH CONDITION MET"], ["ink-4", "NOT MET"], ["indigo", "INFORMATIONAL / NOT EVALUABLE"]] as const).map(([k, t]) => (
          <span key={t} style={{ display: "flex", alignItems: "center", gap: 6 }}><span style={{ width: 7, height: 7, borderRadius: "50%", background: cv(k) }} />{t}</span>
        ))}
        <span data-testid="mv-tech-delivery-note">
          {deliveryCoverage ? `DELIVERY % FROM THE NSE DELIVERY FEED · ${deliveryCoverage.sessions} OF ${deliveryCoverage.total} PLOTTED SESSIONS HAVE A VALUE` : "DELIVERY % FROM THE NSE DELIVERY FEED"}
        </span>
      </div>
    </section>
  );
}

export default MoversTech;
