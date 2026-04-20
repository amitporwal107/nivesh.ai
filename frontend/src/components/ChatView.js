import React, { useState, useEffect, useRef, useCallback } from "react";
import axios from "axios";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import {
  Send, Trash2, Bot, User, Plus, MessageSquare, ChevronLeft,
  Clock, TrendingUp, Shield, BarChart3, Lightbulb, ArrowRight,
  Zap, RefreshCw, Wrench, Layers, ArrowRightCircle, AlertTriangle, Target,
} from "lucide-react";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { ScrollArea } from "@/components/ui/scroll-area";
import { motion, AnimatePresence } from "framer-motion";
import { ChatMessageSkeleton } from "@/components/ui/skeleton-loaders";

const BACKEND_URL = process.env.REACT_APP_BACKEND_URL;
const API = `${BACKEND_URL}/api`;

const MarkdownMessage = ({ content }) => (
  <ReactMarkdown
    remarkPlugins={[remarkGfm]}
    components={{
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
    }}
  >
    {content}
  </ReactMarkdown>
);

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

/* ── Streaming "thinking" indicator ── */
const StreamingIndicator = () => (
  <div className="flex gap-3 justify-start">
    <div className="w-8 h-8 bg-emerald-50 dark:bg-emerald-900/20 rounded-xl flex-shrink-0 flex items-center justify-center mt-1">
      <Bot className="w-4 h-4 text-emerald-600" strokeWidth={1.5} />
    </div>
    <div className="chat-ai-bubble px-4 py-3">
      <div className="flex items-center gap-2">
        <div className="flex gap-1">
          <span className="w-2 h-2 bg-emerald-500 rounded-full animate-bounce" style={{ animationDelay: "0ms" }} />
          <span className="w-2 h-2 bg-emerald-500 rounded-full animate-bounce" style={{ animationDelay: "150ms" }} />
          <span className="w-2 h-2 bg-emerald-500 rounded-full animate-bounce" style={{ animationDelay: "300ms" }} />
        </div>
        <span className="text-xs text-slate-400 ml-1">Analyzing your portfolio...</span>
      </div>
    </div>
  </div>
);

const SessionItem = ({ session, isActive, onClick, onDelete }) => (
  <div
    data-testid={`chat-session-${session.session_id}`}
    onClick={() => onClick(session.session_id)}
    role="button"
    tabIndex={0}
    className={`w-full text-left px-3 py-2.5 rounded-xl text-sm transition-all duration-200 group flex items-center gap-2 cursor-pointer ${
      isActive
        ? "bg-emerald-50 dark:bg-emerald-900/30 text-emerald-700 dark:text-emerald-400"
        : "text-slate-600 dark:text-slate-400 hover:bg-slate-50 dark:hover:bg-slate-800"
    }`}
  >
    <MessageSquare className="w-3.5 h-3.5 flex-shrink-0" strokeWidth={1.5} />
    <span className="flex-1 truncate">{session.title}</span>
    <button
      data-testid={`delete-session-${session.session_id}`}
      onClick={(e) => { e.stopPropagation(); onDelete(session.session_id); }}
      className="opacity-0 group-hover:opacity-100 p-0.5 hover:text-red-500 transition-opacity"
    >
      <Trash2 className="w-3 h-3" />
    </button>
  </div>
);

const ChatView = () => {
  const [messages, setMessages] = useState([]);
  const [input, setInput] = useState("");
  const [suggestedPrompts, setSuggestedPrompts] = useState([]);
  const [suggestionsLoading, setSuggestionsLoading] = useState(true);
  const [sending, setSending] = useState(false);
  const [streaming, setStreaming] = useState(false);
  const [streamingContent, setStreamingContent] = useState("");
  const [loadingMessages, setLoadingMessages] = useState(true);
  const [sessions, setSessions] = useState([]);
  const [activeSessionId, setActiveSessionId] = useState(null);
  const [showSidebar, setShowSidebar] = useState(typeof window !== "undefined" ? window.innerWidth >= 768 : true);
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

  const fetchSuggestedPrompts = useCallback(async () => {
    setSuggestionsLoading(true);
    try {
      const res = await axios.get(`${API}/copilot/suggested-prompts`, { withCredentials: true });
      setSuggestedPrompts(res.data?.prompts || []);
    } catch (err) {
      // Fallback to empty; user can still type
      setSuggestedPrompts([]);
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
      if (loadedSessions.length > 0) {
        setActiveSessionId(loadedSessions[0].session_id);
        fetchMessages(loadedSessions[0].session_id);
      } else {
        setLoadingMessages(false);
      }
      fetchSuggestedPrompts();
    };
    init();
  }, [fetchSessions, fetchMessages, fetchSuggestedPrompts]);

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

  const sendMessageWithText = useCallback(async (rawText) => {
    const text = (rawText || "").trim();
    if (!text || sending || streaming) return;

    setInput("");
    setSending(true);
    setStreaming(true);
    setStreamingContent("");

    const tempUserMsg = { message_id: "temp_user", role: "user", content: text, created_at: new Date().toISOString() };
    setMessages((prev) => [...prev, tempUserMsg]);

    try {
      const controller = new AbortController();
      abortRef.current = controller;

      const response = await fetch(`${API}/chat/stream`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ message: text, session_id: activeSessionId }),
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
            } else if (data.type === "token") {
              tokenQueue.push(data.content);
              renderTokens();
            } else if (data.type === "done" || data.type === "error") {
              // Flush remaining tokens
              const remaining = tokenQueue.join("");
              tokenQueue = [];
              const finalContent = data.content || (accumulated + remaining);
              // Small delay to let last tokens render
              await new Promise(r => setTimeout(r, 200));
              setMessages((prev) => [
                ...prev,
                { message_id: aiMsgId || `msg_stream_${Date.now()}`, role: "assistant", content: finalContent, created_at: new Date().toISOString() },
              ]);
              setStreamingContent("");
              setStreaming(false);
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
  }, [sending, streaming, activeSessionId, fetchSessions, fetchSuggestedPrompts]);

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

  return (
    <div data-testid="chat-view" className="h-[calc(100vh-8rem)] md:h-[calc(100vh-6rem)] flex gap-4 relative">
      {/* Session Sidebar — overlay on mobile, inline on desktop */}
      <AnimatePresence>
        {showSidebar && (
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
                <div className="space-y-0.5">
                  {sessions.map((session) => (
                    <SessionItem
                      key={session.session_id}
                      session={session}
                      isActive={activeSessionId === session.session_id}
                      onClick={handleSwitchSession}
                      onDelete={handleDeleteSession}
                    />
                  ))}
                  {sessions.length === 0 && (
                    <div className="text-center py-8 text-xs text-slate-400">
                      <Clock className="w-5 h-5 mx-auto mb-2 opacity-40" />
                      No conversations yet
                    </div>
                  )}
                </div>
              </ScrollArea>
            </Card>
          </motion.div>
          </>
        )}
      </AnimatePresence>

      {/* Main Chat Area */}
      <div className="flex-1 flex flex-col min-w-0">
        {/* Header */}
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

        {/* Messages */}
        <Card className="flex-1 bg-white dark:bg-slate-900 border-slate-100 dark:border-slate-800 rounded-2xl shadow-none overflow-hidden flex flex-col">
          <ScrollArea className="flex-1 p-3 sm:p-6">
            {loadingMessages ? (
              <div className="space-y-6 py-4">
                <ChatMessageSkeleton />
                <ChatMessageSkeleton />
              </div>
            ) : messages.length === 0 && !streaming ? (
              <div className="flex flex-col items-center justify-center h-full text-center py-10 px-2">
                <div className="w-14 h-14 bg-emerald-50 dark:bg-emerald-900/20 rounded-2xl flex items-center justify-center mb-5">
                  <Bot className="w-7 h-7 text-emerald-600" strokeWidth={1.5} />
                </div>
                <h3 className="text-lg font-medium text-slate-900 dark:text-white mb-2" style={{ fontFamily: "'Outfit', sans-serif" }}>
                  What would you like to fix today?
                </h3>
                <p className="text-sm text-slate-500 dark:text-slate-400 mb-6 max-w-md">
                  I've looked at your portfolio. Tap any of these to get a direct answer — no typing needed.
                </p>
                {suggestionsLoading ? (
                  <div className="flex items-center gap-2 text-slate-400 text-xs"><RefreshCw className="w-3.5 h-3.5 animate-spin" /> Analysing your portfolio…</div>
                ) : suggestedPrompts.length === 0 ? (
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
                  <div className="grid grid-cols-1 gap-2.5 max-w-lg w-full">
                    {suggestedPrompts.map((p) => {
                      const Icon = PROMPT_ICONS[p.icon] || Lightbulb;
                      const c = PROMPT_COLORS[p.color] || PROMPT_COLORS.emerald;
                      return (
                        <button
                          key={p.id}
                          data-testid={`copilot-prompt-${p.id}`}
                          onClick={() => runSuggestedPrompt(p)}
                          disabled={streaming}
                          className={`group flex items-start gap-3 text-left p-3 rounded-xl border ${c.bg} ${c.border} ${c.hover} transition-all disabled:opacity-60`}
                        >
                          <div className={`w-9 h-9 rounded-lg flex items-center justify-center flex-shrink-0 bg-white/70 dark:bg-white/5 ${c.text}`}>
                            <Icon className="w-4 h-4" strokeWidth={1.8} />
                          </div>
                          <div className="flex-1 min-w-0">
                            <div className="flex items-center justify-between gap-2">
                              <span className={`text-sm font-semibold ${c.text}`}>{p.label}</span>
                              {p.badge && (
                                <span className={`text-[10px] font-semibold px-1.5 py-0.5 rounded-full bg-white/80 dark:bg-white/10 ${c.text} whitespace-nowrap`}>
                                  {p.badge}
                                </span>
                              )}
                            </div>
                            <p className="text-xs text-slate-600 dark:text-slate-400 mt-0.5 line-clamp-2">
                              {p.query}
                            </p>
                          </div>
                          <ArrowRight className={`w-4 h-4 mt-1 ${c.text} opacity-0 group-hover:opacity-100 transition-opacity`} />
                        </button>
                      );
                    })}
                  </div>
                )}
              </div>
            ) : (
              <div className="space-y-4">
                <AnimatePresence initial={false}>
                  {messages.map((msg) => (
                    <motion.div
                      key={msg.message_id}
                      initial={{ opacity: 0, y: 8 }}
                      animate={{ opacity: 1, y: 0 }}
                      transition={{ duration: 0.2 }}
                      className={`flex gap-3 ${msg.role === "user" ? "justify-end" : "justify-start"}`}
                    >
                      {msg.role === "assistant" && (
                        <div className="w-8 h-8 bg-emerald-50 dark:bg-emerald-900/20 rounded-xl flex-shrink-0 flex items-center justify-center mt-1">
                          <Bot className="w-4 h-4 text-emerald-600" strokeWidth={1.5} />
                        </div>
                      )}
                      <div className={`max-w-[85%] sm:max-w-[75%] ${msg.role === "user" ? "" : ""}`}>
                        <div
                          className={`px-4 py-3 text-sm leading-relaxed ${
                            msg.role === "user"
                              ? "chat-user-bubble whitespace-pre-wrap"
                              : "chat-ai-bubble chat-markdown"
                          }`}
                        >
                          {msg.role === "assistant" ? (
                            <MarkdownMessage content={msg.content} />
                          ) : (
                            msg.content
                          )}
                        </div>
                        {/* Action buttons for AI messages */}
                        {msg.role === "assistant" && msg.message_id !== "temp_ai" && (
                          <QuickActions content={msg.content} onAction={handleQuickAction} />
                        )}
                      </div>
                      {msg.role === "user" && (
                        <div className="w-8 h-8 bg-emerald-600 rounded-xl flex-shrink-0 flex items-center justify-center mt-1">
                          <User className="w-4 h-4 text-white" strokeWidth={1.5} />
                        </div>
                      )}
                    </motion.div>
                  ))}
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
                {streaming && !streamingContent && <StreamingIndicator />}

                <div ref={messagesEndRef} />
              </div>
            )}
          </ScrollArea>

          {/* Input */}
          <CardContent className="p-3 sm:p-4 border-t border-slate-100 dark:border-slate-800 space-y-2.5">
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
                      className={`flex items-center gap-1.5 text-[11px] font-medium px-2.5 py-1 rounded-full border whitespace-nowrap transition-all ${c.bg} ${c.border} ${c.text} ${c.hover} disabled:opacity-60`}
                    >
                      <Icon className="w-3 h-3" strokeWidth={2} />
                      {p.label}
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
                placeholder="What would you like to improve about your portfolio?"
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
            <p className="text-[10px] text-slate-400 dark:text-slate-500 mt-2 text-center">
              AI-generated guidance for educational purposes. Consult a SEBI-registered advisor for investment decisions.
            </p>
          </CardContent>
        </Card>
      </div>
    </div>
  );
};

export default ChatView;
