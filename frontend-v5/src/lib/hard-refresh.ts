/**
 * hard-refresh — wipes all client-side caches and reloads the page.
 *
 * Called by:
 *   - BuildUpdateBanner "Refresh now" button
 *   - Alt+U keyboard shortcut
 *   - Ctrl/Cmd+Shift+R still works natively in the browser (no override needed)
 *
 * What it clears:
 *   1. Service Worker caches (Cache Storage API)
 *   2. Any registered Service Workers (so they re-register on next load)
 *   3. React Query in-memory cache (if queryClient is passed)
 *   4. sessionStorage (tab-scoped feature-flag overrides etc.)
 *   Then: hard reload via location.reload()
 */

export async function hardRefresh(queryClient?: { clear(): void }): Promise<void> {
  // 1. Wipe all Cache Storage caches (used by any SW or workbox setup)
  if ("caches" in window) {
    const keys = await caches.keys().catch(() => [] as string[]);
    await Promise.all(keys.map(k => caches.delete(k).catch(() => false)));
  }

  // 2. Unregister any active Service Workers so the next load re-registers fresh
  if ("serviceWorker" in navigator) {
    const regs = await navigator.serviceWorker.getRegistrations().catch(() => []);
    await Promise.all(regs.map(r => r.unregister().catch(() => false)));
  }

  // 3. Clear React Query in-memory cache
  queryClient?.clear();

  // 4. Clear sessionStorage (localStorage intentionally kept — has auth tokens)
  try { sessionStorage.clear(); } catch { /* sandboxed */ }

  // 5. Hard reload — bypasses disk cache (same as Ctrl+Shift+R)
  window.location.reload();
}
