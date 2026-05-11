import React, { useEffect, useState, useCallback } from "react";
import axios from "axios";
import { ChevronDown, BarChart3, Search, LineChart, Receipt, Shield, FileText, Compass } from "lucide-react";

const API = `${process.env.REACT_APP_BACKEND_URL}/api`;
const ICON = {
  "compass": Compass, "bar-chart-3": BarChart3, "search": Search, "line-chart": LineChart,
  "receipt": Receipt, "shield": Shield, "file-text": FileText,
};

/**
 * AgentPicker + ModelPicker — Doc 02 §2.1.
 * Inline dropdown rendered above the chat input. Default = Auto-route.
 */
export const AgentPicker = ({ value = "auto", onChange }) => {
  const [open, setOpen] = useState(false);
  const [agents, setAgents] = useState([]);

  useEffect(() => {
    axios.get(`${API}/copilot/agents`, { withCredentials: true })
      .then((r) => setAgents(r.data?.agents || []))
      .catch(() => setAgents([]));
  }, []);

  const current = agents.find((a) => a.id === value) || agents[0];
  const Icon = current ? (ICON[current.icon] || Compass) : Compass;

  return (
    <div className="relative inline-block">
      <button
        type="button"
        data-testid="agent-picker-toggle"
        onClick={() => setOpen((v) => !v)}
        className="inline-flex items-center gap-1.5 px-2.5 py-1 text-[11px] rounded-full border border-[color:var(--cp-border-subtle)] text-slate-600 dark:text-slate-300 hover:border-[color:var(--cp-accent-brand)]"
      >
        <Icon className="w-3 h-3" />
        <span className="truncate max-w-[180px]">{current?.label || "Auto-route"}</span>
        <ChevronDown className="w-3 h-3 text-slate-400" />
      </button>
      {open && (
        <div data-testid="agent-picker-menu" className="absolute bottom-full mb-1 left-0 w-64 max-h-80 overflow-auto rounded-lg shadow-lg border border-[color:var(--cp-border-subtle)] bg-white dark:bg-slate-800 z-50">
          {agents.map((a) => {
            const IconA = ICON[a.icon] || Compass;
            const active = a.id === value;
            return (
              <button
                key={a.id}
                data-testid={`agent-picker-${a.id}`}
                onClick={() => { onChange && onChange(a.id); setOpen(false); }}
                className={`w-full text-left px-3 py-2 text-xs flex items-start gap-2 hover:bg-[color:var(--cp-surface-1)] ${active ? "bg-[color:var(--cp-surface-1)]" : ""}`}
              >
                <IconA className="w-3.5 h-3.5 mt-0.5 text-slate-500" />
                <div className="flex-1 min-w-0">
                  <div className="font-medium truncate">{a.label}</div>
                  <div className="text-[10px] text-slate-500 truncate">{a.one_liner}</div>
                </div>
              </button>
            );
          })}
        </div>
      )}
    </div>
  );
};

export const ModelPicker = ({ value, onChange }) => {
  const [open, setOpen] = useState(false);
  const [models, setModels] = useState([]);

  useEffect(() => {
    axios.get(`${API}/copilot/models/picker`, { withCredentials: true })
      .then((r) => {
        const list = r.data?.models || [];
        setModels(list);
        if (!value && list.length) {
          const def = list.find((m) => m.is_default) || list[0];
          onChange && onChange(def.id);
        }
      })
      .catch(() => setModels([]));
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const current = models.find((m) => m.id === value) || models[0];

  return (
    <div className="relative inline-block">
      <button
        type="button"
        data-testid="model-picker-toggle"
        onClick={() => setOpen((v) => !v)}
        className="inline-flex items-center gap-1.5 px-2.5 py-1 text-[11px] rounded-full border border-[color:var(--cp-border-subtle)] text-slate-600 dark:text-slate-300 hover:border-[color:var(--cp-accent-brand)]"
      >
        <span className="cp-intel-mark font-semibold">{current?.label?.split(" (")[0] || "Model"}</span>
        <ChevronDown className="w-3 h-3 text-slate-400" />
      </button>
      {open && (
        <div data-testid="model-picker-menu" className="absolute bottom-full mb-1 left-0 w-72 max-h-72 overflow-auto rounded-lg shadow-lg border border-[color:var(--cp-border-subtle)] bg-white dark:bg-slate-800 z-50">
          {models.map((m) => {
            const active = m.id === value;
            return (
              <button
                key={m.id}
                data-testid={`model-picker-${m.id}`}
                onClick={() => { onChange && onChange(m.id); setOpen(false); }}
                className={`w-full text-left px-3 py-2 text-xs hover:bg-[color:var(--cp-surface-1)] ${active ? "bg-[color:var(--cp-surface-1)]" : ""}`}
              >
                <div className="font-medium">{m.label}</div>
                <div className="text-[10px] text-slate-500">{m.provider} · {m.underlying}</div>
                {m.notes && <div className="text-[10px] text-slate-400 mt-0.5">{m.notes}</div>}
              </button>
            );
          })}
        </div>
      )}
    </div>
  );
};

/**
 * useAgentRoute — small hook to call /agents/route deterministically
 * before sending a chat message, so the ribbon shows the right agent
 * the instant the user hits Enter.
 */
export const useAgentRoute = () => useCallback(async (message) => {
  try {
    const r = await axios.post(`${API}/copilot/agents/route`, { message }, { withCredentials: true });
    return r.data || null;
  } catch {
    return null;
  }
}, []);

export default { AgentPicker, ModelPicker, useAgentRoute };
