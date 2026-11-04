/**
 * Browser alerts for the Scan dashboard's early signals (docs/scan_builder/DESIGN.md §10; owner 3 Nov evening: "in-app +
 * browser"). While the page is open and the browser allows notifications, each signal newer than the last one this browser
 * saw raises a notification — one per signal, or ONE grouped notification when more than GROUP_OVER arrive in the same
 * refresh. The first answer after the page opens only SEEDS the "seen" list (no notification), so opening the page never
 * floods. What was seen is kept in localStorage per trading day (wrapped in try/catch: private windows can refuse storage).
 * Nothing leaves the browser: notifications are local (the Notification API), no push service is involved.
 *
 * Signal strength (DESIGN.md §11, owner 4 Nov: "process only those signals where signal strength is above 70%"): with an answer
 * that carries scores, ONLY the strong signals are announced (useStrongAlerts: one per stock per day, id `strong:<day>:<SYMBOL>`,
 * kept under their own storage key); a list entry below 70 never raises a notification. useSignalAlerts (every list entry) is
 * kept for an answer from an older backend, which has no scores.
 */
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import type { DashboardSignal, StrongSignal } from "./market-dashboard-data";

export const ALERTS_KEY = "nivesh.scanDashboard.alerts.v1";
export const ALERTS_MUTED_KEY = "nivesh.scanDashboard.alerts.muted";
export const STRONG_ALERTS_KEY = "nivesh.scanDashboard.strongAlerts.v1";
export const GROUP_OVER = 3;
const MAX_IDS = 800;

export interface SeenState { day: string; last_first_seen: string | null; ids: string[] }
export type AlertPermission = "unsupported" | "default" | "granted" | "denied";
export interface AlertNote { title: string; body: string; tag: string }

const fmt2 = new Intl.NumberFormat("en-IN", { minimumFractionDigits: 2, maximumFractionDigits: 2 });
const n2 = (v: number | null | undefined): string | null => (typeof v === "number" && Number.isFinite(v) ? fmt2.format(v) : null);

export function readSeen(key: string = ALERTS_KEY): SeenState | null {
  try {
    const raw = window.localStorage.getItem(key);
    if (!raw) return null;
    const v = JSON.parse(raw) as Partial<SeenState>;
    if (typeof v?.day !== "string" || !Array.isArray(v.ids)) return null;
    return { day: v.day, last_first_seen: typeof v.last_first_seen === "string" ? v.last_first_seen : null, ids: v.ids.filter((x): x is string => typeof x === "string") };
  } catch {
    return null;
  }
}

export function writeSeen(s: SeenState, key: string = ALERTS_KEY): void {
  try {
    window.localStorage.setItem(key, JSON.stringify({ ...s, ids: s.ids.slice(-MAX_IDS) }));
  } catch {
    /* storage refused (private window, quota): alerts still work for this page view, they just are not remembered */
  }
}

/** Anything announced: an id that is stable for the day and the time it happened. */
export interface Announceable { id: string; first_seen: string }

/** The items not in `seen` (oldest first, the order they should be announced in) and the updated seen state. */
export function freshSignals<T extends Announceable>(signals: T[], seen: SeenState | null, day: string): { fresh: T[]; next: SeenState } {
  const base: SeenState = seen && seen.day === day ? seen : { day, last_first_seen: null, ids: [] };
  const known = new Set(base.ids);
  const fresh = signals.filter((s) => !known.has(s.id)).sort((a, b) => a.first_seen.localeCompare(b.first_seen));
  const ids = [...base.ids, ...fresh.map((s) => s.id)];
  const latest = [base.last_first_seen, ...signals.map((s) => s.first_seen)].filter((x): x is string => !!x).sort().pop() ?? null;
  return { fresh, next: { day, last_first_seen: latest, ids } };
}

/** "Entry 852.40 · Stop loss 838.10 · Target 1 881.00" for a signal with a plan; its note (or a plain line) otherwise. */
export function planLine(s: DashboardSignal): string {
  if (!s.plan_ok) return s.plan_note || "Signal without a plan";
  const parts = [
    n2(s.entry) ? `Entry ${n2(s.entry)}` : null,
    n2(s.stop_loss) ? `Stop loss ${n2(s.stop_loss)}` : null,
    n2(s.target_1) ? `Target 1 ${n2(s.target_1)}` : null,
  ].filter(Boolean);
  return parts.join(" · ") || "Signal";
}

/** The notifications for one refresh's new signals: one each, or a single grouped one when more than GROUP_OVER arrive. */
export function alertNotes(fresh: DashboardSignal[]): AlertNote[] {
  if (fresh.length === 0) return [];
  if (fresh.length > GROUP_OVER) {
    const syms = Array.from(new Set(fresh.map((s) => s.symbol)));
    const shown = syms.slice(0, 6).join(", ") + (syms.length > 6 ? ", …" : "");
    return [{ title: `${fresh.length} new signals: ${shown}`, body: "Scan dashboard · open it for each stock's plan", tag: `group-${fresh[fresh.length - 1].id}` }];
  }
  return fresh.map((s) => ({
    title: `${s.symbol} · ${s.widget_title || s.widget_id}${s.direction === "short" ? " (short)" : ""}`,
    body: planLine(s),
    tag: s.id,
  }));
}

/** A strong signal as an announceable item (one per stock per day). */
export interface StrongItem extends Announceable { s: StrongSignal }
export const strongItems = (strong: StrongSignal[], day: string): StrongItem[] =>
  strong.map((s) => ({ id: `strong:${day}:${s.symbol}`, first_seen: s.first_strong, s }));

/** "Entry 614.80 · Stop loss 576.82 · Target 1 690.76" for a strong signal with a plan; its note otherwise. */
export function strongPlanLine(s: StrongSignal): string {
  if (!s.plan_ok) return s.plan_note || "Strong signal without a plan";
  const parts = [
    n2(s.entry) ? `Entry ${n2(s.entry)}` : null,
    n2(s.stop_loss) ? `Stop loss ${n2(s.stop_loss)}` : null,
    n2(s.target_1) ? `Target 1 ${n2(s.target_1)}` : null,
  ].filter(Boolean);
  return parts.join(" · ") || "Strong signal";
}

/** The notifications for one refresh's new strong signals: one each, or one grouped when more than GROUP_OVER arrive. */
export function strongNotes(fresh: StrongItem[]): AlertNote[] {
  if (fresh.length === 0) return [];
  if (fresh.length > GROUP_OVER) {
    const syms = fresh.map((x) => x.s.symbol);
    const shown = syms.slice(0, 6).join(", ") + (syms.length > 6 ? ", …" : "");
    return [{ title: `${fresh.length} strong signals: ${shown}`, body: "Scan dashboard · open it for each stock's score and plan", tag: `group-${fresh[fresh.length - 1].id}` }];
  }
  return fresh.map(({ id, s }) => ({
    title: `${s.symbol} · strong signal${typeof s.score_at === "number" ? ` ${Math.round(s.score_at)}/100` : ""}`,
    body: strongPlanLine(s),
    tag: id,
  }));
}

function currentPermission(): AlertPermission {
  if (typeof window === "undefined" || !("Notification" in window)) return "unsupported";
  const p = window.Notification.permission;
  return p === "granted" || p === "denied" ? p : "default";
}

function readMuted(): boolean {
  try {
    return window.localStorage.getItem(ALERTS_MUTED_KEY) === "1";
  } catch {
    return false;
  }
}

/**
 * Tracks `items` across refreshes: seeds on the first answer, then raises notifications for new ones (when allowed and not
 * paused), built by `notesFor`. Returns the permission state and the controls the panel shows. The pause is shared by both
 * kinds (one switch on the page); what was seen is kept per `storageKey`.
 */
function useAlerts<T extends Announceable>(items: T[] | null | undefined, day: string, notesFor: (fresh: T[]) => AlertNote[], storageKey: string) {
  const [permission, setPermission] = useState<AlertPermission>(currentPermission);
  const [muted, setMuted] = useState<boolean>(readMuted);
  const [sent, setSent] = useState(0);
  const seeded = useRef(false);
  const live = useRef({ permission, muted });
  live.current = { permission, muted };

  useEffect(() => {
    if (!items) return;
    const { fresh, next } = freshSignals(items, seeded.current ? readSeen(storageKey) : null, day);
    writeSeen(next, storageKey);
    if (!seeded.current) {                       // the first answer of this page view: remember, never announce
      seeded.current = true;
      return;
    }
    const { permission: p, muted: m } = live.current;
    if (p !== "granted" || m || fresh.length === 0) return;
    let n = 0;
    for (const note of notesFor(fresh)) {
      try {
        const shown = new window.Notification(note.title, { body: note.body, tag: note.tag });   // shown on construction
        if (shown) n += 1;
      } catch {
        /* a browser can refuse a notification even with permission (e.g. some mobile browsers need a service worker) */
      }
    }
    if (n) setSent((v) => v + n);
  }, [items, day, notesFor, storageKey]);

  const enable = useCallback(async () => {
    if (currentPermission() === "unsupported") return;
    try {
      const p = await window.Notification.requestPermission();
      setPermission(p === "granted" || p === "denied" ? p : "default");
    } catch {
      setPermission(currentPermission());
    }
    setMuted(false);
    try { window.localStorage.removeItem(ALERTS_MUTED_KEY); } catch { /* not remembered; fine */ }
  }, []);

  const toggleMuted = useCallback(() => {
    setMuted((m) => {
      const v = !m;
      try {
        if (v) window.localStorage.setItem(ALERTS_MUTED_KEY, "1"); else window.localStorage.removeItem(ALERTS_MUTED_KEY);
      } catch { /* not remembered; fine */ }
      return v;
    });
  }, []);

  return { permission, muted, sent, enable, toggleMuted };
}

/** Every list entry (an answer from an older backend, without scores; DESIGN.md §10). */
export function useSignalAlerts(signals: DashboardSignal[] | null | undefined, day: string) {
  return useAlerts(signals, day, alertNotes, ALERTS_KEY);
}

/** Only the strong signals (score ≥ 70; DESIGN.md §11): never a list entry below 70. */
export function useStrongAlerts(strong: StrongSignal[] | null | undefined, day: string) {
  const items = useMemo(() => (strong ? strongItems(strong, day) : null), [strong, day]);
  return useAlerts(items, day, strongNotes, STRONG_ALERTS_KEY);
}
