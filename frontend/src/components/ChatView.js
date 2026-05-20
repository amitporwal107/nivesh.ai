import React, { useState, useEffect, useRef, useCallback } from "react";
import axios from "axios";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import {
  Send, Trash2, Bot, User, Plus, MessageSquare, ChevronLeft,
  Clock, TrendingUp, Shield, BarChart3, Lightbulb,
  Zap, RefreshCw, Wrench, Layers, ArrowRightCircle, AlertTriangle, Target,
  Maximize2, Minimize2, Pin, PinOff, Pencil, Check, X as XIcon,
  Copy, RotateCcw, ThumbsUp, ThumbsDown,
} from "lucide-react";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { ScrollArea } from "@/components/ui/scroll-area";
import { motion, AnimatePresence } from "framer-motion";
import { ChatMessageSkeleton } from "@/components/ui/skeleton-loaders";
import CopilotPromptCard from "@/components/copilot/CopilotPromptCard";
import SaveAsPlanCard, { shouldShowSavePlan } from "@/components/copilot/SaveAsPlanCard";
import ChartBlock from "@/components/copilot/ChartBlock";
import { parseCopilotChartBlocks } from "@/lib/parseCopilotChartBlocks";
import { AgentPicker, ModelPicker, useAgentRoute } from "@/components/copilot/AgentModelPickers";
import { cn } from "@/lib/utils";
import AgentRibbon from "@/components/copilot/shared/AgentRibbon";
import { resolveAgent } from "@/components/copilot/shared/agentRegistry";
import WidgetRenderer from "@/components/copilot/widgets/WidgetRenderer";
import V2CopilotWelcome from "@/components/v2app/screens/V2CopilotWelcome";

const BACKEND_URL = process.env.REACT_APP_BACKEND_URL;
const API = `${BACKEND_URL}/api`;

const MARKDOWN_COMPONENTS = {
  p: ({ children }) => <p className="mb-2 last:mb-0">{children}</p>,
  strong: ({ children }) => <strong className="font-semibold">{children}</strong>,
  ul: ({ children }) => <ul className="list-disc pl-4 mb-2 space-y-1">{children}</ul>,
  ol: ({ children }) => <ol className="list-decimal pl-4 mb-2 space-y-1">{children}</ol>,
  li: ({ children }) => <li className="leading-relaxed">{children}</li>,
  h1: ({ children }) => <h3 className="text-base font-semibold mb-2 mt-3 first:mt-0">{children}</h3>,
  h2: ({ children }) => <h3 className="text-base font-semibold mb-2 mt-3 first:mt-0">{children}</h3>,
  h3: ({ children }) => <h4 className="text-sm font-semibold mb-1.5 mt-2 first:mt-0">{children}</h4>,
  code: ({ inline, children }) =>
    inline ? (
      <code className="bg-slate-200 dark:bg-slate-700 px-1.5 py-0.5 rounded text-xs font-mono">{children}</code>
    ) : (
      <pre className="bg-slate-200 dark:bg-slate-700 p-3 rounded-lg text-xs font-mono overflow-x-auto mb-2">
        <code>{children}</code>
      </pre>
    ),
  table: ({ children }) => (
    <div className="overflow-x-auto mb-2">
      <table className="text-xs border-collapse w-full">{children}</table>
    </div>
  ),
  th: ({ children }) => <th className="border border-slate-300 dark:border-slate-600 px-2 py-1 bg-slate-100 dark:bg-slate-700 font-semibold text-left">{children}</th>,
  td: ({ children }) => <td className="border border-slate-300 dark:border-slate-600 px-2 py-1">{children}</td>,
  blockquote: ({ children }) => <blockquote className="border-l-3 border-emerald-500 pl-3 italic my-2 text-slate-600 dark:text-slate-300">{children}</blockquote>,
  hr: () => <hr className="my-3 border-slate-200 dark:border-slate-600" />,
};

// Renders a single Copilot message: splits any ```chart``` JSON blocks
// out of the markdown stream and replaces them with Recharts visuals.
// During streaming, in-flight chart blocks (no closing fence yet) just
// fall through as plain markdown — the `done` event re-renders with
// the server-validated content.
const MarkdownMessage = ({ content }) => {
  const segments = parseCopilotChartBlocks(content);
  return (
    <>
      {segments.map((seg, i) =>
        seg.kind === "chart" ? (
          <ChartBlock key={i} spec={seg.spec} />
        ) : (
          <ReactMarkdown
            key={i}
            remarkPlugins={[remarkGfm]}
            components={MARKDOWN_COMPONENTS}
          >
            {seg.text}
          </ReactMarkdown>
        )
      )}
    </>
  );
};

/* ── Universal toolbar shown under every AI message ── */
const MessageToolbar = ({ message, prevUserText, onRegenerate, onFeedback }) => {
  const [copied, setCopied] = React.useState(false);
  const [rated, setRated] = React.useState(null); // "up" | "down" | null

  const handleCopy = async () => {
    try {
      await navigator.clipboard.writeText(message.content || "");
      setCopied(true);
      setTimeout(() => setCopied(false), 1200);
    } catch {
      /* ignore */
    }
  };

  const handleRate = (rating) => {
    if (rated) return;
    setRated(rating);
    onFeedback?.(message, rating);
  };

  const baseBtn =
    "inline-flex items-center justify-center w-7 h-7 rounded-md text-slate-400 dark:text-slate-500 hover:text-slate-700 dark:hover:text-slate-200 hover:bg-slate-100 dark:hover:bg-white/10 transition-colors";

  return (
    <div
      data-testid={`msg-toolbar-${message.message_id}`}
      className="flex items-center gap-0.5 mt-2 opacity-60 hover:opacity-100 transition-opacity"
    >
      <button
        type="button"
        title={copied ? "Copied" : "Copy"}
        aria-label="Copy message"
        onClick={handleCopy}
        className={baseBtn}
        data-testid="msg-action-copy"
      >
        {copied ? <Check className="w-3.5 h-3.5" strokeWidth={2} /> : <Copy className="w-3.5 h-3.5" strokeWidth={1.75} />}
      </button>
      {prevUserText && onRegenerate && (
        <button
          type="button"
          title="Regenerate"
          aria-label="Regenerate response"
          onClick={() => onRegenerate(prevUserText)}
          className={baseBtn}
          data-testid="msg-action-regenerate"
        >
          <RotateCcw className="w-3.5 h-3.5" strokeWidth={1.75} />
        </button>
      )}
      <button
        type="button"
        title="Helpful"
        aria-label="Mark helpful"
        onClick={() => handleRate("up")}
        className={`${baseBtn} ${rated === "up" ? "text-emerald-500 dark:text-emerald-400" : ""}`}
        data-testid="msg-action-thumbs-up"
      >
        <ThumbsUp className="w-3.5 h-3.5" strokeWidth={1.75} />
      </button>
      <button
        type="button"
        title="Not helpful"
        aria-label="Mark not helpful"
        onClick={() => handleRate("down")}
        className={`${baseBtn} ${rated === "down" ? "text-rose-500 dark:text-rose-400" : ""}`}
        data-testid="msg-action-thumbs-down"
      >
        <ThumbsDown className="w-3.5 h-3.5" strokeWidth={1.75} />
      </button>
    </div>
  );
};

/* ── Quick Action Buttons shown after AI response ── */
const QuickActions = ({ content, onAction }) => {
  const actions = detectActions(content);
  if (actions.length === 0) return null;

  return (
    <motion.div
      initial={{ opacity: 0, y: 6 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ delay: 0.3 }}
      className="flex flex-wrap gap-2 mt-3 pt-3 border-t border-slate-100 dark:border-slate-700/50"
    >
      {actions.map((action) => (
        <button
          key={action.label}
          data-testid={`quick-action-${action.id}`}
          onClick={() => onAction(action.prompt)}
          className="inline-flex items-center gap-1.5 px-3 py-1.5 text-xs font-medium rounded-lg border transition-all duration-200 bg-white dark:bg-slate-800 border-slate-200 dark:border-slate-700 text-slate-600 dark:text-slate-300 hover:border-emerald-300 hover:text-emerald-700 dark:hover:text-emerald-400 hover:bg-emerald-50 dark:hover:bg-emerald-900/20"
        >
          <action.icon className="w-3.5 h-3.5" strokeWidth={1.5} />
          {action.label}
        </button>
      ))}
    </motion.div>
  );
};

function detectActions(content) {
  if (!content) return [];
  const lower = content.toLowerCase();
  const actions = [];

  if (lower.includes("risk") || lower.includes("volatile") || lower.includes("concentration"))
    actions.push({ id: "simulate-risk", label: "Simulate lower risk", icon: Shield, prompt: "Simulate a lower risk portfolio for me. Show before vs after." });

  if (lower.includes("rebalance") || lower.includes("allocation") || lower.includes("diversif"))
    actions.push({ id: "show-rebalance", label: "Show rebalance plan", icon: RefreshCw, prompt: "Show me a detailed rebalance plan with specific actions." });

  if (lower.includes("invest") || lower.includes("recommend") || lower.includes("sip") || lower.includes("mutual fund"))
    actions.push({ id: "compare-funds", label: "Compare options", icon: BarChart3, prompt: "Compare the top 3 options you mentioned with pros, cons, and expected returns." });

  if (lower.includes("tax") || lower.includes("ltcg") || lower.includes("stcg") || lower.includes("80c"))
    actions.push({ id: "tax-strategy", label: "Tax saving strategy", icon: Lightbulb, prompt: "Give me a detailed tax saving strategy based on my portfolio." });

  if (lower.includes("performance") || lower.includes("return") || lower.includes("growth"))
    actions.push({ id: "deep-analysis", label: "Deep analysis", icon: TrendingUp, prompt: "Give me a deep performance analysis of my portfolio holdings." });

  return actions.slice(0, 3);
}

/* ── Streaming "thinking" indicator with rotating professional phrases ── */
const _THINKING_PHRASES = [
  "Analysing your portfolio…",
  "Cross-checking holdings against your targets…",
  "Pulling drift across asset classes…",
  "Computing AMC and sector concentration…",
  "Looking up look-through stock exposures…",
  "Drafting the recommendation…",
];

const _TOOL_LABELS = {
  get_portfolio_summary: "Loading portfolio…",
  get_sip_projection: "Computing SIP projection…",
  get_user_goals: "Fetching your goals…",
  sip_projection: "Computing SIP projection…",
  get_top_funds: "Ranking mutual funds…",
  get_fundamental_comparison: "Pulling fundamental data…",
  get_technical_comparison: "Fetching technical signals…",
  get_full_tax_report: "Calculating tax impact…",
  get_tax_harvest_candidates: "Scanning for harvest candidates…",
  get_portfolio_xirr: "Computing XIRR…",
  run_stress_test: "Running stress test…",
  get_rebalance_plan: "Building rebalance plan…",
};

const StreamingIndicator = ({ toolName }) => {
  const [idx, setIdx] = React.useState(0);
  React.useEffect(() => {
    if (toolName) return; // don't rotate when showing a specific tool
    const t = setInterval(() => setIdx((i) => (i + 1) % _THINKING_PHRASES.length), 2200);
    return () => clearInterval(t);
  }, [toolName]);
  const label = toolName
    ? (_TOOL_LABELS[toolName] || `Running ${toolName.replace(/_/g, " ")}…`)
    : _THINKING_PHRASES[idx];
  return (
    <motion.div
      initial={{ opacity: 0, y: 6 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.25 }}
      className="flex gap-3 justify-start"
    >
      <div className="relative w-8 h-8 flex-shrink-0 mt-1">
        <div className="absolute inset-0 rounded-xl bg-gradient-to-br from-emerald-400 to-emerald-600 opacity-90 animate-pulse" />
        <div className="absolute inset-0 rounded-xl ring-2 ring-emerald-300/40" />
        <div className="absolute inset-0 flex items-center justify-center">
          <Bot className="w-4 h-4 text-white drop-shadow" strokeWidth={1.75} />
        </div>
      </div>
      <div className="chat-ai-bubble px-4 py-3 shadow-sm">
        <div className="flex items-center gap-2.5">
          <div className="flex gap-1">
            <span className="w-1.5 h-1.5 bg-emerald-500 rounded-full animate-bounce" style={{ animationDelay: "0ms" }} />
            <span className="w-1.5 h-1.5 bg-emerald-500 rounded-full animate-bounce" style={{ animationDelay: "180ms" }} />
            <span className="w-1.5 h-1.5 bg-emerald-500 rounded-full animate-bounce" style={{ animationDelay: "360ms" }} />
          </div>
          <AnimatePresence mode="wait">
            <motion.span
              key={toolName || idx}
              initial={{ opacity: 0, y: 4 }}
              animate={{ opacity: 1, y: 0 }}
              exit={{ opacity: 0, y: -4 }}
              transition={{ duration: 0.25 }}
              className="text-xs text-slate-500 dark:text-slate-400 italic"
            >
              {label}
            </motion.span>
          </AnimatePresence>
        </div>
      </div>
    </motion.div>
  );
};

const SessionItem = ({ session, isActive, onClick, onDelete, onPin, onRename }) => {
  const [editing, setEditing] = useState(false);
  const [draftTitle, setDraftTitle] = useState(session.title || "");

  const commitRename = () => {
    const t = draftTitle.trim();
    if (t && t !== session.title) onRename(session.session_id, t);
    setEditing(false);
  };

  return (
    <div
      data-testid={`chat-session-${session.session_id}`}
      onClick={() => !editing && onClick(session.session_id)}
      role="button"
      tabIndex={0}
      className={`w-full text-left px-3 py-2.5 rounded-xl text-sm transition-all duration-200 group flex items-center gap-2 cursor-pointer ${
        isActive
          ? "bg-emerald-50 dark:bg-emerald-900/30 text-emerald-700 dark:text-emerald-400"
          : "text-slate-600 dark:text-slate-400 hover:bg-slate-50 dark:hover:bg-slate-800"
      }`}
    >
      {session.pinned
        ? <Pin className="w-3.5 h-3.5 flex-shrink-0 text-emerald-500" strokeWidth={1.5} />
        : <MessageSquare className="w-3.5 h-3.5 flex-shrink-0" strokeWidth={1.5} />
      }

      {editing ? (
        <input
          autoFocus
          value={draftTitle}
          onChange={(e) => setDraftTitle(e.target.value)}
          onKeyDown={(e) => { if (e.key === "Enter") commitRename(); if (e.key === "Escape") setEditing(false); }}
          onClick={(e) => e.stopPropagation()}
          className="flex-1 min-w-0 text-xs bg-transparent border-b border-emerald-400 outline-none"
        />
      ) : (
        <span className="flex-1 truncate">{session.title}</span>
      )}

      <div className="flex items-center gap-0.5 opacity-0 group-hover:opacity-100 transition-opacity flex-shrink-0">
        {editing ? (
          <>
            <button onClick={(e) => { e.stopPropagation(); commitRename(); }} className="p-0.5 hover:text-emerald-600">
              <Check className="w-3 h-3" />
            </button>
            <button onClick={(e) => { e.stopPropagation(); setEditing(false); }} className="p-0.5 hover:text-slate-500">
              <XIcon className="w-3 h-3" />
            </button>
          </>
        ) : (
          <>
            <button
              data-testid={`rename-session-${session.session_id}`}
              onClick={(e) => { e.stopPropagation(); setDraftTitle(session.title || ""); setEditing(true); }}
              className="p-0.5 hover:text-slate-700 dark:hover:text-slate-200"
              title="Rename"
            >
              <Pencil className="w-3 h-3" />
            </button>
            <button
              data-testid={`pin-session-${session.session_id}`}
              onClick={(e) => { e.stopPropagation(); onPin(session.session_id, !session.pinned); }}
              className="p-0.5 hover:text-emerald-600"
              title={session.pinned ? "Unpin" : "Pin"}
            >
              {session.pinned ? <PinOff className="w-3 h-3" /> : <Pin className="w-3 h-3" />}
            </button>
            <button
              data-testid={`delete-session-${session.session_id}`}
              onClick={(e) => { e.stopPropagation(); onDelete(session.session_id); }}
              className="p-0.5 hover:text-red-500"
              title="Delete"
            >
              <Trash2 className="w-3 h-3" />
            </button>
          </>
        )}
      </div>
    </div>
  );
};

const ChatView = ({ onNavigateToPlanBoard, initialSessionId, v2Mode = false, v2PersonaId = "retail_investor", v2Analytics = null, v2Holdings = [], v2Workspace = null } = {}) => {
  const [messages, setMessages] = useState([]);
  const [input, setInput] = useState("");
  const [suggestedPrompts, setSuggestedPrompts] = useState([]);
  const [tieredPrompts, setTieredPrompts] = useState({ primary: [], secondary: [], advanced: [], journey: "returning", persona: null, category_filter: null, persona_prompts_enabled: false });
  const [showAdvanced, setShowAdvanced] = useState(false);
  const [activeCategoryFilter, setActiveCategoryFilter] = useState(null);
  const [suggestionsLoading, setSuggestionsLoading] = useState(true);
  const [sending, setSending] = useState(false);
  const [streaming, setStreaming] = useState(false);
  const [streamingContent, setStreamingContent] = useState("");
  const [thinkingTool, setThinkingTool] = useState(null); // active tool name from SSE thinking events
  const [loadingMessages, setLoadingMessages] = useState(true);
  const [sessions, setSessions] = useState([]);
  const [activeSessionId, setActiveSessionId] = useState(null);
  const [showSidebar, setShowSidebar] = useState(typeof window !== "undefined" ? window.innerWidth >= 768 : true);
  // Intelligence Layer (Phase B): agent + model picker state, current-turn agent
  const [selectedAgentId, setSelectedAgentId] = useState("auto");
  const [selectedModelId, setSelectedModelId] = useState(null);   // populated by ModelPicker on mount
  const [currentTurnAgent, setCurrentTurnAgent] = useState(null);  // shown in the "thinking" ribbon
  const [showV2History, setShowV2History] = useState(false);
  const routeIntent = useAgentRoute();
  const messagesEndRef = useRef(null);
  const inputRef = useRef(null);
  const abortRef = useRef(null);

  const fetchSessions = useCallback(async () => {
    try {
      const res = await axios.get(`${API}/chat/sessions`, { withCredentials: true });
      setSessions(res.data);
      return res.data;
    } catch (err) {
      console.error("Failed to load sessions", err);
      return [];
    }
  }, []);

  const fetchSuggestedPrompts = useCallback(async (categoryFilter = null, personaOverride = null) => {
    setSuggestionsLoading(true);
    try {
      const params = {};
      if (categoryFilter) params.category = categoryFilter;
      // Optional persona override: callers can pass an exact PersonaType.value
      // when they have one (e.g. immediately after CAS upload before the
      // backend persona_engine has written user_profiles). Defaults are left
      // to the backend so it can read user_profiles.persona authoritatively.
      if (personaOverride) params.persona = personaOverride;
      const res = await axios.get(`${API}/copilot/suggested-prompts`, { params, withCredentials: true });
      setSuggestedPrompts(res.data?.prompts || []);
      setTieredPrompts({
        primary: res.data?.primary || [],
        secondary: res.data?.secondary || [],
        advanced: res.data?.advanced || [],
        journey: res.data?.journey || "returning",
        persona: res.data?.persona || null,
        category_filter: res.data?.category_filter || null,
        persona_prompts_enabled: !!res.data?.persona_prompts_enabled,
      });
    } catch (err) {
      setSuggestedPrompts([]);
      setTieredPrompts({ primary: [], secondary: [], advanced: [], journey: "returning", persona: null, category_filter: null, persona_prompts_enabled: false });
    } finally {
      setSuggestionsLoading(false);
    }
  }, []);

  const fetchMessages = useCallback(async (sessionId) => {
    setLoadingMessages(true);
    try {
      const url = sessionId
        ? `${API}/chat/messages?session_id=${sessionId}`
        : `${API}/chat/messages`;
      const res = await axios.get(url, { withCredentials: true });
      setMessages(res.data);
    } catch (err) {
      console.error("Failed to load messages", err);
    } finally {
      setLoadingMessages(false);
    }
  }, []);

  useEffect(() => {
    const init = async () => {
      const loadedSessions = await fetchSessions();
      // Prefer initialSessionId (from /chat/:threadId) if it matches a session
      const preferred = initialSessionId
        ? loadedSessions.find((s) => s.session_id === initialSessionId)
        : null;
      const first = preferred || (loadedSessions.length > 0 ? loadedSessions[0] : null);
      if (first) {
        setActiveSessionId(first.session_id);
        fetchMessages(first.session_id);
      } else {
        setLoadingMessages(false);
      }
      fetchSuggestedPrompts();
    };
    init();
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [fetchSessions, fetchMessages, fetchSuggestedPrompts]);

  // In v2Mode: consume any pending message that was queued via sessionStorage
  // (e.g. from the V2 home screen AI input before navigating to the copilot screen)
  useEffect(() => {
    if (!v2Mode) return;
    const pending = sessionStorage.getItem("v2_pending_chat_message");
    if (!pending) return;
    sessionStorage.removeItem("v2_pending_chat_message");
    // Small delay so ChatView is fully mounted before sending
    const t = setTimeout(() => sendMessageWithText(pending), 300);
    return () => clearTimeout(t);
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [v2Mode]);

  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages, streamingContent]);

  const handleNewSession = async () => {
    try {
      const res = await axios.post(`${API}/chat/sessions`, {}, { withCredentials: true });
      const newSession = res.data;
      setSessions((prev) => [newSession, ...prev]);
      setActiveSessionId(newSession.session_id);
      setMessages([]);
    } catch (err) {
      console.error("Failed to create session", err);
    }
  };

  const handleSwitchSession = (sessionId) => {
    setActiveSessionId(sessionId);
    fetchMessages(sessionId);
  };

  const handleDeleteSession = async (sessionId) => {
    try {
      await axios.delete(`${API}/chat/sessions/${sessionId}`, { withCredentials: true });
      setSessions((prev) => prev.filter((s) => s.session_id !== sessionId));
      if (activeSessionId === sessionId) {
        const remaining = sessions.filter((s) => s.session_id !== sessionId);
        if (remaining.length > 0) {
          setActiveSessionId(remaining[0].session_id);
          fetchMessages(remaining[0].session_id);
        } else {
          setActiveSessionId(null);
          setMessages([]);
        }
      }
    } catch (err) {
      console.error("Failed to delete session", err);
    }
  };

  const handlePinSession = (sessionId, pin) => {
    // Optimistic local update — server-side persistence is best-effort via PATCH
    setSessions((prev) => prev.map((s) => s.session_id === sessionId ? { ...s, pinned: pin } : s));
    axios.patch(`${API}/chat/sessions/${sessionId}`, { pinned: pin }, { withCredentials: true }).catch(() => {});
  };

  const handleRenameSession = (sessionId, newTitle) => {
    setSessions((prev) => prev.map((s) => s.session_id === sessionId ? { ...s, title: newTitle } : s));
    axios.patch(`${API}/chat/sessions/${sessionId}`, { title: newTitle }, { withCredentials: true }).catch(() => {});
  };

  const sendMessageWithText = useCallback(async (rawText) => {
    const text = (rawText || "").trim();
    if (!text || sending || streaming) return;

    setInput("");

    // ── Intelligence Layer slash-command dispatcher (Phase B) ───
    // Recognised commands → call /api/copilot/widgets/* and append
    // the widget envelope as a synthetic assistant turn. No LLM call.
    //   /fundcard <scheme name>
    //   /market
    //   /compare <code1>,<code2>[,<code3>][,<code4>]
    //   /sip <monthly_budget> [moderate|aggressive|conservative]
    const slashMatch = text.match(/^\/(\w+)(?:\s+(.+))?$/i);
    if (slashMatch) {
      const cmd = slashMatch[1].toLowerCase();
      const arg = (slashMatch[2] || "").trim();
      const tempUserMsg = { message_id: `temp_user_${Date.now()}`, role: "user", content: text, created_at: new Date().toISOString() };
      setMessages((prev) => [...prev, tempUserMsg]);
      setSending(true);
      try {
        let url = null;
        let body = null;
        if (cmd === "fundcard" || cmd === "fund") {
          if (!arg) throw new Error("Usage: /fundcard <scheme name>");
          url = `${API}/copilot/widgets/fund_card`; body = { query: arg };
        } else if (cmd === "market" || cmd === "brief") {
          url = `${API}/copilot/widgets/market_brief`; body = {};
        } else if (cmd === "compare") {
          const codes = arg.split(",").map((s) => s.trim()).filter(Boolean);
          if (codes.length < 2) throw new Error("Usage: /compare <code1>,<code2>[,<code3>]");
          url = `${API}/copilot/widgets/compare_funds`; body = { scheme_codes: codes };
        } else if (cmd === "sip") {
          const parts = arg.split(/\s+/);
          const budget = parseFloat(parts[0] || "0");
          const risk = (parts[1] || "Moderate");
          if (!budget) throw new Error("Usage: /sip <monthly_budget> [conservative|moderate|aggressive]");
          url = `${API}/copilot/widgets/sip_plan`; body = { monthly_budget: budget, risk_label: risk };
        } else if (cmd === "rebalance") {
          url = `${API}/copilot/widgets/rebalance_plan`; body = {};
        } else if (cmd === "tax" || cmd === "harvest") {
          url = `${API}/copilot/widgets/tax_harvest`; body = {};
        } else if (cmd === "stress") {
          const scenario = arg || "covid_2020";
          url = `${API}/copilot/widgets/stress_test`; body = { scenario };
        } else if (cmd === "sectors" || cmd === "rotation") {
          url = `${API}/copilot/widgets/sector_rotation`; body = {};
        } else if (cmd === "overlap") {
          const codes = arg ? arg.split(",").map((s) => s.trim()).filter(Boolean) : [];
          url = `${API}/copilot/widgets/overlap_reveal`; body = { scheme_codes: codes.length ? codes : null };
        } else {
          throw new Error(`Unknown command: /${cmd}. Try /fundcard, /market, /compare, /sip, /rebalance, /tax, /stress, /sectors, /overlap.`);
        }
        const r = await axios.post(url, body, { withCredentials: true });
        const envelope = r.data;
        setMessages((prev) => [
          ...prev,
          {
            message_id: `msg_widget_${Date.now()}`,
            role: "assistant",
            content: "",
            widget: envelope,
            agent: envelope?.agent,
            created_at: new Date().toISOString(),
          },
        ]);
      } catch (err) {
        const errMsg = err?.response?.data?.detail || err.message || "Command failed";
        setMessages((prev) => [
          ...prev,
          {
            message_id: `msg_err_${Date.now()}`,
            role: "assistant",
            content: `_${errMsg}_`,
            created_at: new Date().toISOString(),
          },
        ]);
      } finally {
        setSending(false);
        inputRef.current?.focus();
      }
      return;
    }

    // ── Determine current-turn agent (Auto-route vs manual override) ──
    let turnAgent = null;
    if (selectedAgentId === "auto") {
      const r = await routeIntent(text);
      turnAgent = resolveAgent(r?.agent) || null;
    } else {
      // Resolve via the shared registry so the label matches the picker.
      turnAgent = resolveAgent(selectedAgentId);
    }
    setCurrentTurnAgent(turnAgent);

    setSending(true);
    setStreaming(true);
    setStreamingContent("");
    setThinkingTool(null);

    const tempUserMsg = { message_id: "temp_user", role: "user", content: text, created_at: new Date().toISOString() };
    setMessages((prev) => [...prev, tempUserMsg]);

    try {
      const controller = new AbortController();
      abortRef.current = controller;

      const response = await fetch(`${API}/chat/stream`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          message: text,
          session_id: activeSessionId,
          model: selectedModelId,
          agent_id: turnAgent?.id || null,
          ...(v2Holdings?.length > 0 && {
            portfolio_count: v2Holdings.length,
          }),
        }),
        credentials: "include",
        signal: controller.signal,
      });

      if (!response.ok) {
        throw new Error(`HTTP ${response.status}`);
      }

      const reader = response.body.getReader();
      const decoder = new TextDecoder();
      let accumulated = "";
      let metaReceived = false;
      let aiMsgId = "";
      let tokenQueue = [];
      let rendering = false;
      let pendingWidget = null; // set when server emits a widget SSE event
      let routedAgent = null;   // populated from the 'route' SSE event
      let firstTokenSeen = false;
      // Transitional guard: if the backend ever prepends a routing JSON
      // envelope to the first token (older builds did this), strip it so it
      // never leaks into the rendered bubble. Safe to remove once all
      // backends emit a dedicated 'route' event.
      const LEADING_ROUTE_JSON = /^\s*\{[^}]*"agent"\s*:\s*"[^"]+"[^}]*\}\s*/;

      const renderTokens = () => {
        if (rendering || tokenQueue.length === 0) return;
        rendering = true;
        const renderNext = () => {
          if (tokenQueue.length === 0) { rendering = false; return; }
          const tk = tokenQueue.shift();
          accumulated += tk;
          setStreamingContent(accumulated);
          setTimeout(renderNext, 18);
        };
        renderNext();
      };

      while (true) {
        const { done, value } = await reader.read();
        if (done) break;

        const text_chunk = decoder.decode(value, { stream: true });
        const lines = text_chunk.split("\n");

        for (const line of lines) {
          if (!line.startsWith("data: ")) continue;
          try {
            const data = JSON.parse(line.slice(6));

            if (data.type === "meta") {
              metaReceived = true;
              aiMsgId = data.ai_msg_id;
              setMessages((prev) =>
                prev.map((m) => m.message_id === "temp_user"
                  ? { ...m, message_id: data.user_msg_id }
                  : m
                )
              );
            } else if (data.type === "thinking") {
              setThinkingTool(data.status === "start" ? (data.tool || null) : null);
            } else if (data.type === "route") {
              // Backend has classified the user's intent and chosen an agent.
              // Stamp the bubble's agent ribbon with the routed agent rather
              // than the picker default.
              routedAgent = resolveAgent({
                id: data.agent,
                confidence: typeof data.confidence === "number"
                  ? Math.round(data.confidence * 100)
                  : undefined,
              });
              setCurrentTurnAgent(routedAgent);
            } else if (data.type === "token") {
              setThinkingTool(null); // tool done once tokens start
              let content = data.content;
              if (!firstTokenSeen) {
                firstTokenSeen = true;
                content = content.replace(LEADING_ROUTE_JSON, "");
                if (!content) continue;
              }
              tokenQueue.push(content);
              renderTokens();
            } else if (data.type === "widget") {
              // Agent produced a structured widget — store it and attach to
              // the final message when the done event fires. The renderer
              // reads envelope.data.*, so keep widget fields under .data.
              pendingWidget = {
                kind: data.widget_type,
                data: data.data || {},
                ...(data.title ? { title: data.title } : {}),
                ...(data.freshness ? { freshness: data.freshness } : {}),
                ...(data.agent ? { agent: data.agent } : {}),
              };
            } else if (data.type === "done" || data.type === "error") {
              // Flush remaining tokens
              const remaining = tokenQueue.join("");
              tokenQueue = [];
              let finalContent = data.content || (accumulated + remaining);
              // Defensive: strip any surviving routing JSON envelope.
              finalContent = finalContent.replace(LEADING_ROUTE_JSON, "");
              const finalFollowUps = Array.isArray(data.follow_ups) ? data.follow_ups.slice(0, 3) : [];
              // Small delay to let last tokens render
              await new Promise(r => setTimeout(r, 200));
              setMessages((prev) => [
                ...prev,
                {
                  message_id: aiMsgId || `msg_stream_${Date.now()}`,
                  role: "assistant",
                  content: finalContent,
                  agent: routedAgent || turnAgent,
                  ...(pendingWidget ? { widget: pendingWidget } : {}),
                  ...(finalFollowUps.length > 0 ? { follow_ups: finalFollowUps } : {}),
                  created_at: new Date().toISOString(),
                },
              ]);
              setStreamingContent("");
              setStreaming(false);
              setCurrentTurnAgent(null);
              setThinkingTool(null);
              pendingWidget = null;
            }
          } catch {
            // skip malformed SSE lines
          }
        }
      }

      fetchSessions();
    } catch (err) {
      if (err.name === "AbortError") return;
      console.error("Stream failed, falling back to batch", err);
      // Fallback to non-streaming
      try {
        const res = await axios.post(
          `${API}/chat/send`,
          { message: text, session_id: activeSessionId },
          { withCredentials: true }
        );
        setMessages((prev) => {
          const filtered = prev.filter((m) => m.message_id !== "temp_user");
          return [...filtered, res.data.user_message, res.data.ai_message];
        });
        fetchSessions();
      } catch {
        setMessages((prev) => prev.filter((m) => m.message_id !== "temp_user"));
      }
    } finally {
      setSending(false);
      setStreaming(false);
      setStreamingContent("");
      abortRef.current = null;
      inputRef.current?.focus();
      // Refresh suggestions after a message completes — portfolio signals may have shifted
      fetchSuggestedPrompts();
    }
  }, [sending, streaming, activeSessionId, selectedAgentId, selectedModelId, routeIntent, fetchSessions, fetchSuggestedPrompts]);

  const handleSend = (e) => {
    if (e) e.preventDefault();
    return sendMessageWithText(input);
  };

  const handleQuickAction = (prompt) => {
    setInput(prompt);
    setTimeout(() => {
      const fakeEvent = { preventDefault: () => {} };
      setInput(prompt);
      // Use a callback to send after state update
      setTimeout(() => {
        inputRef.current?.focus();
      }, 50);
    }, 0);
  };

  const handleRegenerate = useCallback(
    (prevUserText) => {
      if (!prevUserText || sending || streaming) return;
      sendMessageWithText(prevUserText);
    },
    [sending, streaming, sendMessageWithText],
  );

  const handleMessageFeedback = useCallback((message, rating) => {
    // Fire-and-forget feedback POST. Failures are non-blocking — the UI
    // still records the local "rated" state so the user gets feedback.
    axios
      .post(
        `${API}/copilot/feedback`,
        {
          message_id: message.message_id,
          session_id: activeSessionId,
          rating,
          agent_id: message.agent?.id || null,
        },
        { withCredentials: true },
      )
      .catch(() => {
        /* ignore */
      });
  }, [activeSessionId]);

  const handleClear = async () => {
    try {
      const url = activeSessionId
        ? `${API}/chat/clear?session_id=${activeSessionId}`
        : `${API}/chat/clear`;
      await axios.delete(url, { withCredentials: true });
      setMessages([]);
      if (activeSessionId) {
        setSessions((prev) => prev.filter((s) => s.session_id !== activeSessionId));
        setActiveSessionId(null);
      } else {
        setSessions([]);
      }
    } catch {
      // ignore
    }
  };

  const intentQuestions = [
    { text: "How can I reduce my portfolio risk?", icon: Shield, color: "text-blue-600 bg-blue-50 dark:bg-blue-900/20" },
    { text: "Where should I invest \u20b91 lakh?", icon: TrendingUp, color: "text-emerald-600 bg-emerald-50 dark:bg-emerald-900/20" },
    { text: "Analyze my portfolio performance", icon: BarChart3, color: "text-violet-600 bg-violet-50 dark:bg-violet-900/20" },
    { text: "What changes will improve my returns?", icon: Zap, color: "text-amber-600 bg-amber-50 dark:bg-amber-900/20" },
  ];

  // Map backend icon-string → lucide component
  const PROMPT_ICONS = {
    Wrench, Layers, Shield, ArrowRightCircle, TrendingUp,
    BarChart3, AlertTriangle, Zap, Lightbulb, Target,
  };

  // Map backend color-name → Tailwind classes (bg/text/border for light + dark)
  const PROMPT_COLORS = {
    rose:    { bg: "bg-rose-50 dark:bg-rose-950/30", text: "text-rose-700 dark:text-rose-300", border: "border-rose-200 dark:border-rose-900", hover: "hover:bg-rose-100 dark:hover:bg-rose-900/40" },
    purple:  { bg: "bg-purple-50 dark:bg-purple-950/30", text: "text-purple-700 dark:text-purple-300", border: "border-purple-200 dark:border-purple-900", hover: "hover:bg-purple-100 dark:hover:bg-purple-900/40" },
    sky:     { bg: "bg-sky-50 dark:bg-sky-950/30", text: "text-sky-700 dark:text-sky-300", border: "border-sky-200 dark:border-sky-900", hover: "hover:bg-sky-100 dark:hover:bg-sky-900/40" },
    amber:   { bg: "bg-amber-50 dark:bg-amber-950/30", text: "text-amber-700 dark:text-amber-300", border: "border-amber-200 dark:border-amber-900", hover: "hover:bg-amber-100 dark:hover:bg-amber-900/40" },
    emerald: { bg: "bg-emerald-50 dark:bg-emerald-950/30", text: "text-emerald-700 dark:text-emerald-300", border: "border-emerald-200 dark:border-emerald-900", hover: "hover:bg-emerald-100 dark:hover:bg-emerald-900/40" },
    violet:  { bg: "bg-violet-50 dark:bg-violet-950/30", text: "text-violet-700 dark:text-violet-300", border: "border-violet-200 dark:border-violet-900", hover: "hover:bg-violet-100 dark:hover:bg-violet-900/40" },
    red:     { bg: "bg-red-50 dark:bg-red-950/30", text: "text-red-700 dark:text-red-300", border: "border-red-200 dark:border-red-900", hover: "hover:bg-red-100 dark:hover:bg-red-900/40" },
    indigo:  { bg: "bg-indigo-50 dark:bg-indigo-950/30", text: "text-indigo-700 dark:text-indigo-300", border: "border-indigo-200 dark:border-indigo-900", hover: "hover:bg-indigo-100 dark:hover:bg-indigo-900/40" },
    yellow:  { bg: "bg-yellow-50 dark:bg-yellow-950/30", text: "text-yellow-700 dark:text-yellow-300", border: "border-yellow-200 dark:border-yellow-900", hover: "hover:bg-yellow-100 dark:hover:bg-yellow-900/40" },
    teal:    { bg: "bg-teal-50 dark:bg-teal-950/30", text: "text-teal-700 dark:text-teal-300", border: "border-teal-200 dark:border-teal-900", hover: "hover:bg-teal-100 dark:hover:bg-teal-900/40" },
  };

  // Click a suggested prompt → auto-send it as the user's message
  const runSuggestedPrompt = async (prompt) => {
    if (streaming) return;
    setInput("");
    // Fire the normal send path
    await sendMessageWithText(prompt.query);
  };

  const formatTime = (dateStr) => {
    const d = new Date(dateStr);
    const now = new Date();
    const diff = now - d;
    if (diff < 86400000) return d.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
    if (diff < 604800000) return d.toLocaleDateString([], { weekday: "short" });
    return d.toLocaleDateString([], { month: "short", day: "numeric" });
  };

  const activeSession = sessions.find((s) => s.session_id === activeSessionId);

  return (
    <div data-testid="chat-view" className={v2Mode ? "flex flex-col h-full" : "h-[calc(100vh-8rem)] md:h-[calc(100vh-6rem)] flex gap-4 relative"}>

      {/* ── V2 top bar (clear + history + session title) ─────────────────── */}
      {v2Mode && (
        <div className="shrink-0 flex items-center justify-between px-1 pb-3 gap-3">
          {/* History toggle + session title */}
          <div className="flex items-center gap-2 min-w-0">
            <button
              onClick={() => setShowV2History((v) => !v)}
              className={cn(
                "flex items-center gap-1.5 h-8 px-3 rounded-lg text-xs font-semibold transition-all border shrink-0",
                showV2History
                  ? "bg-indigo-500/15 border-indigo-500/30 text-indigo-400"
                  : "bg-white/5 border-white/10 text-white/50 hover:text-white hover:bg-white/10"
              )}
              title="Chat history"
            >
              <Clock className="w-3.5 h-3.5" />
              History
              {sessions.length > 0 && (
                <span className="ml-0.5 text-[9px] font-bold bg-white/10 px-1.5 py-0.5 rounded-full">
                  {sessions.length}
                </span>
              )}
            </button>
            {activeSession && (
              <p className="text-xs text-white/30 truncate min-w-0">
                {activeSession.title || "Untitled"}
              </p>
            )}
          </div>

          {/* Right actions */}
          <div className="flex items-center gap-2 shrink-0">
            <button
              onClick={handleNewSession}
              className="flex items-center gap-1.5 h-8 px-3 rounded-lg text-xs font-semibold bg-indigo-600/20 border border-indigo-500/30 text-indigo-400 hover:bg-indigo-600/30 transition-all"
            >
              <Plus className="w-3.5 h-3.5" />
              New Chat
            </button>
            {messages.length > 0 && (
              <button
                data-testid="clear-chat-button"
                onClick={handleClear}
                className="flex items-center gap-1.5 h-8 px-3 rounded-lg text-xs font-semibold bg-rose-500/10 border border-rose-500/20 text-rose-400 hover:bg-rose-500/20 transition-all"
              >
                <Trash2 className="w-3.5 h-3.5" />
                Clear
              </button>
            )}
          </div>
        </div>
      )}

      {/* ── Row: [v2 history?] + [v1 sidebar?] + [chat] ─────────────────── */}
      <div className={v2Mode ? "flex flex-1 min-h-0 gap-3" : "contents"}>

        {/* V2 sliding history panel */}
        {v2Mode && (
          <AnimatePresence>
            {showV2History && (
              <motion.div
                key="v2-history"
                initial={{ width: 0, opacity: 0 }}
                animate={{ width: 220, opacity: 1 }}
                exit={{ width: 0, opacity: 0 }}
                transition={{ duration: 0.2, ease: [0.16, 1, 0.3, 1] }}
                className="shrink-0 flex flex-col bg-[#141414] border border-white/5 rounded-2xl overflow-hidden"
                style={{ minWidth: 0 }}
              >
                <div className="p-3 border-b border-white/5 shrink-0">
                  <p className="text-[9px] font-bold uppercase tracking-[0.2em] text-white/30 px-1">
                    Chat History
                  </p>
                </div>
                <div
                  className="flex-1 overflow-y-auto p-2 space-y-0.5"
                  style={{ scrollbarWidth: "thin", scrollbarColor: "rgba(255,255,255,0.06) transparent" }}
                >
                  {sessions.length === 0 ? (
                    <div className="flex flex-col items-center justify-center py-10 text-center px-4">
                      <MessageSquare className="w-6 h-6 text-white/10 mb-3" strokeWidth={1.5} />
                      <p className="text-xs text-white/20">No conversations yet</p>
                    </div>
                  ) : (
                    sessions.map((session) => (
                      <div
                        key={session.session_id}
                        onClick={() => { handleSwitchSession(session.session_id); }}
                        className={cn(
                          "w-full flex items-center gap-2 px-2.5 py-2 rounded-lg cursor-pointer group transition-all",
                          activeSessionId === session.session_id
                            ? "bg-indigo-500/15 border border-indigo-500/20"
                            : "hover:bg-white/5 border border-transparent"
                        )}
                      >
                        {session.pinned
                          ? <Pin className="w-3 h-3 text-indigo-400 shrink-0" strokeWidth={1.5} />
                          : <MessageSquare className="w-3 h-3 text-white/20 shrink-0 group-hover:text-white/40" strokeWidth={1.5} />
                        }
                        <div className="flex-1 min-w-0">
                          <p className={cn(
                            "text-xs truncate",
                            activeSessionId === session.session_id ? "text-white font-semibold" : "text-white/50 group-hover:text-white/80"
                          )}>
                            {session.title || "Untitled"}
                          </p>
                          <p className="text-[9px] text-white/20 mt-0.5">{formatTime(session.updated_at || session.created_at)}</p>
                        </div>
                        <button
                          onClick={(e) => { e.stopPropagation(); handleDeleteSession(session.session_id); }}
                          className="opacity-0 group-hover:opacity-100 p-0.5 hover:text-rose-400 text-white/20 transition-all shrink-0"
                          title="Delete"
                        >
                          <Trash2 className="w-3 h-3" />
                        </button>
                      </div>
                    ))
                  )}
                </div>
              </motion.div>
            )}
          </AnimatePresence>
        )}

        {/* V1 sliding sidebar */}
        <AnimatePresence>
          {!v2Mode && showSidebar && (
            <>
              {/* Mobile backdrop */}
              <div
                className="fixed inset-0 bg-black/30 z-30 md:hidden"
                onClick={() => setShowSidebar(false)}
              />
              <motion.div
                initial={{ width: 0, opacity: 0 }}
                animate={{ width: 260, opacity: 1 }}
                exit={{ width: 0, opacity: 0 }}
                transition={{ duration: 0.2 }}
                className="flex-shrink-0 flex flex-col h-full fixed md:relative top-0 left-0 z-40 md:z-auto bg-transparent md:bg-transparent"
                style={{ maxWidth: 260 }}
              >
                <Card className="flex-1 bg-white dark:bg-slate-900 border-slate-100 dark:border-slate-800 rounded-2xl shadow-none overflow-hidden flex flex-col">
                  <div className="p-3 border-b border-slate-100 dark:border-slate-800">
                    <Button
                      data-testid="new-conversation-button"
                      onClick={handleNewSession}
                      className="w-full bg-emerald-600 hover:bg-emerald-700 text-white rounded-xl h-9 text-sm"
                    >
                      <Plus className="w-4 h-4 mr-2" strokeWidth={2} />
                      New Chat
                    </Button>
                  </div>
                  <ScrollArea className="flex-1 p-2">
                    {sessions.length === 0 ? (
                      <div className="text-center py-8 text-xs text-slate-400">
                        <Clock className="w-5 h-5 mx-auto mb-2 opacity-40" />
                        No conversations yet
                      </div>
                    ) : (
                      <>
                        {sessions.some((s) => s.pinned) && (
                          <div className="mb-1">
                            <div className="px-3 py-1 text-[10px] uppercase tracking-wider font-semibold text-slate-400">
                              Pinned
                            </div>
                            <div className="space-y-0.5">
                              {sessions.filter((s) => s.pinned).map((session) => (
                                <SessionItem
                                  key={session.session_id}
                                  session={session}
                                  isActive={activeSessionId === session.session_id}
                                  onClick={handleSwitchSession}
                                  onDelete={handleDeleteSession}
                                  onPin={handlePinSession}
                                  onRename={handleRenameSession}
                                />
                              ))}
                            </div>
                          </div>
                        )}
                        {sessions.some((s) => !s.pinned) && (
                          <div>
                            {sessions.some((s) => s.pinned) && (
                              <div className="px-3 py-1 text-[10px] uppercase tracking-wider font-semibold text-slate-400">
                                Recent
                              </div>
                            )}
                            <div className="space-y-0.5">
                              {sessions.filter((s) => !s.pinned).map((session) => (
                                <SessionItem
                                  key={session.session_id}
                                  session={session}
                                  isActive={activeSessionId === session.session_id}
                                  onClick={handleSwitchSession}
                                  onDelete={handleDeleteSession}
                                  onPin={handlePinSession}
                                  onRename={handleRenameSession}
                                />
                              ))}
                            </div>
                          </div>
                        )}
                      </>
                    )}
                  </ScrollArea>
                </Card>
              </motion.div>
            </>
          )}
        </AnimatePresence>

        {/* Main Chat Area */}
        <div className={v2Mode ? "flex-1 flex flex-col min-w-0 min-h-0" : "flex-1 flex flex-col min-w-0"}>
          {/* Header — hidden in V2 mode (V2Layout owns the header) */}
          {!v2Mode && (
          <div className="flex items-center justify-between mb-4 gap-2">
          <div className="flex items-center gap-2 sm:gap-3 min-w-0">
            <Button
              data-testid="toggle-chat-sidebar"
              variant="outline"
              onClick={() => setShowSidebar(!showSidebar)}
              className="rounded-xl border-slate-200 dark:border-slate-700 h-9 w-9 p-0 flex-shrink-0"
            >
              {showSidebar ? <ChevronLeft className="w-4 h-4" /> : <MessageSquare className="w-4 h-4" />}
            </Button>
            <div className="min-w-0">
              <h1 className="text-lg sm:text-2xl md:text-3xl font-medium tracking-tight text-slate-900 dark:text-white truncate" style={{ fontFamily: "'Outfit', sans-serif" }}>
                AI Financial Advisor
              </h1>
              <p className="text-xs sm:text-sm text-slate-500 dark:text-slate-400 mt-0.5 hidden sm:block">Ask anything about your investments</p>
            </div>
          </div>
          {messages.length > 0 && (
            <Button
              data-testid="clear-chat-button"
              variant="outline"
              onClick={handleClear}
              className="rounded-xl border-slate-200 dark:border-slate-700 text-slate-500 dark:text-slate-400 hover:text-red-500 hover:border-red-200 flex-shrink-0 px-2 sm:px-4"
            >
              <Trash2 className="w-4 h-4 sm:mr-2" strokeWidth={1.5} />
              <span className="hidden sm:inline">Clear</span>
            </Button>
          )}
        </div>
        )}

        {/* Messages */}
        <Card className={v2Mode
          ? "flex-1 bg-transparent border-transparent shadow-none overflow-hidden flex flex-col"
          : "flex-1 bg-white dark:bg-slate-900 border-slate-100 dark:border-slate-800 rounded-2xl shadow-none overflow-hidden flex flex-col"
        }>
          <ScrollArea className="flex-1 p-3 sm:p-6">
            {loadingMessages ? (
              <div className="space-y-6 py-4">
                <ChatMessageSkeleton />
                <ChatMessageSkeleton />
              </div>
            ) : (v2Mode && !messages.some(m => m.role === "assistant")) ? (
              /* ── V2: keep persona cards visible until AI responds ── */
              <>
                <V2CopilotWelcome
                  personaId={v2PersonaId}
                  analytics={v2Analytics}
                  workspace={v2Workspace}
                  onAsk={sendMessageWithText}
                  onSwitchSession={handleSwitchSession}
                  recentSessions={sessions}
                  suggestedPrompts={[...tieredPrompts.primary, ...tieredPrompts.secondary]}
                  suggestionsLoading={suggestionsLoading}
                  streaming={streaming}
                />
                {(messages.length > 0 || streaming) && (
                  <div className="mt-6 pt-6 border-t border-white/5 space-y-4">
                    {messages.map(msg => msg.role === "user" ? (
                      <div key={msg.message_id} className="flex gap-3 justify-end">
                        <div className="max-w-[85%] sm:max-w-[75%] chat-user-bubble px-4 py-3 text-sm leading-relaxed whitespace-pre-wrap shadow-sm">
                          {msg.content}
                        </div>
                        <div className="relative w-8 h-8 flex-shrink-0 mt-1">
                          <div className="absolute inset-0 rounded-xl bg-gradient-to-br from-emerald-500 to-emerald-700 shadow-md shadow-emerald-500/20" />
                          <div className="absolute inset-0 flex items-center justify-center">
                            <User className="w-4 h-4 text-white" strokeWidth={1.75} />
                          </div>
                        </div>
                      </div>
                    ) : null)}
                    {streaming && !streamingContent && <StreamingIndicator toolName={thinkingTool} />}
                    {streaming && streamingContent && (
                      <motion.div initial={{ opacity: 0, y: 8 }} animate={{ opacity: 1, y: 0 }} className="flex gap-3 justify-start">
                        <div className="w-8 h-8 bg-emerald-900/20 rounded-xl flex-shrink-0 flex items-center justify-center mt-1">
                          <Bot className="w-4 h-4 text-emerald-600 animate-pulse" strokeWidth={1.5} />
                        </div>
                        <div className="max-w-[85%] sm:max-w-[75%] chat-ai-bubble chat-markdown px-4 py-3 text-sm leading-relaxed">
                          <MarkdownMessage content={streamingContent} />
                          <span className="inline-block w-1.5 h-4 bg-emerald-500 animate-pulse ml-0.5 rounded-sm" />
                        </div>
                      </motion.div>
                    )}
                    <div ref={messagesEndRef} />
                  </div>
                )}
              </>
            ) : messages.length === 0 && !streaming ? (
              <div className="flex flex-col items-center justify-start h-full py-8 px-2 overflow-y-auto">
                <div className="w-14 h-14 bg-emerald-50 dark:bg-emerald-900/20 rounded-2xl flex items-center justify-center mb-4">
                  <Bot className="w-7 h-7 text-emerald-600" strokeWidth={1.5} />
                </div>
                <h3 className="text-lg font-semibold text-slate-900 dark:text-white text-center mb-1" style={{ fontFamily: "'Outfit', sans-serif" }}>
                  {tieredPrompts.journey === "first_time" ? "Welcome — let me start you off right." :
                   tieredPrompts.journey === "post_action" ? "You have pending actions. What next?" :
                   "What should we tackle today?"}
                </h3>
                <p className="text-sm text-slate-500 dark:text-slate-400 mb-5 max-w-md text-center">
                  Tap a decision below to get a direct answer — no typing needed.
                </p>
                {suggestionsLoading ? (
                  <div className="flex items-center gap-2 text-slate-400 text-xs"><RefreshCw className="w-3.5 h-3.5 animate-spin" /> Analysing your portfolio…</div>
                ) : (tieredPrompts.primary.length === 0 && tieredPrompts.secondary.length === 0) ? (
                  <div className="grid grid-cols-1 sm:grid-cols-2 gap-3 max-w-lg w-full">
                    {intentQuestions.map((q) => (
                      <button
                        key={q.text}
                        data-testid={`intent-${q.text.slice(0, 15).replace(/\s/g, '-').toLowerCase()}`}
                        onClick={() => sendMessageWithText(q.text)}
                        className="flex items-center gap-3 text-left text-sm text-slate-600 dark:text-slate-300 bg-white dark:bg-slate-800 hover:bg-slate-50 dark:hover:bg-slate-700/50 p-3.5 rounded-xl border border-slate-100 dark:border-slate-700 hover:border-emerald-200 dark:hover:border-emerald-800 transition-all duration-200 group"
                      >
                        <div className={`w-9 h-9 rounded-lg flex items-center justify-center flex-shrink-0 ${q.color}`}>
                          <q.icon className="w-4 h-4" strokeWidth={1.5} />
                        </div>
                        <span className="group-hover:text-slate-900 dark:group-hover:text-white transition-colors">{q.text}</span>
                      </button>
                    ))}
                  </div>
                ) : (
                  <div className="w-full max-w-xl space-y-4">
                    {/* ── 5-category filter chips (when persona prompts are enabled) ── */}
                    {tieredPrompts.persona_prompts_enabled && (
                      <div className="flex flex-wrap gap-2 justify-center pb-2">
                        {[
                          { key: null, label: "All" },
                          { key: "portfolio_health", label: "Portfolio Health" },
                          { key: "performance", label: "Performance" },
                          { key: "risk_diversification", label: "Risk & Diversification" },
                          { key: "tax", label: "Tax" },
                          { key: "goal_planning", label: "Goal Planning" },
                        ].map((chip) => {
                          const isActive = activeCategoryFilter === chip.key;
                          return (
                            <button
                              key={chip.key || "all"}
                              data-testid={`copilot-category-chip-${chip.key || "all"}`}
                              onClick={() => {
                                setActiveCategoryFilter(chip.key);
                                fetchSuggestedPrompts(chip.key);
                              }}
                              className={`text-xs font-medium px-3 py-1.5 rounded-full border transition-colors ${
                                isActive
                                  ? "bg-emerald-600 text-white border-emerald-600"
                                  : "bg-white dark:bg-slate-800 text-slate-600 dark:text-slate-300 border-slate-200 dark:border-slate-700 hover:border-emerald-300 dark:hover:border-emerald-700"
                              }`}
                            >
                              {chip.label}
                            </button>
                          );
                        })}
                      </div>
                    )}
                    {/* ── PRIMARY (hero) ───────────────────────────── */}
                    {tieredPrompts.primary.map((p) => {
                      const Icon = PROMPT_ICONS[p.icon] || Lightbulb;
                      const c = PROMPT_COLORS[p.color] || PROMPT_COLORS.emerald;
                      return (
                        <CopilotPromptCard
                          key={p.id}
                          prompt={p}
                          variant="hero"
                          Icon={Icon}
                          colorClasses={c}
                          disabled={streaming}
                          onClick={() => runSuggestedPrompt(p)}
                        />
                      );
                    })}

                    {/* ── SECONDARY ─────────────────────────────────── */}
                    {tieredPrompts.secondary.length > 0 && (
                      <div className="grid grid-cols-1 gap-2">
                        {tieredPrompts.secondary.map((p) => {
                          const Icon = PROMPT_ICONS[p.icon] || Lightbulb;
                          const c = PROMPT_COLORS[p.color] || PROMPT_COLORS.emerald;
                          return (
                            <CopilotPromptCard
                              key={p.id}
                              prompt={p}
                              variant="compact"
                              Icon={Icon}
                              colorClasses={c}
                              disabled={streaming}
                              onClick={() => runSuggestedPrompt(p)}
                            />
                          );
                        })}
                      </div>
                    )}

                    {/* ── ADVANCED (collapsed by default) ───────────── */}
                    {tieredPrompts.advanced.length > 0 && (
                      <div className="border-t border-slate-100 dark:border-slate-800 pt-3">
                        <button
                          data-testid="copilot-prompts-advanced-toggle"
                          onClick={() => setShowAdvanced((v) => !v)}
                          className="w-full flex items-center justify-between text-xs font-semibold text-slate-500 dark:text-zinc-400 hover:text-slate-800 dark:hover:text-white uppercase tracking-wider px-1"
                        >
                          <span>Advanced · for deeper dives</span>
                          {showAdvanced ? <Minimize2 className="w-3.5 h-3.5" /> : <Maximize2 className="w-3.5 h-3.5" />}
                        </button>
                        {showAdvanced && (
                          <div className="grid grid-cols-1 sm:grid-cols-2 gap-2 mt-3">
                            {tieredPrompts.advanced.map((p) => {
                              const Icon = PROMPT_ICONS[p.icon] || Lightbulb;
                              const c = PROMPT_COLORS[p.color] || PROMPT_COLORS.emerald;
                              return (
                                <CopilotPromptCard
                                  key={p.id}
                                  prompt={p}
                                  variant="tiny"
                                  Icon={Icon}
                                  colorClasses={c}
                                  disabled={streaming}
                                  onClick={() => runSuggestedPrompt(p)}
                                />
                              );
                            })}
                          </div>
                        )}
                      </div>
                    )}
                  </div>
                )}
              </div>
            ) : (
              <div className="space-y-4">
                <AnimatePresence initial={false}>
                  {messages.map((msg, idx) => {
                    // Find the nearest preceding user message for context
                    const prevUser = (() => {
                      for (let j = idx - 1; j >= 0; j--) {
                        if (messages[j].role === "user") return messages[j].content;
                      }
                      return "";
                    })();
                    const isUser = msg.role === "user";
                    return (
                    <motion.div
                      key={msg.message_id}
                      initial={{ opacity: 0, y: 12, scale: 0.98 }}
                      animate={{ opacity: 1, y: 0, scale: 1 }}
                      transition={{ duration: 0.28, ease: [0.16, 1, 0.3, 1] }}
                      layout
                      className={`flex gap-3 ${isUser ? "justify-end" : "justify-start"}`}
                    >
                      {!isUser && (
                        <div className="relative w-8 h-8 flex-shrink-0 mt-1">
                          <div className="absolute inset-0 rounded-xl bg-gradient-to-br from-emerald-50 to-emerald-100 dark:from-emerald-900/30 dark:to-emerald-800/30" />
                          <div className="absolute inset-0 rounded-xl ring-1 ring-emerald-200/60 dark:ring-emerald-700/40" />
                          <div className="absolute inset-0 flex items-center justify-center">
                            <Bot className="w-4 h-4 text-emerald-600 dark:text-emerald-400" strokeWidth={1.75} />
                          </div>
                        </div>
                      )}
                      <div className={`max-w-[85%] sm:max-w-[75%]`}>
                        {/* Agent ribbon — Phase B (above bubble) */}
                        {!isUser && msg.agent && (
                          <div className="mb-1.5">
                            <AgentRibbon agent={msg.agent} compact />
                          </div>
                        )}
                        {/* Embedded widget (Phase B) — if present, render the
                            envelope; bubble content shows alongside as prose. */}
                        {!isUser && msg.widget ? (
                          <div data-testid={`msg-widget-${msg.message_id}`}>
                            <WidgetRenderer
                              envelope={msg.widget}
                              embedded="chat"
                              onAction={(action, payload) => {
                                if (action === "suggestion" && payload?.suggestion) {
                                  sendMessageWithText(payload.suggestion);
                                }
                              }}
                            />
                            {msg.content && (
                              <div className="chat-ai-bubble chat-markdown shadow-sm px-4 py-3 text-sm leading-relaxed mt-2">
                                <MarkdownMessage content={msg.content} />
                              </div>
                            )}
                          </div>
                        ) : (
                          <motion.div
                            initial={{ opacity: 0 }}
                            animate={{ opacity: 1 }}
                            transition={{ duration: 0.35, delay: 0.05 }}
                            className={`px-4 py-3 text-sm leading-relaxed ${
                              isUser
                                ? "chat-user-bubble whitespace-pre-wrap shadow-sm"
                                : "chat-ai-bubble chat-markdown shadow-sm"
                            }`}
                          >
                            {!isUser ? (
                              <MarkdownMessage content={msg.content} />
                            ) : (
                              msg.content
                            )}
                          </motion.div>
                        )}
                        {/* Save-as-Plan CTA (high-intent responses only) */}
                        {!isUser && msg.message_id !== "temp_ai" && shouldShowSavePlan(msg.content, prevUser) && (
                          <SaveAsPlanCard onNavigateToPlanBoard={onNavigateToPlanBoard} />
                        )}
                        {/* Universal toolbar — copy, regenerate, feedback */}
                        {!isUser && msg.message_id !== "temp_ai" && (
                          <MessageToolbar
                            message={msg}
                            prevUserText={prevUser}
                            onRegenerate={handleRegenerate}
                            onFeedback={handleMessageFeedback}
                          />
                        )}
                        {/* Inline follow-up suggestions emitted by the backend */}
                        {!isUser && msg.message_id !== "temp_ai" && Array.isArray(msg.follow_ups) && msg.follow_ups.length > 0 && (
                          <div className="flex flex-wrap gap-1.5 mt-2" data-testid={`msg-followups-${msg.message_id}`}>
                            {msg.follow_ups.slice(0, 3).map((fu, i) => (
                              <button
                                key={`${msg.message_id}-fu-${i}`}
                                type="button"
                                onClick={() => sendMessageWithText(fu)}
                                disabled={streaming}
                                className="text-[11px] font-medium px-2.5 py-1 rounded-full border border-emerald-200/60 dark:border-emerald-700/40 bg-emerald-50/60 dark:bg-emerald-900/20 text-emerald-700 dark:text-emerald-300 hover:bg-emerald-100 dark:hover:bg-emerald-900/40 disabled:opacity-60"
                              >
                                {fu}
                              </button>
                            ))}
                          </div>
                        )}
                        {/* Context-aware next-step prompts (keyword-derived) */}
                        {!isUser && msg.message_id !== "temp_ai" && (
                          <QuickActions content={msg.content} onAction={handleQuickAction} />
                        )}
                      </div>
                      {isUser && (
                        <div className="relative w-8 h-8 flex-shrink-0 mt-1">
                          <div className="absolute inset-0 rounded-xl bg-gradient-to-br from-emerald-500 to-emerald-700 shadow-md shadow-emerald-500/20" />
                          <div className="absolute inset-0 flex items-center justify-center">
                            <User className="w-4 h-4 text-white" strokeWidth={1.75} />
                          </div>
                        </div>
                      )}
                    </motion.div>
                    );
                  })}
                </AnimatePresence>

                {/* Streaming response */}
                {streaming && streamingContent && (
                  <motion.div
                    initial={{ opacity: 0, y: 8 }}
                    animate={{ opacity: 1, y: 0 }}
                    className="flex gap-3 justify-start"
                  >
                    <div className="w-8 h-8 bg-emerald-50 dark:bg-emerald-900/20 rounded-xl flex-shrink-0 flex items-center justify-center mt-1">
                      <Bot className="w-4 h-4 text-emerald-600 animate-pulse" strokeWidth={1.5} />
                    </div>
                    <div className="max-w-[85%] sm:max-w-[75%] chat-ai-bubble chat-markdown px-4 py-3 text-sm leading-relaxed">
                      <MarkdownMessage content={streamingContent} />
                      <span className="inline-block w-1.5 h-4 bg-emerald-500 animate-pulse ml-0.5 rounded-sm" />
                    </div>
                  </motion.div>
                )}

                {/* Thinking indicator (before first token arrives) */}
                {streaming && !streamingContent && <StreamingIndicator toolName={thinkingTool} />}

                <div ref={messagesEndRef} />
              </div>
            )}
          </ScrollArea>

          {/* Input */}
          <CardContent className={`p-3 sm:p-4 space-y-2.5 ${v2Mode ? "border-t border-white/5" : "border-t border-slate-100 dark:border-slate-800"}`}>
            {/* Persistent smart-prompt chips (dynamic, context-aware) */}
            {messages.length > 0 && !suggestionsLoading && suggestedPrompts.length > 0 && (
              <div className="flex items-center gap-1.5 overflow-x-auto pb-0.5 -mx-1 px-1 scrollbar-thin" data-testid="copilot-chip-strip">
                <span className="text-[10px] font-semibold text-slate-400 dark:text-zinc-500 uppercase tracking-wider whitespace-nowrap pr-1">
                  Ask:
                </span>
                {suggestedPrompts.map((p) => {
                  const Icon = PROMPT_ICONS[p.icon] || Lightbulb;
                  const c = PROMPT_COLORS[p.color] || PROMPT_COLORS.emerald;
                  return (
                    <button
                      key={p.id}
                      data-testid={`copilot-chip-${p.id}`}
                      onClick={() => runSuggestedPrompt(p)}
                      disabled={streaming}
                      title={p.query}
                      className={`flex items-center gap-1.5 text-[11px] font-medium pl-2 pr-2.5 py-1 rounded-full border whitespace-nowrap transition-all ${c.bg} ${c.border} ${c.text} ${c.hover} disabled:opacity-60`}
                    >
                      <Icon className="w-3 h-3" strokeWidth={2} />
                      {p.label}
                      {p.viz?.headline && (
                        <span className={`ml-0.5 text-[10px] font-bold tabular-nums px-1.5 py-0.5 rounded-full bg-white/80 dark:bg-white/10 ${c.text}`}>
                          {p.viz.headline}
                        </span>
                      )}
                    </button>
                  );
                })}
              </div>
            )}
            <form onSubmit={handleSend} className="flex items-center gap-2 sm:gap-3">
              <input
                ref={inputRef}
                data-testid="chat-input"
                value={input}
                onChange={(e) => setInput(e.target.value)}
                placeholder="Ask anything · /fundcard /market /compare /sip /rebalance /tax /stress /sectors /overlap"
                disabled={sending && streaming}
                className="flex-1 bg-slate-50 dark:bg-slate-800 border border-slate-200 dark:border-slate-700 rounded-xl px-4 py-3 text-sm text-slate-900 dark:text-white placeholder:text-slate-400 dark:placeholder:text-slate-500 focus:outline-none focus:border-emerald-500 focus:ring-1 focus:ring-emerald-500 transition-colors"
              />
              <Button
                data-testid="send-message-button"
                type="submit"
                disabled={!input.trim() || (sending && streaming)}
                className="bg-emerald-600 hover:bg-emerald-700 text-white rounded-xl h-11 w-11 p-0 flex-shrink-0"
              >
                <Send className="w-4 h-4" strokeWidth={2} />
              </Button>
            </form>
            {/* Phase B: agent + model pickers, current-turn ribbon */}
            <div className="flex items-center flex-wrap gap-2 mt-1.5">
              <AgentPicker value={selectedAgentId} onChange={setSelectedAgentId} />
              <ModelPicker value={selectedModelId} onChange={setSelectedModelId} />
              {currentTurnAgent && (
                <div className="ml-auto text-[10px] text-slate-400 flex items-center gap-1.5">
                  <span className="cp-shimmer w-1.5 h-1.5 rounded-full" />
                  Handing off to {currentTurnAgent.label}…
                </div>
              )}
            </div>
            <p className="text-[10px] text-slate-400 dark:text-slate-500 mt-2 text-center">
              AI-generated guidance for educational purposes. Consult a SEBI-registered advisor for investment decisions.
            </p>
          </CardContent>
        </Card>
        </div>
      </div>
    </div>
  );
};

export default ChatView;
