/**
 * Per-USER history + favourites for thematic research queries, server-backed
 * (Mongo via /api/thematic/*). Follows the user across devices. Optimistic local
 * updates keep the UI snappy; the server response reconciles. If the API is
 * unreachable the local optimistic state still works for the session.
 */
import { useState, useEffect, useCallback } from "react";
import { apiFetch } from "@/services/api/authed-fetch";

const CAP = 40;
type Prefs = { history: string[]; favorites: string[] };

async function post(path: string, body: object): Promise<Prefs | null> {
  try {
    const r = await apiFetch(path, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    });
    if (!r.ok) return null;
    return (await r.json()) as Prefs;
  } catch {
    return null;
  }
}

export function useThematicQueries() {
  const [history, setHistory] = useState<string[]>([]);
  const [favorites, setFavorites] = useState<string[]>([]);

  useEffect(() => {
    let alive = true;
    (async () => {
      try {
        const r = await apiFetch("/api/thematic/prefs");
        if (!r.ok) return;
        const d = (await r.json()) as Prefs;
        if (alive) {
          setHistory(Array.isArray(d.history) ? d.history : []);
          setFavorites(Array.isArray(d.favorites) ? d.favorites : []);
        }
      } catch {
        /* not signed in / offline — keep session-local state */
      }
    })();
    return () => { alive = false; };
  }, []);

  const addHistory = useCallback((q: string) => {
    const t = (q || "").trim();
    if (!t) return;
    setHistory((h) => [t, ...h.filter((x) => x !== t)].slice(0, CAP)); // optimistic
    post("/api/thematic/history", { query: t }).then((d) => {
      if (d) { setHistory(d.history); setFavorites(d.favorites); }
    });
  }, []);

  const removeHistory = useCallback((q: string) => {
    setHistory((h) => h.filter((x) => x !== q));
    post("/api/thematic/history/remove", { query: q }).then((d) => { if (d) setHistory(d.history); });
  }, []);

  const clearHistory = useCallback(() => {
    setHistory([]);
    post("/api/thematic/history/remove", { clear: true });
  }, []);

  const isFavorite = useCallback((q: string) => favorites.includes((q || "").trim()), [favorites]);

  const toggleFavorite = useCallback((q: string) => {
    const t = (q || "").trim();
    if (!t) return;
    setFavorites((f) => (f.includes(t) ? f.filter((x) => x !== t) : [t, ...f])); // optimistic
    post("/api/thematic/favorites/toggle", { query: t }).then((d) => { if (d) setFavorites(d.favorites); });
  }, []);

  return { history, favorites, addHistory, removeHistory, clearHistory, isFavorite, toggleFavorite };
}
