import React, { useState, useEffect, useRef, useCallback } from "react";
import axios from "axios";
import { toast } from "sonner";
import { Send, Sparkles, RotateCcw, RefreshCw, User, Zap } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Badge } from "@/components/ui/badge";

const API = `${process.env.REACT_APP_BACKEND_URL}/api`;

const SUGGESTIONS = [
  "Can I retire 5 years earlier?",
  "What if I bump my SIP by ₹10,000?",
  "Should I shift to aggressive allocation?",
  "How much more do I need to save monthly?",
  "What if my income grows to ₹2.5L/month?",
];

const fmtRs = (n) => {
  if (n == null) return "—";
  const abs = Math.abs(n);
  if (abs >= 1e7) return `₹${(n / 1e7).toFixed(2)} Cr`;
  if (abs >= 1e5) return `₹${(n / 1e5).toFixed(2)} L`;
  return `₹${Math.round(n).toLocaleString("en-IN")}`;
};

const pctTone = (pct) => {
  if (pct == null) return "text-slate-500";
  if (pct >= 85) return "text-emerald-600";
  if (pct >= 60) return "text-amber-600";
  return "text-rose-600";
};

// Mini stat chip for LLM responses
const Chip = ({ label, value, tone = "text-slate-800 dark:text-slate-100" }) => (
  <div className="rounded bg-slate-100 dark:bg-slate-800 px-2 py-1 text-[10px]">
    <span className="uppercase tracking-wider text-[9px] text-slate-500">{label}</span>
    <span className={`font-bold ml-1 tabular-nums ${tone}`}>{value}</span>
  </div>
);

export default function GoalCopilot({ goal, onGoalUpdated }) {
  const [messages, setMessages] = useState([]);
  const [input, setInput] = useState("");
  const [loading, setLoading] = useState(false);
  const [loadingHistory, setLoadingHistory] = useState(true);
  const endRef = useRef(null);

  const loadHistory = useCallback(async () => {
    setLoadingHistory(true);
    try {
      const res = await axios.get(
        `${API}/goals/${goal.goal_id}/copilot/history`,
        { withCredentials: true }
      );
      setMessages(res.data.messages || []);
    } catch (e) {
      /* non-fatal */
    } finally {
      setLoadingHistory(false);
    }
  }, [goal.goal_id]);

  useEffect(() => { loadHistory(); }, [loadHistory]);

  useEffect(() => {
    endRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages, loading]);

  const send = async (query) => {
    const q = (query ?? input).trim();
    if (!q || loading) return;
    setInput("");
    // Optimistically append user turn
    setMessages(prev => [
      ...prev,
      { role: "user", content: q, created_at: new Date().toISOString() },
    ]);
    setLoading(true);
    try {
      const res = await axios.post(
        `${API}/goals/${goal.goal_id}/copilot`,
        { query: q },
        { withCredentials: true, timeout: 30000 }
      );
      setMessages(prev => [
        ...prev,
        {
          role: "assistant",
          content: res.data.narrative,
          extracted_params: res.data.extracted_params,
          engine_output: res.data.engine_output,
          created_at: new Date().toISOString(),
        },
      ]);
    } catch (e) {
      toast.error(e.response?.data?.detail || "Copilot call failed");
      setMessages(prev => [
        ...prev,
        {
          role: "assistant",
          content: "Sorry — I couldn't evaluate that. Try rephrasing the question?",
          created_at: new Date().toISOString(),
        },
      ]);
    } finally {
      setLoading(false);
    }
  };

  const clearHistory = async () => {
    if (!window.confirm("Clear this goal's copilot chat history?")) return;
    try {
      await axios.delete(
        `${API}/goals/${goal.goal_id}/copilot/history`,
        { withCredentials: true }
      );
      setMessages([]);
      toast.success("Chat history cleared");
    } catch (e) {
      toast.error("Failed to clear");
    }
  };

  const applyLastSuggestion = async (msg) => {
    const params = msg.extracted_params || {};
    const patch = {};
    if (params.horizon_years != null) patch.horizon_years = params.horizon_years;
    if (params.monthly_sip_rs != null) patch.monthly_sip_rs = params.monthly_sip_rs;
    if (params.allocation_override) patch.allocation = params.allocation_override;
    if (Object.keys(patch).length === 0) {
      toast.info("No changes to apply");
      return;
    }
    if (!window.confirm(`Apply these changes to the goal?\n\n${JSON.stringify(patch, null, 2)}`)) return;
    try {
      await axios.patch(`${API}/goals/${goal.goal_id}`, patch, { withCredentials: true });
      await axios.post(`${API}/goals/${goal.goal_id}/simulate`, {}, { withCredentials: true });
      toast.success("Applied and simulated");
      onGoalUpdated?.();
    } catch (e) {
      toast.error(e.response?.data?.detail || "Failed to apply");
    }
  };

  return (
    <div className="rounded-xl border border-indigo-200 dark:border-indigo-900 bg-gradient-to-br from-indigo-50/50 to-white dark:from-indigo-950/20 dark:to-transparent"
         data-testid="goal-copilot">
      <div className="flex items-center justify-between px-4 py-2.5 border-b border-indigo-100 dark:border-indigo-900">
        <div className="flex items-center gap-2">
          <div className="w-6 h-6 bg-indigo-600 rounded-md flex items-center justify-center">
            <Sparkles className="w-3.5 h-3.5 text-white" />
          </div>
          <span className="text-sm font-semibold text-indigo-900 dark:text-indigo-200">
            Goal Copilot
          </span>
          <Badge variant="outline" className="text-[9px] border-indigo-200 text-indigo-700 dark:border-indigo-800 dark:text-indigo-300">
            gpt-4o-mini
          </Badge>
        </div>
        {messages.length > 0 && (
          <Button
            size="sm"
            variant="ghost"
            onClick={clearHistory}
            className="text-[10px] h-7"
            data-testid="copilot-clear-btn"
          >
            <RotateCcw className="w-3 h-3 mr-1" /> clear
          </Button>
        )}
      </div>

      {/* Messages */}
      <div
        className="px-4 py-3 max-h-[360px] overflow-y-auto space-y-3"
        data-testid="copilot-messages"
      >
        {loadingHistory && (
          <div className="text-xs text-slate-500 text-center py-4">Loading history…</div>
        )}
        {!loadingHistory && messages.length === 0 && (
          <div className="text-center py-4">
            <div className="text-xs text-slate-500 mb-3">
              Ask about this goal in plain English — I'll run the simulation and explain the result.
            </div>
            <div className="flex flex-wrap gap-1.5 justify-center">
              {SUGGESTIONS.slice(0, 4).map((s, i) => (
                <button
                  key={i}
                  onClick={() => send(s)}
                  className="text-[10px] px-2 py-1 rounded-full border border-indigo-200 dark:border-indigo-800 text-indigo-700 dark:text-indigo-300 hover:bg-indigo-50 dark:hover:bg-indigo-900/30"
                  data-testid={`copilot-suggestion-${i}`}
                >
                  {s}
                </button>
              ))}
            </div>
          </div>
        )}
        {messages.map((m, i) => (
          <div
            key={i}
            className={`flex gap-2 ${m.role === "user" ? "justify-end" : ""}`}
            data-testid={`copilot-msg-${m.role}-${i}`}
          >
            {m.role === "assistant" && (
              <div className="w-6 h-6 bg-indigo-600 rounded-full flex-shrink-0 flex items-center justify-center mt-0.5">
                <Sparkles className="w-3 h-3 text-white" />
              </div>
            )}
            <div
              className={`max-w-[85%] rounded-lg px-3 py-2 text-xs leading-relaxed ${
                m.role === "user"
                  ? "bg-indigo-600 text-white"
                  : "bg-white dark:bg-slate-800 text-slate-800 dark:text-slate-100 border border-slate-200 dark:border-slate-700"
              }`}
            >
              <div>{m.content}</div>
              {m.role === "assistant" && m.engine_output && !m.engine_output.error && (
                <div className="mt-2 flex flex-wrap gap-1">
                  <Chip
                    label="on-track"
                    value={`${(m.engine_output.on_track_pct ?? 0).toFixed(0)}%`}
                    tone={pctTone(m.engine_output.on_track_pct)}
                  />
                  {m.engine_output.monte_carlo?.prob_success_pct != null && (
                    <Chip
                      label="MC"
                      value={`${m.engine_output.monte_carlo.prob_success_pct.toFixed(0)}%`}
                      tone={pctTone(m.engine_output.monte_carlo.prob_success_pct)}
                    />
                  )}
                  {m.engine_output.required_sip_rs != null && (
                    <Chip
                      label="req SIP"
                      value={`${fmtRs(m.engine_output.required_sip_rs)}/mo`}
                    />
                  )}
                  {m.engine_output.expected_return_pct != null && (
                    <Chip
                      label="return"
                      value={`${m.engine_output.expected_return_pct.toFixed(1)}%`}
                    />
                  )}
                </div>
              )}
              {m.role === "assistant" && m.extracted_params && (
                Object.values(m.extracted_params).some((v) => v != null && v !== "general")
              ) && (
                <div className="mt-2 pt-2 border-t border-slate-200 dark:border-slate-700 flex items-center justify-between gap-2">
                  <span className="text-[9px] uppercase tracking-wider text-slate-500">
                    Hypothetical plan
                  </span>
                  <Button
                    size="sm"
                    variant="outline"
                    className="text-[10px] h-6 px-2"
                    onClick={() => applyLastSuggestion(m)}
                    data-testid={`copilot-apply-${i}`}
                  >
                    <Zap className="w-2.5 h-2.5 mr-1" /> Apply to goal
                  </Button>
                </div>
              )}
            </div>
            {m.role === "user" && (
              <div className="w-6 h-6 bg-slate-500 rounded-full flex-shrink-0 flex items-center justify-center mt-0.5">
                <User className="w-3 h-3 text-white" />
              </div>
            )}
          </div>
        ))}
        {loading && (
          <div className="flex gap-2" data-testid="copilot-loading">
            <div className="w-6 h-6 bg-indigo-600 rounded-full flex items-center justify-center">
              <RefreshCw className="w-3 h-3 text-white animate-spin" />
            </div>
            <div className="bg-white dark:bg-slate-800 border border-slate-200 dark:border-slate-700 rounded-lg px-3 py-2 text-xs text-slate-500">
              Running simulation…
            </div>
          </div>
        )}
        <div ref={endRef} />
      </div>

      {/* Input */}
      <div className="px-3 py-2.5 border-t border-indigo-100 dark:border-indigo-900">
        <div className="flex gap-2">
          <Input
            value={input}
            onChange={(e) => setInput(e.target.value)}
            onKeyDown={(e) => e.key === "Enter" && !e.shiftKey && (e.preventDefault(), send())}
            placeholder="e.g. Can I retire 5 years earlier?"
            disabled={loading}
            className="text-xs"
            data-testid="copilot-input"
          />
          <Button
            size="sm"
            onClick={() => send()}
            disabled={loading || !input.trim()}
            className="bg-indigo-600 hover:bg-indigo-700"
            data-testid="copilot-send"
          >
            <Send className="w-3.5 h-3.5" />
          </Button>
        </div>
      </div>
    </div>
  );
}
