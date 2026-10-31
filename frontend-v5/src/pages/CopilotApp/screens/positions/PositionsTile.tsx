/**
 * The open-position count on the My Portfolio headline (Portfolio ledger), linking to the Open Positions workspace.
 * Reads the same GET /api/positions as the workspace (one cached read). "—" with the reason when it could not be read.
 */
import { fmtNum, type TileItem } from "../../components/ui";
import { useCopilotShell } from "../../lib/shell-context";
import { usePositions } from "./positions-data";

export function usePositionsTile(): TileItem {
  const { go } = useCopilotShell();
  const q = usePositions();
  const s = q.data?.summary;
  const flagged = s ? s.near_stop + s.stop_breached : 0;
  return {
    k: "Open positions",
    v: <span data-testid="ledger-open-positions">{s ? fmtNum(s.positions) : "—"}</span>,
    s: (
      <button type="button" data-testid="ledger-open-positions-link" onClick={() => go("page/positions")}
        style={{ background: "none", border: 0, padding: 0, color: "var(--mint)", cursor: "pointer", font: "inherit" }}>
        {q.isPending ? "Reading…" : q.isError ? "Not read · open ›" : flagged ? `${fmtNum(flagged)} near a stop · open ›` : "Broker and paper · open ›"}
      </button>
    ),
    tone: flagged ? "amber" : "ink",
  };
}
