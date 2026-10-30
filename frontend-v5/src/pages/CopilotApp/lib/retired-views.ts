/**
 * Retired views: the screens the desk redesign's step 6 removed (2026-10-27; docs/desk_redesign_20261027/PLAN.md §4,
 * the owner's scope A, "trading duplicates only"). Each old URL opens its new home in the Smart trading desk, never a
 * blank page or the app home:
 *
 *   trader                  the old Trader landing           → the desk (Market Overview)
 *   tool/optlab             the Options lab                  → Market Desk › Smart Money, F&O section
 *   tool/fnolab?screen=mi   the F&O lab (its default screen) → Market Desk › Smart Money
 *              prog · replay · shadow                       → Trade Desk › Chart Analysis (Strategy Lab, their home until
 *                                                              29 Oct, was removed)
 *              live · cert                                  → Risk Desk › Policy & runtime (live readiness)
 *              audit                                        → Risk Desk › Decision log
 *
 * The rest of the old query string is kept: the backend's Kite login returns to /v5/app/trader?kite=connected
 * (backend/services/kite_live_feed/platform_token.py, KITE_LOGIN_RETURN_PATH), which the shell's KiteLoginNotice reads.
 * index.tsx applies this before it looks the view up in the screen registry, in every mode.
 */
const DESK = "trader/desk";

/** The F&O lab's `?screen=` → its desk place. A missing or unknown screen is the lab's own default, `mi`. */
const FNOLAB_PLACE: Record<string, string> = {
  mi: "tab=market&view=smartmoney",
  prog: "tab=trade&view=chart&sub=live",
  replay: "tab=trade&view=chart&sub=live",
  shadow: "tab=trade&view=chart&sub=live",
  live: "tab=risk&view=controls",
  cert: "tab=risk&view=controls",
  audit: "tab=risk&view=log",
};

/** The view (below the app base, with its query) a retired view opens now, or null when the view is not retired. */
export function retiredViewRedirect(view: string, search: string): string | null {
  const old = new URLSearchParams(search);
  let place: string;
  switch (view) {
    case "trader":
      place = "";
      break;
    case "tool/optlab":
      place = "tab=market&view=smartmoney&section=fno";
      break;
    case "tool/fnolab":
      place = FNOLAB_PLACE[old.get("screen") ?? ""] ?? FNOLAB_PLACE.mi;
      old.delete("screen");
      break;
    default:
      return null;
  }
  const next = new URLSearchParams(place);
  old.forEach((v, k) => {
    if (!next.has(k)) next.append(k, v);
  });
  const q = next.toString();
  return q ? `${DESK}?${q}` : DESK;
}
