/**
 * Client 360 in the shell (view "advisor/client-360").
 *
 * This used to mount the original page (pages/Client360) unchanged. That page
 * cannot be told which client to show, sends "Open full portfolio" and "Plan
 * board" to the original app's /dashboard and /plan, and prints "Nothing
 * flagged right now" when its needs-attention request fails. None of that can
 * be changed from outside the page, so the shell has its own build on the same
 * hooks and derivations: screens/advisor/Client360.
 *
 * The registry still imports this file, so the view path and the screen's test
 * id (screen-advisor-client-360) are unchanged.
 */
export { default } from "../advisor/Client360";
