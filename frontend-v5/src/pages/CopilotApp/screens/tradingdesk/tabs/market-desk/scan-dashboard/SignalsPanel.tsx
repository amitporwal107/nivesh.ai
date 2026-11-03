/**
 * Scan dashboard — "New signals" (docs/scan_builder/DESIGN.md §9; owner 3 Nov ~17:15 IST: "The whole idea is to give early
 * alerts and signals and trading plan for those stocks"). Today's signals, newest first: when a stock entered which scan,
 * its trading plan frozen at that moment — in the owner's chosen words for this screen, "Entry · Stop loss · Target 1 ·
 * Target 2" (his explicit exception to the 3 Nov wording rule; the rest of the page keeps the rule) — the strategy idea
 * for the stock when one exists, and the price now. Browser alerts (signal-alerts.ts) announce the new ones while the page
 * is open. The plan is rules-based (the server's `signals_meta.rules`), shown with its caveat.
 */
import { useMemo, useState, type MouseEvent } from "react";
import type { DashboardSignal, SignalsMeta } from "./market-dashboard-data";
import { useSignalAlerts } from "./signal-alerts";

const fmt2 = new Intl.NumberFormat("en-IN", { minimumFractionDigits: 2, maximumFractionDigits: 2 });
const n2 = (v: number | null | undefined): string | null => (typeof v === "number" && Number.isFinite(v) ? fmt2.format(v) : null);
const SHOWN = 20;

/** hh:mm in IST for an ISO time. */
export function istHm(iso: string | null | undefined): string | null {
  if (!iso) return null;
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return null;
  return d.toLocaleTimeString("en-IN", { timeZone: "Asia/Kolkata", hour: "2-digit", minute: "2-digit", hour12: false });
}

/** "Entry 852.40 · Stop loss 838.10 · Target 1 881.00 · Target 2 895.30" (the levels the signal has). */
export function planLevels(s: DashboardSignal): string {
  return [
    n2(s.entry) ? `Entry ${n2(s.entry)}` : null,
    n2(s.stop_loss) ? `Stop loss ${n2(s.stop_loss)}` : null,
    n2(s.target_1) ? `Target 1 ${n2(s.target_1)}` : null,
    n2(s.target_2) ? `Target 2 ${n2(s.target_2)}` : null,
  ].filter(Boolean).join(" · ");
}

function planTitle(s: DashboardSignal): string {
  return [
    s.stop_basis ? `Stop loss: ${s.stop_basis}` : null,
    s.target_1_basis ? `Target 1: ${s.target_1_basis}` : null,
    n2(s.risk_per_share) ? `risk ${n2(s.risk_per_share)} a share` : null,
  ].filter(Boolean).join(" · ");
}

export function SignalsPanel({ signals, meta, ideaFor, chartHref, onOpenSymbol }: {
  signals: DashboardSignal[];
  meta: SignalsMeta | null;
  ideaFor: (sym: string) => { text: string; title: string } | null;
  chartHref: (s: string) => string;
  onOpenSymbol: (s: string) => void;
}) {
  const [all, setAll] = useState(false);
  const [scan, setScan] = useState<string | null>(null);
  const alerts = useSignalAlerts(signals, meta?.day || signals[0]?.first_seen.slice(0, 10) || "");
  const scans = useMemo(() => {
    const m = new Map<string, string>();
    for (const s of signals) if (!m.has(s.widget_id)) m.set(s.widget_id, s.widget_title || s.widget_id);
    return Array.from(m.entries());
  }, [signals]);
  const filtered = scan ? signals.filter((s) => s.widget_id === scan) : signals;
  const shown = all ? filtered : filtered.slice(0, SHOWN);

  return (
    <section data-testid="sd-signals" aria-label="New signals" className="cp-card flex min-w-0 flex-col" style={{ padding: 0, overflow: "hidden" }}>
      <header className="flex min-w-0 flex-wrap items-center" style={{ gap: "6px 10px", padding: "12px 14px 8px" }}>
        <h4 className="m-0" style={{ fontSize: 15, fontWeight: 600, color: "var(--cp-ink)" }}>New signals</h4>
        <span data-testid="sd-signals-count" className="cp-pill" style={{ fontFamily: "var(--mono)", fontSize: 11 }}>
          {signals.length.toLocaleString("en-IN")} today
        </span>
        <span style={{ flex: "1 1 auto" }} />
        <AlertsControl alerts={alerts} />
      </header>
      {scans.length > 1 && (
        <div data-testid="sd-signals-filters" role="group" aria-label="Scans" className="cp-scroll flex overflow-x-auto" style={{ gap: 6, padding: "0 14px 8px" }}>
          {[[null, "All"] as const, ...scans].map(([id, label]) => {
            const on = scan === id;
            return (
              <button key={id ?? "all"} type="button" data-testid={`sd-signals-filter-${id ?? "all"}`} aria-pressed={on} onClick={() => setScan(id)}
                style={{ flex: "none", padding: "3px 10px", borderRadius: 999, fontSize: 12, cursor: "pointer", border: `1px solid ${on ? "var(--mint)" : "var(--line-2)"}`, background: on ? "var(--mint)" : "transparent", color: on ? "var(--bg-0)" : "var(--cp-ink-2)" }}>
                {label}
              </button>
            );
          })}
        </div>
      )}
      {signals.length === 0 ? (
        <p data-testid="sd-signals-empty" className="m-0" style={{ padding: "10px 14px 12px", borderTop: "1px solid var(--cp-line)", fontSize: 13, color: "var(--cp-ink-2)" }}>
          No signals yet today.{meta && !meta.recording ? " Signals are recorded while the market is open." : ""}
        </p>
      ) : (
        <ul className="m-0 cp-scroll" style={{ listStyle: "none", padding: 0, maxHeight: all ? 560 : undefined, overflow: all ? "auto" : undefined, borderTop: "1px solid var(--cp-line)" }}>
          {shown.map((s) => <SignalRow key={s.id} s={s} idea={ideaFor(s.symbol)} chartHref={chartHref} onOpenSymbol={onOpenSymbol} />)}
        </ul>
      )}
      {filtered.length > SHOWN && (
        <button type="button" data-testid="sd-signals-toggle" onClick={() => setAll((v) => !v)}
          style={{ alignSelf: "flex-start", border: 0, background: "none", padding: "8px 14px", cursor: "pointer", font: "inherit", fontSize: 12.5, color: "var(--mint)" }}>
          {all ? "Show fewer" : `Show all ${filtered.length.toLocaleString("en-IN")}`}
        </button>
      )}
      {meta && (meta.rules || meta.caveat) && (
        <div style={{ padding: "8px 14px 12px", borderTop: "1px solid var(--cp-line)", fontSize: 11.5, lineHeight: 1.5, color: "var(--cp-ink-3)" }}>
          {meta.rules && <p data-testid="sd-signals-rules" data-plan-words="true" className="m-0">{meta.rules}</p>}
          {meta.caveat && <p data-testid="sd-signals-caveat" data-plan-words="true" className="m-0">{meta.caveat}</p>}
        </div>
      )}
    </section>
  );
}

function SignalRow({ s, idea, chartHref, onOpenSymbol }: {
  s: DashboardSignal; idea: { text: string; title: string } | null; chartHref: (s: string) => string; onOpenSymbol: (s: string) => void;
}) {
  const move = s.move_since_pct;
  const moveTone = typeof move === "number" && Number.isFinite(move) ? (move < 0 ? "var(--cp-danger)" : "var(--mint)") : "var(--cp-ink-3)";
  const rr = [n2(s.rr_1), n2(s.rr_2)].filter(Boolean).join("/");
  return (
    <li data-testid="sd-signal" data-id={s.id} data-direction={s.direction} data-plan={s.plan_ok ? "true" : "false"}
      className="flex min-w-0 flex-col" style={{ gap: 3, padding: "8px 14px", borderBottom: "1px solid var(--cp-line)" }}>
      <div className="flex min-w-0 flex-wrap items-center" style={{ gap: "4px 8px", fontSize: 13 }}>
        <span data-testid="sd-signal-time" className="cp-mono-note" style={{ color: "var(--cp-ink-2)" }}>{istHm(s.first_seen) ?? "–"}</span>
        {s.at_open && <span data-testid="sd-signal-open" className="cp-pill" style={{ fontSize: 10.5 }}>at open</span>}
        <a data-testid="sd-signal-sym" data-symbol={s.symbol} href={chartHref(s.symbol)} title={`Open ${s.symbol} in Chart Analysis`}
          onClick={(e: MouseEvent<HTMLAnchorElement>) => {
            if (e.button !== 0 || e.metaKey || e.ctrlKey || e.shiftKey || e.altKey) return;
            e.preventDefault();
            onOpenSymbol(s.symbol);
          }}
          style={{ color: "var(--mint)", fontFamily: "var(--mono)", textDecoration: "none" }}>
          {s.symbol} <span aria-hidden>↗</span>
        </a>
        <span data-testid="sd-signal-dir" className="cp-pill" style={{ fontSize: 10.5, color: s.direction === "short" ? "var(--cp-danger)" : "var(--mint)" }}>
          {s.direction === "short" ? "Short" : "Long"}
        </span>
        <span data-testid="sd-signal-scan" style={{ color: "var(--cp-ink-2)" }}>{s.widget_title || s.widget_id}</span>
        <span style={{ flex: "1 1 auto" }} />
        {n2(s.price_now) && (
          <span data-testid="sd-signal-now" className="cp-num" style={{ fontSize: 12.5, color: "var(--cp-ink-2)" }}>
            Now {n2(s.price_now)}
            {typeof move === "number" && Number.isFinite(move) && <span style={{ color: moveTone }}> · {move > 0 ? "+" : ""}{fmt2.format(move)}%</span>}
          </span>
        )}
      </div>
      {s.plan_ok ? (
        <div data-testid="sd-signal-plan" data-plan-words="true" title={planTitle(s) || undefined} className="cp-num" style={{ fontSize: 12.5, color: "var(--cp-ink)" }}>
          {planLevels(s)}{rr ? <span style={{ color: "var(--cp-ink-2)" }}> · R:R {rr}</span> : null}
        </div>
      ) : (
        <div data-testid="sd-signal-noplan" data-plan-words="true" style={{ fontSize: 12.5, color: "var(--cp-ink-3)" }}>{s.plan_note || "No plan for this signal."}</div>
      )}
      {idea && (
        <div data-testid="sd-signal-idea" title={idea.title} style={{ fontSize: 12, color: "var(--cp-ink-2)" }}>Strategy idea: {idea.text}</div>
      )}
    </li>
  );
}

function AlertsControl({ alerts }: { alerts: ReturnType<typeof useSignalAlerts> }) {
  const { permission, muted, enable, toggleMuted } = alerts;
  const btn = { border: "1px solid var(--line-2)", background: "transparent", borderRadius: 999, padding: "3px 10px", fontSize: 12, cursor: "pointer", color: "var(--cp-ink-2)" } as const;
  if (permission === "unsupported") {
    return <span data-testid="sd-alerts" data-state="unsupported" className="cp-mono-note">Browser alerts are not available in this browser</span>;
  }
  if (permission === "denied") {
    return <span data-testid="sd-alerts" data-state="denied" className="cp-mono-note" style={{ color: "var(--amber)" }}>Browser alerts are blocked (allow notifications for this site in the browser)</span>;
  }
  if (permission === "default") {
    return <button type="button" data-testid="sd-alerts" data-state="off" onClick={() => { void enable(); }} style={btn}>Enable browser alerts</button>;
  }
  return (
    <button type="button" data-testid="sd-alerts" data-state={muted ? "paused" : "on"} onClick={toggleMuted} title={muted ? "Turn browser alerts back on" : "Pause browser alerts"}
      style={{ ...btn, borderColor: muted ? "var(--line-2)" : "var(--mint)", color: muted ? "var(--cp-ink-3)" : "var(--mint)" }}>
      {muted ? "Browser alerts paused" : "Browser alerts on"}
    </button>
  );
}
