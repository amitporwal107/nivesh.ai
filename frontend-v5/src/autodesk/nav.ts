/** The desk's twelve screens, grouped and numbered as in the prototype's sidebar (Desk / Positions / Control). */

export type ScreenId =
  | "overview" | "agents" | "scanner" | "workbench" | "approvals"
  | "trades" | "pnl" | "risk"
  | "middle" | "sim" | "fleet" | "policies";

export interface ScreenDef {
  id: ScreenId;
  label: string;
  path: string;          // under the router basename /autodesk
  group: "Desk" | "Positions" | "Control";
  /** 1 = the screen shows its data today; 2 = the desk records the data (paper orders, fills, positions, P&L) but the screen does not show it yet, or is not built. */
  phase: 1 | 2;
}

export const SCREENS: ScreenDef[] = [
  { id: "overview", label: "Desk overview", path: "/", group: "Desk", phase: 1 },
  { id: "agents", label: "Agent command centre", path: "/agents", group: "Desk", phase: 1 },
  { id: "scanner", label: "Opportunity scanner", path: "/scanner", group: "Desk", phase: 1 },
  { id: "workbench", label: "Strategy workbench", path: "/workbench", group: "Desk", phase: 2 },
  { id: "approvals", label: "Approval queue", path: "/approvals", group: "Desk", phase: 1 },
  { id: "trades", label: "Active trades", path: "/trades", group: "Positions", phase: 2 },
  { id: "pnl", label: "Real-time P&L", path: "/pnl", group: "Positions", phase: 2 },
  { id: "risk", label: "Capital & risk", path: "/risk", group: "Positions", phase: 2 },
  { id: "middle", label: "Middle office", path: "/middle", group: "Control", phase: 2 },
  { id: "sim", label: "Simulator", path: "/simulator", group: "Control", phase: 1 },
  { id: "fleet", label: "Agent fleet & reliability", path: "/fleet", group: "Control", phase: 2 },
  { id: "policies", label: "Policies & permissions", path: "/policies", group: "Control", phase: 1 },
];

export const GROUPS = ["Desk", "Positions", "Control"] as const;

export const screenById = (id: ScreenId): ScreenDef => SCREENS.find((s) => s.id === id)!;

/** Screen number as the sidebar shows it ("01" … "12"). */
export const screenNo = (id: ScreenId): string => String(SCREENS.findIndex((s) => s.id === id) + 1).padStart(2, "0");

export function screenForPath(pathname: string): ScreenDef {
  const p = pathname.replace(/\/+$/, "") || "/";
  return SCREENS.find((s) => (s.path === "/" ? p === "/" : p === s.path || p.startsWith(`${s.path}/`))) ?? SCREENS[0];
}

/** Phone bottom bar: Desk / Trades / Approve / P&L / More (the rest open from the More sheet). */
export const TABS: { id: ScreenId | "more"; label: string; glyph: string }[] = [
  { id: "overview", label: "Desk", glyph: "◐" },
  { id: "trades", label: "Trades", glyph: "≡" },
  { id: "approvals", label: "Approve", glyph: "✓" },
  { id: "pnl", label: "P&L", glyph: "↗" },
  { id: "more", label: "More", glyph: "＋" },
];
