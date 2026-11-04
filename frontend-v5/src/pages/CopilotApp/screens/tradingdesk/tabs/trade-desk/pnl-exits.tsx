/**
 * P&L dashboard — Exit watch (docs/paper_pnl_dashboard/EXIT_WATCH.md; test cases EW-33 … EW-37): the stop loss and exit alerts of
 * the user's LIVE broker positions. Owner, 4 Nov 2026: "I need proper alerts and signals when to exit and take a stop loss";
 * alerts in the app only for now; default stop 2 × ATR, trailing (hedged futures: the put strike).
 *
 *   ExitBanner   under the header while any alert is unseen: the newest one's words, the count, Mark seen
 *   ExitWatch    after the open positions: one row per watched position (a card on a phone) — price, stop loss and how it is
 *                set, distance, status, loss at the stop, the latest signal; a row opens to its stop history, the rule and
 *                "Set my stop" / "Use the rule"; what is not watched and why; the last 7 days of alerts; the watcher's line.
 *
 * Read-only towards the broker: nothing here places, modifies or cancels an order. The writes are the alerts' seen mark and
 * the user's own stop (PUT / DELETE /api/positions/{underlying}/levels). Figures are the route's; null → "—", never 0.
 * Standard trading words are allowed on this screen (owner, 3–4 Nov); never recommend / pick / suggested.
 */
import { useState, type CSSProperties, type FormEvent, type KeyboardEvent, type ReactNode } from "react";
import type { UseQueryResult } from "@tanstack/react-query";
import { ApiError } from "@/services/api/errors";
import { fmtINR, fmtNum, fmtPct, LoadingBlock, type Tone } from "../../../../components/ui";
import { QueryProblem } from "../../../trading/parts";
import { linkBtn, quiet } from "./parts";
import {
  levelsProblem, useClearOwnStop, useMarkExitsSeen, useSetOwnStop,
  type AlertSeverity, type ExitAlert, type ExitKind, type ExitMethod, type ExitPosition, type ExitStatus, type ExitWatch,
} from "./pnl-data";
import { MONO, Pill, TONES, card, eyebrow, serifTitle } from "./pnl-ui";

export const WATCHER_LINE = "Checked live every 30 s in market hours · stops move after NSE's end-of-day file · in-app only · nothing is sent to your broker";

const STATUS: Record<ExitStatus, { text: string; tone: Tone }> = {
  HIT: { text: "Hit", tone: "danger" }, NEAR: { text: "Near", tone: "amber" }, OK: { text: "OK", tone: "mint" },
  FLOOR: { text: "At floor", tone: "amber" }, NO_STOP: { text: "No stop", tone: "ink" },
};
const METHOD: Record<ExitMethod, { text: string; tone: Tone; long: string }> = {
  atr_trail: { text: "2 × ATR trail", tone: "indigo", long: "the 2 × ATR trailing rule" },
  yours: { text: "Yours", tone: "mint", long: "your own stop loss" },
  put_floor: { text: "Put floor", tone: "mint", long: "the strike of the protective put" },
  call_cap: { text: "Call cap", tone: "mint", long: "the strike of the protective call" },
  none: { text: "No stop", tone: "ink", long: "no stop loss" },
};
const KIND: Record<ExitKind, string> = { shares: "Shares", future: "Future", hedged: "Hedged" };
const SOURCE: Record<string, string> = { kite_live: "Kite live", kite_close: "Kite close (provisional)", eod: "Exchange close" };
const SEV: Record<AlertSeverity, Tone> = { CRITICAL: "danger", WARNING: "amber", INFO: "indigo" };
export const ALERT_WORDS: Record<string, string> = {
  STOP_HIT: "Stop loss hit", NEAR_STOP: "Near the stop loss", FLOOR_REACHED: "At the hedge floor", CLOSE_THROUGH_STOP: "Closed through the stop loss",
  SUPPORT_BREAK: "Support broken", TREND_TURN: "Trend turned", STOP_RAISED: "Stop loss moved", HEDGE_REMOVED: "Hedge removed", RESULTS_SOON: "Results soon",
};
const FEED_WHY: Record<string, string> = {
  feed_not_live: "The live feed is not live just now, so the last live round raised nothing.",
  no_saved_close: "No saved close for the last session yet.",
  unreadable: "Live prices could not be read on the last round, so it raised nothing.",
};

const px = (v: number | null | undefined) => (v == null || !Number.isFinite(v) ? "—" : v.toLocaleString("en-IN", { minimumFractionDigits: 2, maximumFractionDigits: 2 }));
const WHEN = new Intl.DateTimeFormat("en-IN", { timeZone: "Asia/Kolkata", day: "2-digit", month: "short", hour: "2-digit", minute: "2-digit", hour12: false });
const when = (iso: string | null) => {
  if (!iso) return null;
  const d = new Date(iso);
  return Number.isNaN(d.getTime()) ? null : `${WHEN.format(d)} IST`;
};
const words = (kind: string) => ALERT_WORDS[kind] ?? kind.replace(/_/g, " ").toLowerCase();
const not404 = (e: unknown) => !(e instanceof ApiError && e.status === 404);

function Chip({ tone, children, testId, attrs, title }: { tone: Tone; children: ReactNode; testId?: string; attrs?: Record<string, string>; title?: string }) {
  return <Pill tone={tone} testId={testId} attrs={attrs} title={title} style={{ padding: "2px 8px", fontSize: 10, letterSpacing: "0.08em" }}>{children}</Pill>;
}

/** Loss at the stop in words: a loss in danger, a gain locked in (negative figure) in mint. */
function LossAt({ p }: { p: ExitPosition }) {
  if (p.lossAtStop == null) return <span style={{ color: "var(--cp-ink-3)" }}>—</span>;
  if (p.lossAtStop < 0) return <span data-testid="pnl-exit-loss" data-value={String(p.lossAtStop)} style={{ color: "var(--mint)" }}>locks in {fmtINR(-p.lossAtStop)}</span>;
  return <span data-testid="pnl-exit-loss" data-value={String(p.lossAtStop)} style={{ color: "var(--cp-danger)" }}>{fmtINR(-p.lossAtStop)}</span>;
}

function Distance({ p }: { p: ExitPosition }) {
  if (p.distancePct == null && p.distanceAtr == null) return <span style={{ color: "var(--cp-ink-3)" }}>—</span>;
  return (
    <span data-testid="pnl-exit-distance">
      {fmtPct(p.distancePct, { digits: 2 })}{p.distanceAtr != null ? ` · ${p.distanceAtr < 0 ? "−" : ""}${Math.abs(p.distanceAtr).toFixed(2)} ATR` : ""}
    </span>
  );
}

function StopCell({ p, align = "flex-end" }: { p: ExitPosition; align?: CSSProperties["alignItems"] }) {
  const m = METHOD[p.method];
  return (
    <div data-testid="pnl-exit-stop" data-method={p.method} className="flex min-w-0 flex-col" style={{ gap: 4, alignItems: align }}>
      <span style={{ fontFamily: MONO, fontSize: 12.5, color: p.stop == null ? "var(--cp-ink-3)" : "var(--cp-ink)" }}>{px(p.stop)}</span>
      <Chip tone={m.tone} testId="pnl-exit-method">{m.text}</Chip>
    </div>
  );
}

function StatusChip({ p }: { p: ExitPosition }) {
  const st = STATUS[p.status];
  return <Chip tone={st.tone} testId="pnl-exit-status" attrs={{ "data-status": p.status }} title={p.why ?? undefined}>{st.text}</Chip>;
}

function PriceCell({ p, align = "flex-end" }: { p: ExitPosition; align?: CSSProperties["alignItems"] }) {
  const src = p.priceSource ? SOURCE[p.priceSource] ?? p.priceSource : null;
  return (
    <div className="flex min-w-0 flex-col" style={{ gap: 3, alignItems: align }}>
      <span data-testid="pnl-exit-price" style={{ fontFamily: MONO, fontSize: 12.5, color: p.priceSource === "kite_live" ? "var(--cp-ink)" : "var(--cp-ink-2)" }}>{px(p.price)}</span>
      <span data-testid="pnl-exit-source" style={{ fontSize: 10.5, color: "var(--cp-ink-3)", overflowWrap: "anywhere" }}>{src ?? "No price"}{p.priceAsOf && p.priceSource === "kite_live" ? ` · ${when(p.priceAsOf)}` : ""}</span>
    </div>
  );
}

function LatestSignal({ a }: { a: ExitAlert | null }) {
  if (!a) return <span data-testid="pnl-exit-signal" style={{ color: "var(--cp-ink-3)", fontSize: 12 }}>—</span>;
  return (
    <span data-testid="pnl-exit-signal" data-kind={a.kind} className="flex min-w-0 flex-col" style={{ gap: 2, fontSize: 12 }}>
      <span style={{ color: TONES[SEV[a.severity]].c, overflowWrap: "anywhere" }}>{words(a.kind)}</span>
      <span style={{ color: "var(--cp-ink-3)", fontSize: 11 }}>{when(a.at) ?? a.day ?? ""}</span>
    </span>
  );
}

// ── one position's detail: history, rule, your own stop ────────────────────────────────────────────────────────────────────

function OwnStop({ p }: { p: ExitPosition }) {
  const [value, setValue] = useState("");
  const [msg, setMsg] = useState<{ ok: boolean; text: string } | null>(null);
  const save = useSetOwnStop();
  const clear = useClearOwnStop();
  const busy = save.isPending || clear.isPending;
  const submit = (e: FormEvent) => {
    e.preventDefault();
    const v = Number(value);
    if (!value.trim() || !Number.isFinite(v) || v <= 0) {
      setMsg({ ok: false, text: "Enter a price above zero." });
      return;
    }
    setMsg(null);
    save.mutate({ underlying: p.underlying, stop: v, own: p.own }, {
      onSuccess: (r) => { setValue(""); setMsg({ ok: true, text: `Saved: your stop loss ${px(r.stop ?? v)} now replaces the rule for ${p.underlying} in every account.` }); },
      onError: (err) => setMsg({ ok: false, text: levelsProblem(err) }),
    });
  };
  const useRule = () => {
    setMsg(null);
    clear.mutate({ underlying: p.underlying, own: p.own }, {
      onSuccess: () => setMsg({ ok: true, text: `Your own stop loss for ${p.underlying} is cleared: the rule applies again.` }),
      onError: (err) => setMsg({ ok: false, text: levelsProblem(err) }),
    });
  };
  return (
    <div className="flex min-w-0 flex-col" style={{ gap: 8 }}>
      <form data-testid="pnl-exit-setstop" onSubmit={submit} className="flex flex-wrap items-center" style={{ gap: 8 }}>
        <label style={{ ...eyebrow, color: "var(--cp-ink-2)" }} htmlFor={`stop-${p.key}`}>Set my stop loss</label>
        <input id={`stop-${p.key}`} data-testid="pnl-exit-setstop-input" type="number" inputMode="decimal" step="0.05" min="0" value={value}
          placeholder={p.stop != null ? px(p.stop).replace(/,/g, "") : "price"} onChange={(e) => setValue(e.target.value)} disabled={busy}
          style={{ width: 120, padding: "6px 8px", borderRadius: 8, border: "1px solid var(--line-3)", background: "var(--bg-1)", color: "var(--cp-ink)", fontFamily: MONO, fontSize: 12.5 }} />
        <button type="submit" data-testid="pnl-exit-setstop-save" disabled={busy}
          style={{ cursor: busy ? "wait" : "pointer", padding: "6px 12px", borderRadius: 999, border: "1px solid var(--line-3)", background: "var(--bg-3)", color: "var(--cp-ink)", fontFamily: MONO, fontSize: 10.5, letterSpacing: "0.08em", textTransform: "uppercase" }}>
          {save.isPending ? "Saving…" : "Save"}
        </button>
        {p.method === "yours" && (
          <button type="button" data-testid="pnl-exit-userule" onClick={useRule} disabled={busy} style={{ ...linkBtn, fontSize: 12.5 }}>
            {clear.isPending ? "Clearing…" : "Use the rule"}
          </button>
        )}
      </form>
      <span style={{ ...quiet, fontSize: 11.5 }}>
        Your own stop loss is kept per stock and applies to {p.underlying} in every account, on the share price. It is watched here; it is not an order at your broker.
      </span>
      {msg && <span data-testid="pnl-exit-setstop-msg" role={msg.ok ? "status" : "alert"} style={{ fontSize: 12.5, color: msg.ok ? "var(--mint)" : "var(--cp-danger)" }}>{msg.text}</span>}
    </div>
  );
}

function ExitDetail({ p, ruleText }: { p: ExitPosition; ruleText: string | null }) {
  const hist = p.history.slice(-5).reverse();
  const facts: Array<[string, ReactNode]> = [
    ["Stop loss", <>{px(p.stop)} · {METHOD[p.method].long}{p.stopDay ? ` · from ${p.stopDay}` : ""}</>],
    ["Rule level", p.ruleStop != null ? px(p.ruleStop) : "—"],
    ["ATR (14)", p.atr != null ? `${px(p.atr)}${p.atrPct != null ? ` · ${fmtPct(p.atrPct, { digits: 2 })}` : ""}` : "—"],
    ["Support (20-session low)", px(p.support)],
  ];
  return (
    <div data-testid="pnl-exit-detail" data-key={p.key} className="flex min-w-0 flex-col" style={{ gap: 12, padding: "14px 18px 16px", background: "var(--bg-2)", borderTop: "1px solid var(--cp-line)" }}>
      <div className="grid" style={{ gridTemplateColumns: "repeat(auto-fit,minmax(min(100%,180px),1fr))", gap: "8px 16px" }}>
        {facts.map(([k, v]) => (
          <div key={k} className="flex min-w-0 flex-col" style={{ gap: 2 }}>
            <span style={eyebrow}>{k}</span>
            <span style={{ fontFamily: MONO, fontSize: 12.5, color: "var(--cp-ink)", overflowWrap: "anywhere" }}>{v}</span>
          </div>
        ))}
      </div>
      {p.legs.length > 0 && (
        <div data-testid="pnl-exit-legs" className="flex min-w-0 flex-col" style={{ gap: 3 }}>
          <span style={eyebrow}>Legs</span>
          {p.legs.map((l, i) => (
            <span key={i} style={{ fontFamily: MONO, fontSize: 12, color: "var(--cp-ink-2)", overflowWrap: "anywhere" }}>
              {l.instrument ?? "—"} · {l.type ?? "—"}{l.strike != null ? ` ${px(l.strike)}` : ""}{l.expiry ? ` · ${l.expiry}` : ""} · {l.quantity == null ? "—" : fmtNum(l.quantity)} @ {px(l.avg)}
            </span>
          ))}
        </div>
      )}
      {(p.stored === false || p.note || p.why || p.lossBasis) && (
        <ul className="m-0 flex flex-col" style={{ gap: 3, paddingLeft: 16, ...quiet, fontSize: 12 }}>
          {p.stored === false && <li data-testid="pnl-exit-unstored">Worked out for this view; the watcher stores it on its next round.</li>}
          {p.why && <li>{p.why}</li>}
          {p.note && <li>{p.note}</li>}
          {p.lossBasis && <li>Loss at the stop: {p.lossBasis}</li>}
        </ul>
      )}
      <div data-testid="pnl-exit-history" className="flex min-w-0 flex-col" style={{ gap: 4 }}>
        <span style={eyebrow}>Stop history · last {hist.length || 0} evening{hist.length === 1 ? "" : "s"}</span>
        {hist.length ? hist.map((h, i) => (
          <span key={`${h.day}-${i}`} data-testid="pnl-exit-history-row" style={{ fontFamily: MONO, fontSize: 11.5, color: "var(--cp-ink-2)", overflowWrap: "anywhere" }}>
            {h.day ?? "—"} · close {px(h.close)} · ATR {px(h.atr)} · rule {px(h.candidate)} · stop {px(h.stop)} {h.moved ? "(moved)" : h.moved === false ? "(held)" : ""}{h.reason ? ` · ${h.reason}` : ""}
          </span>
        )) : <span style={{ ...quiet, fontSize: 12 }}>No evening recorded yet: the stop moves after NSE's end-of-day file.</span>}
      </div>
      {ruleText && <span data-testid="pnl-exit-rule" style={{ ...quiet, fontSize: 12 }}>{ruleText}</span>}
      <OwnStop p={p} />
    </div>
  );
}

// ── rows (desktop) and cards (phone) ───────────────────────────────────────────────────────────────────────────────────────

const COLS = [1.5, 1, 1.15, 1, 0.75, 1, 1.4].map((f) => `minmax(0,${f}fr)`).join(" ");
const TABLE_MIN = 880;
const HEADS: Array<[string, boolean]> = [["Position", false], ["Price", true], ["Stop loss", true], ["Distance", true], ["Status", false], ["Loss at stop", true], ["Latest signal", false]];
const numCell: CSSProperties = { textAlign: "right", fontFamily: MONO, fontSize: 12, fontVariantNumeric: "tabular-nums", minWidth: 0, overflowWrap: "anywhere" };

function PositionCell({ p }: { p: ExitPosition }) {
  return (
    <div className="flex min-w-0 flex-col" style={{ gap: 4 }}>
      <span data-testid="pnl-exit-label" style={{ fontWeight: 500, color: "var(--cp-ink)", overflowWrap: "anywhere" }}>{p.label}</span>
      <span className="flex flex-wrap items-center" style={{ gap: 6 }}>
        {p.kind && <Chip tone={p.kind === "hedged" ? "mint" : "ink"} testId="pnl-exit-kind" attrs={{ "data-kind": p.kind }}>{KIND[p.kind]}</Chip>}
        <span style={{ fontSize: 12, color: "var(--cp-ink-3)", overflowWrap: "anywhere" }}>{p.account ?? "Broker"}{p.side ? ` · ${p.side}` : ""}</span>
      </span>
    </div>
  );
}

function ExitRow({ p, latest, open, onToggle }: { p: ExitPosition; latest: ExitAlert | null; open: boolean; onToggle: () => void }) {
  const onKey = (e: KeyboardEvent<HTMLDivElement>) => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); onToggle(); } };
  return (
    <div role="row" data-testid="pnl-exit-row" data-key={p.key} data-status={p.status} tabIndex={0} aria-expanded={open} onClick={onToggle} onKeyDown={onKey}
      className="grid items-center" style={{ gridTemplateColumns: COLS, gap: 8, padding: "12px 16px", cursor: "pointer", background: open ? "var(--bg-2)" : "transparent", fontSize: 13.5 }}>
      <div role="cell"><PositionCell p={p} /></div>
      <div role="cell"><PriceCell p={p} /></div>
      <div role="cell"><StopCell p={p} /></div>
      <div role="cell" style={numCell}><Distance p={p} /></div>
      <div role="cell"><StatusChip p={p} /></div>
      <div role="cell" style={numCell}><LossAt p={p} /></div>
      <div role="cell" className="min-w-0"><LatestSignal a={latest} /></div>
    </div>
  );
}

function ExitCard({ p, latest, open, onToggle, children }: { p: ExitPosition; latest: ExitAlert | null; open: boolean; onToggle: () => void; children: ReactNode }) {
  return (
    <div data-testid="pnl-exit-card" data-key={p.key} data-status={p.status} className="flex min-w-0 flex-col" style={{ ...card, boxShadow: "none", overflow: "hidden" }}>
      <button type="button" data-testid="pnl-exit-expand" aria-expanded={open} onClick={onToggle} className="flex min-w-0 flex-col"
        style={{ gap: 8, padding: "12px 14px", border: 0, background: open ? "var(--bg-2)" : "none", cursor: "pointer", color: "inherit", font: "inherit", textAlign: "left" }}>
        <span className="flex min-w-0 items-start justify-between" style={{ gap: 10, width: "100%" }}>
          <PositionCell p={p} />
          <StatusChip p={p} />
        </span>
        <span className="grid" style={{ gridTemplateColumns: "repeat(2,minmax(0,1fr))", gap: "8px 12px", width: "100%" }}>
          <span className="flex min-w-0 flex-col" style={{ gap: 2 }}><span style={eyebrow}>Price</span><PriceCell p={p} align="flex-start" /></span>
          <span className="flex min-w-0 flex-col" style={{ gap: 2 }}><span style={eyebrow}>Stop loss</span><StopCell p={p} align="flex-start" /></span>
          <span className="flex min-w-0 flex-col" style={{ gap: 2, fontFamily: MONO, fontSize: 12 }}><span style={eyebrow}>Distance</span><Distance p={p} /></span>
          <span className="flex min-w-0 flex-col" style={{ gap: 2, fontFamily: MONO, fontSize: 12 }}><span style={eyebrow}>Loss at stop</span><LossAt p={p} /></span>
        </span>
        <span className="flex min-w-0 items-end justify-between" style={{ gap: 10, width: "100%" }}>
          <LatestSignal a={latest} />
          <span style={{ ...quiet, fontSize: 10.5, flex: "none" }}>{open ? "less" : "more"}</span>
        </span>
      </button>
      {open && children}
    </div>
  );
}

// ── the alerts ─────────────────────────────────────────────────────────────────────────────────────────────────────────────

function AlertItem({ a }: { a: ExitAlert }) {
  const t = TONES[SEV[a.severity]];
  return (
    <div data-testid="pnl-exit-alert" data-id={a.id} data-kind={a.kind} data-severity={a.severity} data-seen={a.seen ? "true" : "false"}
      className="flex items-start" style={{ gap: 12, padding: "10px 12px", borderRadius: 10, background: a.seen ? "transparent" : t.soft, border: `1px solid ${a.seen ? "var(--cp-line)" : t.line}` }}>
      <span aria-hidden style={{ marginTop: 6, width: 6, height: 6, borderRadius: "50%", background: a.seen ? "var(--cp-ink-3)" : t.c, flex: "none" }} />
      <div className="flex min-w-0 flex-col" style={{ gap: 2 }}>
        <span className="flex flex-wrap items-center" style={{ gap: 8, fontSize: 13.5, fontWeight: 500, color: "var(--cp-ink)" }}>
          {words(a.kind)}{a.underlying ? ` · ${a.underlying}` : ""}{a.account ? ` · ${a.account}` : ""}
          {!a.seen && <Chip tone={SEV[a.severity]} testId="pnl-exit-alert-new">New</Chip>}
        </span>
        <span style={{ fontSize: 12.5, color: "var(--cp-ink-2)", lineHeight: 1.45, overflowWrap: "anywhere" }}>{a.text}</span>
        <span className="cp-num" style={{ fontSize: 11, color: "var(--cp-ink-3)" }}>
          {when(a.at) ?? a.day ?? "—"}{a.price != null ? ` · price ${px(a.price)}` : ""}{a.level != null ? ` · level ${px(a.level)}` : ""}{a.source ? ` · ${SOURCE[a.source] ?? a.source}` : ""}
        </span>
      </div>
    </div>
  );
}

/** Under the header while any exit alert is unseen. Nothing while the route is missing or quiet. */
export function ExitBanner({ q }: { q: UseQueryResult<ExitWatch> }) {
  const mark = useMarkExitsSeen();
  const x = q.data;
  if (!x || x.unseen <= 0) return null;
  const newest = x.alerts.find((a) => !a.seen) ?? null;
  const sev: AlertSeverity = x.alerts.some((a) => !a.seen && a.severity === "CRITICAL") ? "CRITICAL" : newest?.severity ?? "WARNING";
  const t = TONES[SEV[sev]];
  return (
    <div data-testid="pnl-exit-banner" data-severity={sev} role={sev === "CRITICAL" ? "alert" : "status"} className="flex min-w-0 flex-wrap items-center"
      style={{ gap: "8px 14px", padding: "12px 16px", borderRadius: 12, background: t.soft, border: `1px solid ${t.line}` }}>
      <span className="flex min-w-0 flex-col" style={{ gap: 3, flex: "1 1 260px" }}>
        <span style={{ ...eyebrow, color: t.c }} data-testid="pnl-exit-banner-count">{x.unseen} new exit alert{x.unseen === 1 ? "" : "s"}</span>
        {newest && <span data-testid="pnl-exit-banner-text" style={{ fontSize: 13.5, color: "var(--cp-ink)", lineHeight: 1.45, overflowWrap: "anywhere" }}>{words(newest.kind)}: {newest.text}</span>}
        {mark.isError && <span role="alert" style={{ fontSize: 12, color: "var(--cp-danger)" }}>The alerts could not be marked seen just now. Try again.</span>}
      </span>
      <button type="button" data-testid="pnl-exit-seen" disabled={mark.isPending} onClick={() => mark.mutate(undefined)}
        style={{ cursor: mark.isPending ? "wait" : "pointer", padding: "6px 12px", borderRadius: 999, border: `1px solid ${t.line}`, background: "var(--bg-1)", color: "var(--cp-ink)",
          fontFamily: MONO, fontSize: 10.5, letterSpacing: "0.08em", textTransform: "uppercase", flex: "none" }}>
        {mark.isPending ? "Marking…" : "Mark seen"}
      </button>
    </div>
  );
}

export function ExitWatchSection({ q, narrow }: { q: UseQueryResult<ExitWatch>; narrow: boolean }) {
  const [open, setOpen] = useState<string | null>(null);
  const mark = useMarkExitsSeen();
  // The route not on this server (404): the section is left out rather than shown broken.
  if (q.isError && !not404(q.error)) return null;
  const head = (n: number | null) => (
    <div className="flex flex-wrap items-center" style={{ gap: 14, padding: "18px 22px", borderBottom: "1px solid var(--cp-line)" }}>
      <div style={serifTitle}>Exit watch</div>
      {n != null && <div data-testid="pnl-exit-count" style={eyebrow}>{n} watched</div>}
      <div style={{ flex: 1 }} />
      <Chip tone="indigo">Live positions · stop loss and exit alerts</Chip>
    </div>
  );
  if (!q.data) {
    return (
      <section data-testid="pnl-exits" className="flex min-w-0 flex-col" style={{ ...card, overflow: "hidden" }}>
        {head(null)}
        <div style={{ padding: 16 }}>
          {q.isError ? <QueryProblem what="The exit watch" error={q.error} onRetry={() => void q.refetch()} /> : <LoadingBlock label="Reading the exit watch" rows={2} />}
        </div>
      </section>
    );
  }
  const x = q.data;
  const latestFor = (key: string) => x.alerts.find((a) => a.key === key) ?? null;
  const toggle = (k: string) => setOpen((o) => (o === k ? null : k));
  const ruleText = x.rule.text;
  const w = x.watcher;
  const watcherBits: string[] = [];
  if (w.enabled === false) watcherBits.push("The watcher is off on this server: the levels are shown, but no alert is raised.");
  if (w.liveRoundAt) watcherBits.push(`Last live check ${when(w.liveRoundAt)}.`);
  if (w.eodDay) watcherBits.push(`Stops last moved on the ${w.eodDay} close.`);
  if (w.feedWhy) watcherBits.push(FEED_WHY[w.feedWhy] ?? w.feedWhy);
  const troubled = x.accounts.filter((a) => a.state && a.state !== "OK" && a.state !== "OFF");
  return (
    <section data-testid="pnl-exits" className="flex min-w-0 flex-col" style={{ ...card, overflow: "hidden" }}>
      {head(x.positions.length)}
      {troubled.length > 0 && (
        <span data-testid="pnl-exit-accounts" style={{ ...quiet, padding: "10px 22px 0", color: "var(--amber)" }}>
          {troubled.map((a) => `${a.name ?? a.accountId}: ${a.state === "SIGN_IN" ? "sign in again to read its positions" : a.state === "STALE" ? "its last read is old" : "could not be read"}`).join(" · ")}.
        </span>
      )}
      {!x.positions.length ? (
        <span data-testid="pnl-exits-empty" style={{ ...quiet, padding: "16px 22px" }}>No live broker position to watch in this selection.</span>
      ) : narrow ? (
        <div data-testid="pnl-exit-cards" className="flex min-w-0 flex-col" style={{ gap: 10, padding: 12 }}>
          {x.positions.map((p) => (
            <ExitCard key={p.key} p={p} latest={latestFor(p.key)} open={open === p.key} onToggle={() => toggle(p.key)}>
              <ExitDetail p={p} ruleText={ruleText} />
            </ExitCard>
          ))}
        </div>
      ) : (
        <div data-testid="pnl-exit-table" className="cp-scroll" role="table" aria-label="Exit watch" style={{ overflowX: "auto" }}>
          <div style={{ minWidth: TABLE_MIN }}>
            <div role="row" className="grid" style={{ gridTemplateColumns: COLS, gap: 8, padding: "10px 16px", borderBottom: "1px solid var(--cp-line)" }}>
              {HEADS.map(([h, right]) => <span key={h} role="columnheader" style={{ ...eyebrow, textAlign: right ? "right" : "left" }}>{h}</span>)}
            </div>
            {x.positions.map((p) => (
              <div key={p.key} style={{ borderBottom: "1px solid var(--cp-line)" }}>
                <ExitRow p={p} latest={latestFor(p.key)} open={open === p.key} onToggle={() => toggle(p.key)} />
                {open === p.key && <ExitDetail p={p} ruleText={ruleText} />}
              </div>
            ))}
          </div>
        </div>
      )}
      <div className="flex min-w-0 flex-col" style={{ gap: 12, padding: "14px 22px 18px" }}>
        {x.notWatched.length > 0 && (
          <div data-testid="pnl-exit-notwatched" className="flex min-w-0 flex-col" style={{ gap: 3 }}>
            <span style={eyebrow}>Not watched · {x.notWatched.length}</span>
            {x.notWatched.map((n, i) => (
              <span key={i} data-testid="pnl-exit-notwatched-row" style={{ ...quiet, overflowWrap: "anywhere" }}>{n.label}{n.why ? ` — ${n.why}` : ""}</span>
            ))}
          </div>
        )}
        <div className="flex min-w-0 flex-col" style={{ gap: 8 }}>
          <div className="flex flex-wrap items-center" style={{ gap: 10 }}>
            <span data-testid="pnl-exit-alerts-head" style={eyebrow}>Exit alerts · last 7 days · {x.alerts.length}</span>
            {x.unseen > 0 && (
              <button type="button" data-testid="pnl-exit-seen-all" disabled={mark.isPending} onClick={() => mark.mutate(undefined)} style={{ ...linkBtn, fontSize: 12.5 }}>
                {mark.isPending ? "Marking…" : "Mark all seen"}
              </button>
            )}
          </div>
          <div data-testid="pnl-exit-alerts" className="flex min-w-0 flex-col" style={{ gap: 8 }}>
            {x.alerts.length ? x.alerts.map((a) => <AlertItem key={a.id} a={a} />)
              : <span data-testid="pnl-exit-alerts-none" style={quiet}>No exit alert in the last 7 days.</span>}
          </div>
        </div>
        <div data-testid="pnl-exit-watcher" className="flex min-w-0 flex-col" style={{ gap: 3, borderTop: "1px solid var(--cp-line)", paddingTop: 10 }}>
          <span style={{ fontFamily: MONO, fontSize: 11, letterSpacing: "0.06em", textTransform: "uppercase", color: "var(--cp-ink-3)", lineHeight: 1.6 }}>{WATCHER_LINE}</span>
          {watcherBits.length > 0 && <span data-testid="pnl-exit-watcher-state" style={{ ...quiet, fontSize: 11.5 }}>{watcherBits.join(" ")}</span>}
        </div>
      </div>
    </section>
  );
}
