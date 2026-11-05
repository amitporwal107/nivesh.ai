/**
 * Paper Trading v2 — the "02 Scanner opportunities" chip's badge (UI_DESIGN_V2.md §1): a mono amber count of the caller's
 * proposals awaiting approval, live from GET /api/v1/proposals?state=AWAITING_USER_APPROVAL; hidden at 0, while loading
 * and when the read fails (the view itself says why). Drawn by TradingDesk.tsx's sub-view switcher, in its own chunk.
 */
import { useAwaitingCount } from "./api-a";

export default function PaperOppsBadge({ on }: { on: boolean }) {
  const q = useAwaitingCount();
  const n = q.data?.count ?? 0;
  if (!n) return null;
  return (
    <span data-testid="desk-sub-opportunities-badge" aria-label={`${n} awaiting your approval`}
      style={{ marginLeft: 7, padding: "1px 6px", borderRadius: 999, fontFamily: "var(--mono)", fontSize: 10, fontVariantNumeric: "tabular-nums",
        color: "var(--amber)", background: on ? "var(--bg-0)" : "var(--amber-soft)", border: "1px solid var(--amber-line)" }}>
      {n}{q.data?.capped ? "+" : ""}
    </span>
  );
}
