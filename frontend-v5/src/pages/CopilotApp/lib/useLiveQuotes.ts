/**
 * One shared live-quote connection for the whole Copilot app.
 *
 *   const { quotes, meta } = useLiveQuotes(["RELIANCE", "NIFTY 50"]);   // subscribe while mounted
 *   const q = useLiveOverlay("RELIANCE");                               // the quote, only while the feed is LIVE
 *   const meta = useLiveMeta();                                         // mode / age for the shell chip
 *
 * Source: the backend's platform-level Kite feed (read-only). GET /api/live/stream is a server-sent-events stream that
 * pushes a `snapshot` event every server cadence (30 s by default). There is exactly ONE connection for every screen: components subscribe to
 * symbols, the store dedupes them (reference-counted) and asks for their union. If the stream cannot be used (the browser
 * has no EventSource, the session is a bearer-token WebView, the proxy buffers it, or it keeps failing) the store falls back
 * to polling GET /api/live/quotes at the server's cadence. It pauses while the tab is hidden, and while the market is closed or the
 * feed is not connected it only checks the status once a minute. Nothing here ever writes anything.
 *
 * A quote the feed did not have is simply absent: a price is a number or null, never 0.
 */
import { useEffect, useMemo, useSyncExternalStore } from "react";
import { http } from "@/services/api/http";
import { apiConfig } from "@/services/api/config";

export type LiveMode = "live" | "delayed" | "closed" | "expired" | "not_connected" | "disabled" | "unknown";

export interface LiveQuote {
  ltp: number;
  change: number | null;
  changePct: number | null;
  open: number | null;
  high: number | null;
  low: number | null;
  /** Previous close (Kite's ohlc.close). */
  close: number | null;
  volume: number | null;
  oi: number | null;
  ts: string | null;
}

export interface LiveMeta {
  mode: LiveMode;
  source: string | null;
  session: string | null;
  /** The server's publish time. */
  asOf: string | null;
  /** When the newest quote in the snapshot was taken (server). */
  dataAt: string | null;
  /** Seconds between the newest data and the server's answer (server clock). */
  ageSeconds: number | null;
  stale: boolean;
  /** The server's publish interval in seconds; polling follows it. */
  cadenceSeconds: number;
  final: boolean;
  /** performance.now()-style browser time of the last answer, for "updated Ns ago". */
  receivedAt: number | null;
  transport: "sse" | "poll" | "idle";
}

const DEFAULT_CADENCE_S = 30;       // until the server says otherwise (its `cadence_seconds`, KITE_LIVE_FEED_CADENCE_SECONDS)
const IDLE_MS = 60_000;
const SSE_MAX_SYMBOLS = 300;
const SSE_FAILS_BEFORE_POLL = 2;
// The same spellings the backend folds (services/kite_live_feed/gateway.py): NSE's names for the sector indices differ from Kite's.
const ALIASES: Record<string, string> = {
  "NIFTY FINANCIAL SERVICES": "NIFTY FIN SERVICE", "NIFTY CONSUMER DURABLES": "NIFTY CONSR DURBL", "NIFTY SERVICES SECTOR": "NIFTY SERV SECTOR",
  "NIFTY PRIVATE BANK": "NIFTY PVT BANK", "NIFTY MIDCAP SELECT": "NIFTY MID SELECT", "NIFTY OIL & GAS": "NIFTY OIL AND GAS", "NIFTY NEXT50": "NIFTY NEXT 50",
};
const norm = (s: string) => {
  const t = s.trim().toUpperCase().replace(/^NSE:/, "").replace(/\s+/g, " ");
  return ALIASES[t] ?? t;
};

const EMPTY_META: LiveMeta = { mode: "unknown", source: null, session: null, asOf: null, dataAt: null, ageSeconds: null, stale: true, cadenceSeconds: DEFAULT_CADENCE_S, final: false, receivedAt: null, transport: "idle" };

const num = (v: unknown): number | null => (typeof v === "number" && Number.isFinite(v) ? v : null);
const str = (v: unknown): string | null => (typeof v === "string" && v ? v : null);
const MODES: LiveMode[] = ["live", "delayed", "closed", "expired", "not_connected", "disabled"];

/** Parse a /quotes, /snapshot or stream body. Anything malformed is "no data", never a crash. */
export function parsePayload(body: unknown, receivedAt: number): { quotes: Record<string, LiveQuote>; meta: LiveMeta } | null {
  if (!body || typeof body !== "object") return null;
  const b = body as Record<string, unknown>;
  const raw = b.quotes;
  if (!raw || typeof raw !== "object" || Array.isArray(raw)) return null;
  const quotes: Record<string, LiveQuote> = {};
  for (const [sym, v] of Object.entries(raw as Record<string, unknown>)) {
    if (!v || typeof v !== "object") continue;
    const r = v as Record<string, unknown>;
    const ltp = num(r.ltp);
    if (ltp == null || ltp <= 0) continue;
    quotes[norm(sym)] = {
      ltp, change: num(r.change), changePct: num(r.change_pct), open: num(r.open), high: num(r.high), low: num(r.low),
      close: num(r.close), volume: num(r.volume), oi: num(r.oi), ts: str(r.ts),
    };
  }
  const m = MODES.find((x) => x === b.mode) ?? "unknown";
  return {
    quotes,
    meta: { mode: m, source: str(b.source), session: str(b.session), asOf: str(b.as_of), dataAt: str(b.data_at), ageSeconds: num(b.age_seconds), stale: b.stale !== false, cadenceSeconds: Math.min(120, Math.max(2, num(b.cadence_seconds) ?? DEFAULT_CADENCE_S)), final: b.final === true, receivedAt, transport: "idle" },
  };
}

class LiveStore {
  private refs = new Map<string, number>();
  private listeners = new Set<() => void>();
  private quotes: Record<string, LiveQuote> = {};
  private meta: LiveMeta = EMPTY_META;
  private version = 0;
  private es: EventSource | null = null;
  private timer: ReturnType<typeof setTimeout> | null = null;
  private reconnect: ReturnType<typeof setTimeout> | null = null;
  private sseFails = 0;
  private usePoll = false;
  private sseKey = "";
  private inflight: AbortController | null = null;
  private started = false;

  // ── React plumbing
  subscribe = (fn: () => void) => { this.listeners.add(fn); return () => { this.listeners.delete(fn); }; };
  getVersion = () => this.version;
  getQuotes = () => this.quotes;
  getMeta = () => this.meta;
  subscriberCount = () => this.refs.size;
  private emit() { this.version++; this.listeners.forEach((l) => l()); }

  /** Reference-counted: two screens asking for RELIANCE cost one symbol in the request. */
  watch(symbols: string[]): () => void {
    const syms = Array.from(new Set(symbols.map(norm).filter(Boolean)));
    for (const s of syms) this.refs.set(s, (this.refs.get(s) ?? 0) + 1);
    this.ensureStarted();
    this.scheduleReconnect();
    return () => {
      for (const s of syms) {
        const n = (this.refs.get(s) ?? 1) - 1;
        if (n <= 0) this.refs.delete(s); else this.refs.set(s, n);
      }
      if (this.refs.size === 0) this.stopAll(); else this.scheduleReconnect();
    };
  }

  private ensureStarted() {
    if (this.started || typeof document === "undefined") return;
    this.started = true;
    document.addEventListener("visibilitychange", this.onVisibility);
  }

  private onVisibility = () => {
    if (document.hidden) { this.closeStream(); this.clearTimer(); this.setTransport("idle"); } else if (this.refs.size) this.connect();
  };

  private setTransport(t: LiveMeta["transport"]) { if (this.meta.transport !== t) { this.meta = { ...this.meta, transport: t }; this.emit(); } }
  private clearTimer() { if (this.timer) { clearTimeout(this.timer); this.timer = null; } }
  private closeStream() { if (this.es) { this.es.close(); this.es = null; this.sseKey = ""; } this.inflight?.abort(); this.inflight = null; }

  private stopAll() {
    this.closeStream(); this.clearTimer();
    if (this.reconnect) { clearTimeout(this.reconnect); this.reconnect = null; }
    if (this.started && typeof document !== "undefined") document.removeEventListener("visibilitychange", this.onVisibility);
    this.started = false; this.setTransport("idle");
  }

  /** Coalesce a burst of mounts into one (re)connection. */
  private scheduleReconnect() {
    if (this.reconnect) clearTimeout(this.reconnect);
    this.reconnect = setTimeout(() => { this.reconnect = null; if (this.refs.size && !(typeof document !== "undefined" && document.hidden)) this.connect(); }, 150);
  }

  private query(): { symbols?: string; universe?: string } {
    const syms = Array.from(this.refs.keys()).sort();
    if (syms.length > SSE_MAX_SYMBOLS) return { universe: "all" };
    return { symbols: syms.join(",") };
  }

  private connect() {
    this.clearTimer();
    const idle = this.meta.mode === "closed" || this.meta.mode === "not_connected" || this.meta.mode === "expired" || this.meta.mode === "disabled";
    if (!idle && !this.usePoll && typeof EventSource !== "undefined") { this.openStream(); return; }
    this.closeStream();
    void this.poll();
  }

  private openStream() {
    const q = this.query();
    const key = q.symbols ?? `u:${q.universe}`;
    if (this.es && this.sseKey === key) return;
    this.closeStream();
    const qs = new URLSearchParams(q.symbols ? { symbols: q.symbols } : { universe: q.universe ?? "all" });
    try {
      const es = new EventSource(`${apiConfig.baseUrl}/api/live/stream?${qs.toString()}`, { withCredentials: true });
      this.es = es; this.sseKey = key;
      es.addEventListener("snapshot", (ev) => {
        this.sseFails = 0;
        try { this.apply(JSON.parse((ev as MessageEvent).data), "sse"); } catch { /* a malformed event is skipped */ }
      });
      es.onerror = () => {
        this.sseFails++;
        // readyState CLOSED = the browser gave up for good (a non-200 answer or the wrong content type): poll at once.
        if (es.readyState === 2 || this.sseFails >= SSE_FAILS_BEFORE_POLL) { this.usePoll = true; this.closeStream(); void this.poll(); setTimeout(() => { this.usePoll = false; this.sseFails = 0; }, 5 * 60_000); }
      };
    } catch { this.usePoll = true; void this.poll(); }
  }

  private async poll() {
    if (!this.refs.size) return;
    this.setTransport("poll");
    const q = this.query();
    this.inflight?.abort();
    const ctl = (this.inflight = new AbortController());
    try {
      const res = q.symbols
        ? await http({ path: "/api/live/quotes", query: { symbols: q.symbols }, signal: ctl.signal, noRetry: true, timeoutMs: 8_000 })
        : await http({ path: "/api/live/snapshot", query: { universe: q.universe ?? "all" }, signal: ctl.signal, noRetry: true, timeoutMs: 8_000 });
      this.apply(res.data, "poll");
    } catch (e) {
      if (ctl.signal.aborted) return;
      this.markDown();
    }
    if (!this.refs.size || ctl.signal.aborted) return;
    const idle = this.meta.mode === "closed" || this.meta.mode === "not_connected" || this.meta.mode === "expired" || this.meta.mode === "disabled";
    this.timer = setTimeout(() => this.connect(), idle ? IDLE_MS : Math.max(5_000, this.meta.cadenceSeconds * 1000));
  }

  private markDown() {
    this.meta = { ...this.meta, mode: this.meta.mode === "closed" ? "closed" : "not_connected", stale: true, receivedAt: this.meta.receivedAt };
    this.emit();
  }

  private apply(body: unknown, transport: "sse" | "poll") {
    const parsed = parsePayload(body, Date.now());
    if (!parsed) { this.markDown(); return; }
    this.quotes = { ...this.quotes, ...parsed.quotes };
    this.meta = { ...parsed.meta, transport };
    this.emit();
    // The market closed or the feed dropped: stop the stream, check the status once a minute.
    if (transport === "sse" && (["closed", "not_connected", "expired", "disabled"] as LiveMode[]).includes(parsed.meta.mode)) {
      this.closeStream();
      this.timer = setTimeout(() => this.connect(), IDLE_MS);
    }
  }
}

export const liveStore = new LiveStore();

/** Subscribe to `symbols` while the component is mounted; re-renders on each new snapshot. */
export function useLiveQuotes(symbols: string[]): { quotes: Record<string, LiveQuote>; meta: LiveMeta } {
  const key = symbols.map(norm).filter(Boolean).sort().join(",");
  useEffect(() => (key ? liveStore.watch(key.split(",")) : undefined), [key]);
  useSyncExternalStore(liveStore.subscribe, liveStore.getVersion, liveStore.getVersion);
  return { quotes: liveStore.getQuotes(), meta: liveStore.getMeta() };
}

/** The shell chip's read: no subscription of its own. */
export function useLiveMeta(): LiveMeta {
  useSyncExternalStore(liveStore.subscribe, liveStore.getVersion, liveStore.getVersion);
  return liveStore.getMeta();
}

/** A quote handed to a screen: `kind` says whether it is a LIVE tick or the final snapshot after the close ("close"). */
export type OverlayQuote = LiveQuote & { kind: "live" | "close" };

const istDayOf = (iso: string | null): string | null => {
  const t = iso ? Date.parse(iso) : NaN;
  return Number.isFinite(t) ? new Date(t + 5.5 * 3600_000).toISOString().slice(0, 10) : null;
};

/**
 * What a price cell may show from the feed. While LIVE: the quote. After the close, once the feed has published its FINAL
 * snapshot: the quote too, but only when it is from a session newer than the screen's own end-of-day day (`eodDay`, a
 * YYYY-MM-DD) -- so "today's close" shows before the end-of-day ingest lands, labelled "close". Never when delayed / expired / not connected.
 */
function pick(q: LiveQuote | undefined, meta: LiveMeta, eodDay: string | null | undefined): OverlayQuote | null {
  if (!q) return null;
  if (meta.mode === "live") return { ...q, kind: "live" };
  if (meta.mode === "closed" && meta.final && eodDay) {
    // The final snapshot of the most recent session, and newer than the screen's own end-of-day day. Compared by date; once the
    // warehouse's bar for that day lands, `eodDay` catches up and this returns null (the end-of-day data takes over).
    const qDay = istDayOf(q.ts);
    if (qDay && qDay > eodDay && qDay === istDayOf(meta.dataAt)) return { ...q, kind: "close" };
  }
  return null;
}

/** "Close · 21 Oct · Kite": how a closing-snapshot price is labelled (never "live"). */
export function closeLabel(q: { ts: string | null }): string {
  const d = q.ts ? new Date(q.ts.slice(0, 10) + "T00:00:00Z") : null;
  const day = d && Number.isFinite(d.getTime()) ? d.toLocaleDateString("en-GB", { day: "numeric", month: "short", timeZone: "UTC" }) : "latest session";
  return `Close · ${day} · Kite`;
}

/** The Flash value for a quote: ticks flash, a closing snapshot never does. */
export const flashOf = (q: OverlayQuote | null | undefined): number | undefined => (q && q.kind === "live" ? q.ltp : undefined);

/** The overlay quote for one symbol, or null (see `pick`). */
export function useLiveOverlay(symbol: string | null | undefined, eodDay?: string | null): OverlayQuote | null {
  const sym = symbol ? norm(symbol) : "";
  const { quotes, meta } = useLiveQuotes(sym ? [sym] : []);
  return sym ? pick(quotes[sym], meta, eodDay) : null;
}

/** Many symbols at once (a table): one subscription. */
export function useLiveOverlays(symbols: string[], eodDay?: string | null): { get: (symbol: string) => OverlayQuote | null; live: boolean } {
  const { quotes, meta } = useLiveQuotes(symbols);
  const live = meta.mode === "live";
  return useMemo(() => ({ live, get: (s: string) => pick(quotes[norm(s)], meta, eodDay) }), [live, quotes, meta, eodDay]);
}
