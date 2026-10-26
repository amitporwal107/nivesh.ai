/**
 * Smart trading desk — the breadcrumb trail's rules (the user's requirement of 2026-10-25: a breadcrumb of the
 * navigation path, every step clickable). Drawn by DeskTrail.tsx, kept by TradingDesk.tsx.
 *
 * A crumb is one VIEW of the desk, named from the URL alone (crumbOf): the tab, the More view, the lab's view
 * and underlying, the chart's stock. Changing a filter or a sort keeps the same view, so it only updates that
 * crumb's saved URL; opening another view records the one left as a step. The trail is the steps taken before
 * the current view:
 *   - a main tab (the tab row, the phone's bottom bar) or "Trading desk" starts the trail again;
 *   - a crumb returns to that step's exact URL and drops the steps after it;
 *   - reaching a view already on the trail by any other link also drops everything from it on, so the trail
 *     never loops;
 *   - a link can name the part of the view it leaves from (`TrailFrom`, "Top 10 F&O ideas"), and that step then
 *     reads "AI Scanner · Top 10 F&O ideas" and scrolls back to it.
 *
 * Kept in this browser tab's sessionStorage with the view it belongs to, so a reload of the same view keeps
 * the trail and a fresh link starts clean. Storage that is blocked or holds something else is ignored.
 */
import { DESK_TAB_LABEL, LAB_VIEW_LABEL, isDeskTab, isLabView, type TrailFrom } from "./context";

export interface Crumb {
  /** The view's identity: two URLs with the same key are the same view. */
  key: string;
  label: string;
  /** The view's whole query string when it was left. */
  search: string;
  /** A data-testid on that view to scroll back to. */
  anchor?: string;
}

/** Older steps beyond this drop off the front. */
export const TRAIL_MAX = 6;

const STORE = "nv.desk.trail.v1";
const SYM = /^[A-Z0-9&-]{1,20}$/;
const symOf = (v: string | null) => {
  const s = (v ?? "").toUpperCase();
  return SYM.test(s) ? s : null;
};

const MORE_VIEW_LABEL: Record<string, string> = { strategy: "Strategy Builder", chartink: "Chartink scans", risk: "Risk controls" };

/** The view a URL shows, as a breadcrumb key and label. */
export function crumbOf(params: URLSearchParams): { key: string; label: string } {
  const tab = params.get("tab");
  if (tab === "more") {
    const view = params.get("view") ?? "";
    const label = MORE_VIEW_LABEL[view];
    if (!label) return { key: "more", label: "More" };
    const sym = view === "strategy" ? symOf(params.get("sym")) : null;
    return { key: `more:${view}:${sym ?? ""}`, label: sym ? `${label} · ${sym}` : label };
  }
  const t = isDeskTab(tab) ? tab : "overview";
  if (t === "fno") {
    const raw = params.get("lab");
    const view = isLabView(raw) ? raw : "buildup";
    const sym = symOf(params.get("lab_sym"));
    const focus = symOf(params.get("lab_focus"));
    // Candidates is a list: the stock in focus names it. The other views show one underlying.
    const which = view === "candidates" ? focus : sym;
    return { key: `fno:${view}:${sym ?? ""}:${focus ?? ""}`, label: `F&O Lab · ${LAB_VIEW_LABEL[view]}${which ? ` · ${which}` : ""}` };
  }
  if (t === "chart") {
    const sym = symOf(params.get("sym"));
    return { key: `chart:${sym ?? ""}`, label: sym ? `${DESK_TAB_LABEL.chart} · ${sym}` : DESK_TAB_LABEL.chart };
  }
  return { key: t, label: DESK_TAB_LABEL[t] };
}

/**
 * The trail after leaving `prev` for the view `hereKey`: cut back to where `hereKey` already stands on it, or
 * add `prev` (named by `from` when the link gave one), keeping the last TRAIL_MAX steps.
 */
export function nextTrail(trail: Crumb[], prev: Crumb, hereKey: string, from: TrailFrom | null): Crumb[] {
  const at = trail.findIndex((c) => c.key === hereKey);
  if (at >= 0) return trail.slice(0, at);
  const step = from ? { ...prev, label: `${prev.label} · ${from.label}`, ...(from.anchor ? { anchor: from.anchor } : {}) } : prev;
  return [...trail, step].slice(-TRAIL_MAX);
}

const isCrumb = (c: unknown): c is Crumb => {
  const o = c as Partial<Crumb> | null;
  return !!o && typeof o.key === "string" && typeof o.label === "string" && typeof o.search === "string" && (o.anchor === undefined || typeof o.anchor === "string");
};

/** The saved trail when it belongs to the view `hereKey` (a reload), else none. */
export function readTrail(hereKey: string): Crumb[] {
  try {
    const raw = window.sessionStorage.getItem(STORE);
    if (!raw) return [];
    const o = JSON.parse(raw) as { here?: unknown; trail?: unknown };
    if (o.here !== hereKey || !Array.isArray(o.trail)) return [];
    return o.trail.filter(isCrumb).slice(-TRAIL_MAX);
  } catch {
    return []; // storage blocked or corrupt: the trail starts from here
  }
}

export function writeTrail(hereKey: string, trail: Crumb[]): void {
  try {
    window.sessionStorage.setItem(STORE, JSON.stringify({ here: hereKey, trail }));
  } catch {
    /* private window / quota: the trail holds for this page only */
  }
}
