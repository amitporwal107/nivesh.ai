/**
 * The one-click way back from a 409 `risk_reduce` on a share paper trade: the universal risk policy would take the entry
 * only at a smaller size and recorded NOTHING, so this offers to submit the same trade again at the size it allows
 * ("Paper trade 59 shares instead"). The refusal itself, with the reasons, is the caller's error line (writeProblem).
 *
 * Shares only: a structure's reduce is in lots per leg, and the screens that record structures have no lot input to
 * resubmit, so they show the words alone. Renders nothing for any other error, or when the approved size is not a whole
 * number of at least one share. Accepting sends a new submission (a different body, so a new Idempotency-Key); the
 * policy judges it again. Nothing places an order.
 */
import type { CSSProperties } from "react";
import { Btn, fmtINR } from "../../components/ui";
import { riskReduceOf } from "./desk-trading";

const quiet: CSSProperties = { fontSize: 12, lineHeight: 1.5, color: "var(--cp-ink-3)" };

export function RiskReduceOffer({ error, onAccept, testId }: {
  error: unknown;
  /** Called with the approved share count; the caller resubmits its last body with that quantity. While that request
   *  is in flight the mutation is no longer in error, so this offer is gone and cannot be pressed twice. */
  onAccept: (quantity: number) => void;
  testId: string;
}) {
  const r = riskReduceOf(error);
  const qty = r?.approvedQty ?? null;
  if (qty == null || qty < 1) return null;
  const shares = `${qty.toLocaleString("en-IN")} ${qty === 1 ? "share" : "shares"}`;
  return (
    <span data-testid={testId} data-approved={qty} className="flex min-w-0 flex-wrap items-center" style={{ gap: 8 }}>
      <Btn variant="primary" data-testid={`${testId}-accept`} onClick={() => onAccept(qty)} style={{ padding: "5px 12px", fontSize: 12 }}>
        Paper trade {shares} instead
      </Btn>
      <span data-testid={`${testId}-note`} style={quiet}>
        Same entry, stop and target{r?.approvedNotionalRs != null ? `; ${fmtINR(r.approvedNotionalRs)} at the planned entry` : ""}. The risk policy checks it again. Simulated; nothing is sent to a broker.
      </span>
    </span>
  );
}
