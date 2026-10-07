/**
 * Flag lift card (Top Movers v4, "FLAG LIFT · CONDITIONAL ON VOLATILITY DECILE").
 *
 * Props: { data: MoversFlagLift | null; error?: string | null; onRetry?: () => void }
 *   data = GET /api/movers/flag-lift response (adapter type). null = loading.
 *
 * Honesty notes:
 *  - The D1..D10 strip is drawn from `by_decile` (flags) and `decile_base` (BASE row). A null lift is an empty cell, never
 *    a zero. Cells with fewer than THIN_FIRINGS firings are faded and hatched: a 1-firing cell is not a confident lift.
 *  - If `by_decile` is absent (older cached response) a single pooled bar is drawn and the card says per-decile is
 *    not available.
 *  - There is no "focus event" on this card, so the FOCUS chip, the ring and the "fired" dots are not drawn. The
 *    "IN DECILE" column shows the pooled within-decile lift (all ten deciles together).
 *  - Verdict words come from the API; the client only picks colours from them.
 */
import "./moversV4FlagLift.css";
import type { MoversFlagLift as FlagLiftData } from "@/services/adapters/movers.adapter";

type Flag = FlagLiftData["flags"][number];

const REASONS: Record<string, string> = {
  NIDP_INSIDER_SAST_NOT_BACKFILLED: "The insider / SAST source is not loaded yet.",
  NO_SOURCE: "There is no insider / SAST source in the data platform.",
  NO_BULK_DEAL_TABLE: "There is no bulk / block deal table to measure this from.",
  TOO_FEW_FIRINGS: "It fired too rarely to measure.",
  POPULATION_TOO_SMALL: "Too few stocks in this window to measure it.",
  NO_FINAL_RUN_IN_WINDOW: "No finished odds run in this window to measure against.",
  NO_ESTIMATES_FOR_HEAD: "No odds estimates exist for this question in this window.",
};

const VERDICT_NOTE: Record<string, string> = {
  SURVIVES: "Still adds information after allowing for volatility.",
  WEAK: "Adds only a little once volatility is allowed for.",
  DECORATION: "Adds nothing beyond volatility.",
  "PRE-PRICED": "Real signal, but already in the price before it can be acted on.",
};

/** A decile cell with fewer firings than this is faded + hatched and called thin in its tooltip. */
const THIN_FIRINGS = 5;
const GRID = "16px minmax(140px,1.3fr) 70px minmax(200px,2fr) 70px 100px";
const count = (n: number) => n.toLocaleString("en-IN");
const x = (v: number) => `${v.toFixed(2)}×`;
const num = (v: unknown): v is number => typeof v === "number" && Number.isFinite(v);

/** Design colour scale for a lift value (>=2 / 1.5 / 1.25 / below). */
const cellBg = (v: number) =>
  v >= 2 ? "var(--mint)" : v >= 1.5 ? "var(--mint-line)" : v >= 1.25 ? "var(--amber-line)" : "var(--bg-3)";
const curColor = (v: number) => (v >= 1.5 ? "var(--mint)" : v >= 1.25 ? "var(--amber)" : "var(--ink-3)");

function vTone(v: string): "mint" | "amber" | "ink-3" {
  return v === "SURVIVES" ? "mint" : v === "WEAK" || v === "PRE-PRICED" ? "amber" : "ink-3";
}

function reasonText(f: Flag): string {
  const code = f.reason ?? "";
  const text = REASONS[code] ?? (code ? `Not available (${code}).` : "Not available.");
  return code === "TOO_FEW_FIRINGS" ? `${text} Fired ${count(f.n)} time${f.n === 1 ? "" : "s"}.` : text;
}

const rowStyle: React.CSSProperties = {
  display: "grid", gridTemplateColumns: GRID, gap: 10, alignItems: "center", padding: "7px 0",
  borderTop: "1px solid var(--line)", fontFamily: "var(--mono)",
};
const stripStyle: React.CSSProperties = { display: "grid", gridTemplateColumns: "repeat(10,1fr)", gap: 3 };
const poolStyle: React.CSSProperties = { display: "grid", gridTemplateColumns: "repeat(1,1fr)", gap: 3 };
const HATCH = "repeating-linear-gradient(135deg, rgba(0,0,0,.45) 0 2px, transparent 2px 5px)";

type Dec = NonNullable<Flag["by_decile"]>[number];

function Cell({ c }: { c: Dec }) {
  const lift = num(c.lift) ? c.lift : null;
  const thin = c.firings < THIN_FIRINGS;
  const tip =
    lift == null
      ? `D${c.decile} · no lift (${count(c.firings)} firings, ${count(c.moved)} moved)`
      : `D${c.decile} · ${x(lift)} · ${count(c.firings)} firings, ${count(c.moved)} moved${thin ? ` · thin (fewer than ${THIN_FIRINGS} firings)` : ""}`;
  return (
    <span
      title={tip}
      aria-label={tip}
      data-thin={thin ? "1" : undefined}
      style={{
        height: 14, borderRadius: 3,
        background: lift == null ? "transparent" : cellBg(lift),
        border: lift == null ? "1px dashed var(--line-3)" : "none",
        boxSizing: "border-box",
        opacity: lift != null && thin ? 0.4 : 1,
        backgroundImage: lift != null && thin ? HATCH : undefined,
      }}
    />
  );
}

function Row({ f }: { f: Flag }) {
  if (!f.available) {
    return (
      <div style={rowStyle} data-testid={`mv-lift-${f.key}`} className="mv-lift-row mv-lift-row-na">
        <span />
        <span style={{ fontSize: 11, letterSpacing: ".06em", color: "var(--ink-3)" }}>{f.label}</span>
        <span
          data-testid={`mv-lift-na-${f.key}`}
          style={{ gridColumn: "3 / 7", fontSize: 11, color: "var(--ink-4)", letterSpacing: ".02em", lineHeight: 1.4 }}
        >
          <span style={{ letterSpacing: ".1em", color: "var(--ink-3)" }}>NOT MEASURED</span> · {reasonText(f)}
        </span>
      </div>
    );
  }
  const within = num(f.lift_within) ? f.lift_within : null;
  const v = f.verdict;
  const tone = v ? vTone(v) : "ink-3";
  return (
    <div style={rowStyle} data-testid={`mv-lift-${f.key}`} className={`mv-lift-row${v ? ` mv-lift-v-${v.toLowerCase()}` : ""}`}>
      <span />
      <span style={{ fontSize: 11, letterSpacing: ".06em", color: "var(--ink-2)" }}>{f.label}</span>
      <span
        style={{ fontSize: 12, textAlign: "right", color: "var(--ink-3)", textDecoration: "line-through", textDecorationColor: "var(--ink-4)" }}
        title="Across all names: volatility alone explains most of it"
      >
        {num(f.lift_uncond) ? x(f.lift_uncond) : "n/a"}
      </span>
      {f.by_decile && f.by_decile.length > 0 ? (
        <div style={stripStyle}>{f.by_decile.map((c) => <Cell key={c.decile} c={c} />)}</div>
      ) : (
        <div style={poolStyle}>
          <span
            style={{ height: 14, borderRadius: 3, background: within == null ? "transparent" : cellBg(within), border: within == null ? "1px dashed var(--line-3)" : "none" }}
            title={within == null ? "No within-decile lift reported" : `All ten ATR deciles pooled · ${x(within)} · fired ${count(f.n)} times · per-decile not available`}
          />
        </div>
      )}
      <span style={{ fontSize: 12.5, fontWeight: 500, textAlign: "right", color: within == null ? "var(--ink-4)" : curColor(within) }}>
        {within == null ? "—" : x(within)}
      </span>
      {v ? (
        <span
          title={VERDICT_NOTE[v]}
          style={{
            justifySelf: "end", padding: "2px 7px", borderRadius: 999, fontSize: 9.5, letterSpacing: ".08em",
            border: `1px solid ${v === "DECORATION" ? "var(--line-3)" : `var(--${tone}-line)`}`,
            background: v === "DECORATION" ? "transparent" : `var(--${tone}-soft)`,
            color: `var(--${tone})`,
          }}
        >
          {v}
        </span>
      ) : (
        <span style={{ justifySelf: "end", fontSize: 9.5, letterSpacing: ".08em", color: "var(--ink-4)" }}>NO VERDICT</span>
      )}
    </div>
  );
}

const card: React.CSSProperties = {
  borderRadius: 14, background: "var(--bg-1)", border: "1px solid var(--line)", boxShadow: "var(--shadow-card)",
  padding: "18px 20px", display: "flex", flexDirection: "column", gap: 14,
};

export function MoversFlagLift(props: { data: FlagLiftData | null; error?: string | null; onRetry?: () => void }) {
  const { data, error, onRetry } = props;
  if (error) {
    return (
      <section className="mv4-lift" style={card} data-testid="mv-lift" role="alert">
        <span style={{ fontFamily: "var(--mono)", fontSize: 11, color: "var(--danger)" }}>Could not load the flag comparison: {error}</span>
        {onRetry && (
          <button type="button" onClick={onRetry} className="mv4-lift-retry">Try again</button>
        )}
      </section>
    );
  }
  if (!data) {
    return (
      <section className="mv4-lift" style={card} data-testid="mv-lift" aria-busy="true">
        <span style={{ fontFamily: "var(--mono)", fontSize: 11, color: "var(--ink-3)", letterSpacing: ".14em" }}>LOADING FLAG LIFT…</span>
      </section>
    );
  }
  const measured = data.flags.filter((f) => f.available && f.verdict != null);
  const survive = measured.filter((f) => f.verdict === "SURVIVES").length;
  const pre = measured.filter((f) => f.verdict === "PRE-PRICED").length;
  const notMeasured = data.flags.length - measured.length;
  const base = num(data.base_rate) ? data.base_rate : null;
  const noData = measured.length === 0;
  const hasDec = measured.some((f) => f.by_decile && f.by_decile.length > 0);
  const horizon = num(data.horizon) ? data.horizon : null;
  return (
    <section className="mv4-lift" style={card} data-testid="mv-lift" aria-label="Flag lift conditional on volatility decile">
      <div style={{ display: "flex", alignItems: "center", gap: 10, flexWrap: "wrap" }}>
        <span style={{ fontFamily: "var(--mono)", fontSize: 11, letterSpacing: ".14em", color: "var(--ink-3)" }}>
          FLAG LIFT · CONDITIONAL ON VOLATILITY DECILE
        </span>
        <span style={{ flex: 1 }} />
        <span style={{ fontFamily: "var(--mono)", fontSize: 10, letterSpacing: ".1em", color: "var(--ink-4)" }}>
          {data.from} → {data.to}
        </span>
      </div>
      <span style={{ fontFamily: "var(--display)", fontSize: 26, lineHeight: 1.2, textWrap: "pretty" } as React.CSSProperties}>
        {noData ? (
          <span style={{ color: "var(--ink-3)" }}>No flag could be measured in this window.</span>
        ) : (
          <>
            <span style={{ color: "var(--mint)" }}>{survive} of {measured.length} measured flags</span>
            {` keep tradeable lift once volatility is held fixed. ${pre} more ${pre === 1 ? "is" : "are"} informative but already in the price.`}
          </>
        )}
      </span>
      <div style={{ overflowX: "auto" }}>
        <div style={{ minWidth: 620, display: "flex", flexDirection: "column" }}>
          <div
            style={{
              display: "grid", gridTemplateColumns: GRID, gap: 10, alignItems: "end", paddingBottom: 6,
              fontFamily: "var(--mono)", fontSize: 9.5, letterSpacing: ".1em", color: "var(--ink-4)",
            }}
          >
            <span />
            <span>FLAG</span>
            <span style={{ textAlign: "right" }}>ALL NAMES</span>
            <span>{hasDec ? "LIFT BY ATR DECILE · D1 → D10" : "LIFT · ALL DECILES POOLED"}</span>
            <span style={{ textAlign: "right" }}>POOLED</span>
            <span style={{ textAlign: "right" }}>VERDICT</span>
          </div>
          <div style={rowStyle} data-testid="mv-lift-base">
            <span />
            <span style={{ fontSize: 11, letterSpacing: ".06em", color: "var(--indigo)" }}>BASE ±5% RATE</span>
            <span style={{ fontSize: 12, textAlign: "right", color: "var(--indigo)" }}>{base == null ? "—" : `${(base * 100).toFixed(0)}%`}</span>
            {data.decile_base && data.decile_base.length > 0 ? (
              <div style={stripStyle}>
                {data.decile_base.map((d) => {
                  const r = num(d.base_rate) ? d.base_rate : null;
                  const tip = r == null ? `D${d.decile} · no rate (${count(d.n)} stock-days)` : `D${d.decile} · ${(r * 100).toFixed(0)}% of ${count(d.n)} stock-days reach ±5%`;
                  return (
                    <span key={d.decile} title={tip} aria-label={tip}
                      style={{ height: 14, borderRadius: 3, boxSizing: "border-box", background: r == null ? "transparent" : r >= 0.25 ? "var(--indigo)" : r >= 0.12 ? "var(--indigo-line)" : "var(--indigo-soft)", border: r == null ? "1px dashed var(--line-3)" : "none" }} />
                  );
                })}
              </div>
            ) : (
              <div style={poolStyle}>
                <span
                  style={{ height: 14, borderRadius: 3, background: base == null ? "transparent" : base >= 0.25 ? "var(--indigo)" : base >= 0.12 ? "var(--indigo-line)" : "var(--indigo-soft)" }}
                  title="Share of all stock-days in the window that reached ±5%; per-decile rates are not available"
                />
              </div>
            )}
            <span style={{ fontSize: 12.5, fontWeight: 500, textAlign: "right", color: "var(--ink-4)" }}>—</span>
            <span style={{ justifySelf: "end", padding: "2px 7px", borderRadius: 999, border: "1px solid var(--indigo-line)", color: "var(--indigo)", fontSize: 9.5, letterSpacing: ".08em" }}>
              MECHANISM
            </span>
          </div>
          {data.flags.map((f) => <Row key={f.key} f={f} />)}
        </div>
      </div>
      <div style={{ display: "flex", flexWrap: "wrap", gap: 14, alignItems: "center", fontFamily: "var(--mono)", fontSize: 9.5, letterSpacing: ".08em", color: "var(--ink-3)" }}>
        {([["var(--mint)", "≥2×"], ["var(--mint-line)", "1.5–2×"], ["var(--amber-line)", "1.25–1.5×"], ["var(--bg-3)", "<1.25×"]] as const).map(([bg, t]) => (
          <span key={t} style={{ display: "flex", alignItems: "center", gap: 6 }}>
            <span style={{ width: 12, height: 10, borderRadius: 2, background: bg }} />{t}
          </span>
        ))}
        <span style={{ display: "flex", alignItems: "center", gap: 6 }}>
          <span style={{ width: 12, height: 10, borderRadius: 2, background: "var(--mint)", opacity: 0.4, backgroundImage: HATCH }} />faded = fewer than {THIN_FIRINGS} firings
        </span>
        <span style={{ display: "flex", alignItems: "center", gap: 6 }}>
          <span style={{ width: 12, height: 10, borderRadius: 2, border: "1px dashed var(--line-3)", boxSizing: "border-box" }} />empty = no lift
        </span>
      </div>
      <span style={{ fontSize: 13, lineHeight: 1.5, color: "var(--ink-3)", textWrap: "pretty" } as React.CSSProperties}>
        Measured on the real {count(data.population)} stock-days from {data.from} to {data.to}
        {horizon != null ? `, ±5% within ${horizon} sessions` : ""}. The struck-through figure is the lift across all names,
        where volatility alone explains most of it. Each cell compares the flag with all stock-days in the same ATR decile ({data.deciles} deciles, D1 calmest); the POOLED column is all ten together. {hasDec ? "A faded cell rests on very few firings and is not a firm lift; hover a cell for its firings and moves." : "Per-decile cells are not available in this response, so a single pooled bar is shown."}{" "}
        Anything that survives is new information.
        {notMeasured > 0 ? ` ${notMeasured} flag${notMeasured === 1 ? " is" : "s are"} not measured (reason shown on its row).` : ""}
      </span>
    </section>
  );
}
