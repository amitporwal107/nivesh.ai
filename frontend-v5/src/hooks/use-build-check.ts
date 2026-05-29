/**
 * use-build-check — detects when a newer frontend build is deployed.
 *
 * Strategy:
 *   - On mount, read the hashed JS bundle URL that is currently loaded in
 *     this tab (from the <script> tag in the live DOM).
 *   - Every POLL_INTERVAL ms, fetch /v5/ (index.html, always no-cache per
 *     nginx config) and extract the hashed asset URL from its <script> tag.
 *   - If the URL differs → a new build has been deployed → set updateAvailable.
 *
 * This requires zero build config changes: Vite's content-hash filenames
 * (e.g. index-DVqBS3bV.js) are unique per build, so any difference means
 * the server is serving a newer bundle.
 */

import { useState, useEffect, useRef, useCallback } from "react";

const POLL_INTERVAL_MS = 2 * 60 * 1_000; // check every 2 minutes
const INDEX_URL = "/v5/";

// Regex to extract the hashed JS bundle path from index.html
const ASSET_RE = /src="(\/v5\/assets\/index-[^"]+\.js)"/;

/** Return the hashed JS URL loaded in this tab, or null if not detectable. */
function getCurrentBundleUrl(): string | null {
  const scripts = document.querySelectorAll<HTMLScriptElement>('script[type="module"][src]');
  for (const s of scripts) {
    if (s.src.includes("/v5/assets/index-")) return s.src;
  }
  // Fallback: check all scripts for the pattern
  for (const s of document.querySelectorAll<HTMLScriptElement>("script[src]")) {
    if (/\/v5\/assets\/index-/.test(s.src)) return s.src;
  }
  return null;
}

/** Fetch latest index.html and extract the hashed JS bundle path. */
async function fetchLatestBundleUrl(): Promise<string | null> {
  try {
    const res = await fetch(INDEX_URL, {
      cache: "no-store",
      headers: { "Cache-Control": "no-cache" },
    });
    if (!res.ok) return null;
    const html = await res.text();
    const match = ASSET_RE.exec(html);
    return match ? match[1] : null;
  } catch {
    return null;
  }
}

export interface BuildCheckState {
  updateAvailable: boolean;
  currentUrl: string | null;
  latestUrl: string | null;
  /** Call to dismiss the banner without refreshing */
  dismiss: () => void;
  /** Milliseconds since last check */
  lastCheckedAt: number | null;
}

export function useBuildCheck(): BuildCheckState {
  const [updateAvailable, setUpdateAvailable] = useState(false);
  const [dismissed, setDismissed] = useState(false);
  const [currentUrl] = useState<string | null>(() => getCurrentBundleUrl());
  const [latestUrl, setLatestUrl] = useState<string | null>(null);
  const [lastCheckedAt, setLastCheckedAt] = useState<number | null>(null);
  const timerRef = useRef<ReturnType<typeof setInterval> | null>(null);

  const check = useCallback(async () => {
    if (!currentUrl) return; // Can't compare without a baseline
    const latest = await fetchLatestBundleUrl();
    setLastCheckedAt(Date.now());
    if (!latest) return;
    setLatestUrl(latest);
    // Compare just the filename (strip origin so localhost vs CDN doesn't matter)
    const currentFile = currentUrl.split("/").pop();
    const latestFile = latest.split("/").pop();
    if (latestFile && currentFile && latestFile !== currentFile) {
      setUpdateAvailable(true);
    }
  }, [currentUrl]);

  useEffect(() => {
    // Initial check after 30s (don't blast on mount)
    const initial = setTimeout(check, 30_000);
    // Recurring poll
    timerRef.current = setInterval(check, POLL_INTERVAL_MS);
    return () => {
      clearTimeout(initial);
      if (timerRef.current) clearInterval(timerRef.current);
    };
  }, [check]);

  // Re-check on tab becoming visible (user returns from another tab)
  useEffect(() => {
    function onVisible() {
      if (document.visibilityState === "visible") check();
    }
    document.addEventListener("visibilitychange", onVisible);
    return () => document.removeEventListener("visibilitychange", onVisible);
  }, [check]);

  return {
    updateAvailable: updateAvailable && !dismissed,
    currentUrl,
    latestUrl,
    dismiss: () => setDismissed(true),
    lastCheckedAt,
  };
}
