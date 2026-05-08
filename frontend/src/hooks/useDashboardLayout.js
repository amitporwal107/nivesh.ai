import { useState, useCallback } from "react";

const STORAGE_KEY = "market_dashboard_layout_v1";

export const DEFAULT_ORDER = [
  "market", "strategy", "events", "sectors", "trades", "journal",
];

function load() {
  try {
    const raw = localStorage.getItem(STORAGE_KEY);
    if (!raw) return null;
    return JSON.parse(raw);
  } catch {
    return null;
  }
}

function persist(state) {
  try { localStorage.setItem(STORAGE_KEY, JSON.stringify(state)); } catch {}
}

export function useDashboardLayout() {
  const [state, setState] = useState(() => {
    const saved = load();
    const savedOrder    = saved?.order    ?? [];
    const savedCollapsed = saved?.collapsed ?? [];

    // Merge: keep saved order, append any new ids at the end, drop removed ids
    const merged = [
      ...savedOrder.filter(id => DEFAULT_ORDER.includes(id)),
      ...DEFAULT_ORDER.filter(id => !savedOrder.includes(id)),
    ];

    return { order: merged, collapsed: savedCollapsed };
  });

  const toggleCollapse = useCallback((id) => {
    setState(prev => {
      const collapsed = prev.collapsed.includes(id)
        ? prev.collapsed.filter(c => c !== id)
        : [...prev.collapsed, id];
      const next = { ...prev, collapsed };
      persist(next);
      return next;
    });
  }, []);

  const reorder = useCallback((fromId, toId) => {
    if (fromId === toId) return;
    setState(prev => {
      const order = [...prev.order];
      const fi = order.indexOf(fromId);
      const ti = order.indexOf(toId);
      if (fi === -1 || ti === -1) return prev;
      order.splice(fi, 1);
      order.splice(ti, 0, fromId);
      const next = { ...prev, order };
      persist(next);
      return next;
    });
  }, []);

  const reset = useCallback(() => {
    const next = { order: DEFAULT_ORDER, collapsed: [] };
    persist(next);
    setState(next);
  }, []);

  return { ...state, toggleCollapse, reorder, reset };
}
