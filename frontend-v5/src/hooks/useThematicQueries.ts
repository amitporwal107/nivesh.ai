/**
 * Per-device history + favourites for thematic research queries (localStorage).
 * History logs every query fired (newest first, deduped, capped); favourites is a
 * user-curated saved set. Kept client-side for now — no backend dependency; can be
 * promoted to a server-backed store later without changing callers.
 */
import { useState, useEffect, useCallback } from "react";

const HISTORY_KEY = "nv_thematic_history";
const FAVORITES_KEY = "nv_thematic_favorites";
const HISTORY_CAP = 40;

function read(key: string): string[] {
  try {
    const v = JSON.parse(localStorage.getItem(key) || "[]");
    return Array.isArray(v) ? v.filter((x): x is string => typeof x === "string") : [];
  } catch {
    return [];
  }
}
function write(key: string, v: string[]) {
  try { localStorage.setItem(key, JSON.stringify(v)); } catch { /* quota / private mode */ }
}

export function useThematicQueries() {
  const [history, setHistory] = useState<string[]>(() => read(HISTORY_KEY));
  const [favorites, setFavorites] = useState<string[]>(() => read(FAVORITES_KEY));

  useEffect(() => write(HISTORY_KEY, history), [history]);
  useEffect(() => write(FAVORITES_KEY, favorites), [favorites]);

  const addHistory = useCallback((q: string) => {
    const t = (q || "").trim();
    if (!t) return;
    setHistory((h) => [t, ...h.filter((x) => x !== t)].slice(0, HISTORY_CAP));
  }, []);
  const removeHistory = useCallback((q: string) => {
    setHistory((h) => h.filter((x) => x !== q));
  }, []);
  const clearHistory = useCallback(() => setHistory([]), []);

  const isFavorite = useCallback((q: string) => favorites.includes((q || "").trim()), [favorites]);
  const toggleFavorite = useCallback((q: string) => {
    const t = (q || "").trim();
    if (!t) return;
    setFavorites((f) => (f.includes(t) ? f.filter((x) => x !== t) : [t, ...f]));
  }, []);

  return { history, favorites, addHistory, removeHistory, clearHistory, isFavorite, toggleFavorite };
}
