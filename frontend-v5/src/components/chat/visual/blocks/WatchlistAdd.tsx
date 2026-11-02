/**
 * The `watchlist_add` block: a confirmation card under a screen answer (docs/plans_20261031/SCREENER_WATCHLIST_PLAN.md, slice W5).
 *
 * The chat never writes. This card shows what would be added (the stocks, how many, from which screen), and the add happens only
 * when the reader presses the button: one call from this browser with the reader's own session, the same routes the Screener page uses
 * (POST /api/watchlists, POST /api/watchlists/{id}/symbols/bulk), which check ownership, the instrument list and the 100-stock limit.
 * Seeing the card, choosing a list or reading the answer writes nothing.
 *
 * An old frontend that does not know this block shows the "not supported yet" note (VisualAnswer) and the answer still reads.
 */
import { AddToList } from "@/pages/CopilotApp/screens/screener/AddToList";
import type { WatchlistAddBlock } from "../schema";
import type { BlockProps } from "./common";

/** VisualAnswer frames every block (title and note above and below), so this draws only the card. */
export function WatchlistAddView({ b }: BlockProps<WatchlistAddBlock>) {
  return <AddToList embedded idPrefix="va-add" selected={b.symbols} matches={b.matched} query={b.screen} asOf={b.as_of ?? null} onDone={() => undefined} />;
}
