import React, { useState, useEffect, useRef, useCallback } from "react";
import axios from "axios";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import { Send, Trash2, Bot, User, Plus, MessageSquare, ChevronLeft, Clock } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { ScrollArea } from "@/components/ui/scroll-area";
import { motion, AnimatePresence } from "framer-motion";

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

const SessionItem = ({ session, isActive, onClick, onDelete }) => (
  <button
    data-testid={`chat-session-${session.session_id}`}
    onClick={() => onClick(session.session_id)}
    className={`w-full text-left px-3 py-2.5 rounded-xl text-sm transition-all duration-200 group flex items-center gap-2 ${
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
  </button>
);

const ChatView = () => {
  const [messages, setMessages] = useState([]);
  const [input, setInput] = useState("");
  const [sending, setSending] = useState(false);
  const [loadingMessages, setLoadingMessages] = useState(true);
  const [sessions, setSessions] = useState([]);
  const [activeSessionId, setActiveSessionId] = useState(null);
  const [showSidebar, setShowSidebar] = useState(true);
  const messagesEndRef = useRef(null);
  const inputRef = useRef(null);

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
    };
    init();
  }, [fetchSessions, fetchMessages]);

  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages]);

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

  const handleSend = async (e) => {
    e.preventDefault();
    const text = input.trim();
    if (!text || sending) return;

    setInput("");
    setSending(true);

    const tempUserMsg = { message_id: "temp_user", role: "user", content: text, created_at: new Date().toISOString() };
    setMessages((prev) => [...prev, tempUserMsg]);

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
      // Refresh sessions to get updated title
      fetchSessions();
    } catch {
      setMessages((prev) => prev.filter((m) => m.message_id !== "temp_user"));
    } finally {
      setSending(false);
      inputRef.current?.focus();
    }
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

  const suggestedQuestions = [
    "Is my portfolio well-diversified?",
    "Where should I invest ₹1L?",
    "What's my risk profile?",
    "Should I rebalance my portfolio?",
  ];

  const formatTime = (dateStr) => {
    const d = new Date(dateStr);
    const now = new Date();
    const diff = now - d;
    if (diff < 86400000) return d.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
    if (diff < 604800000) return d.toLocaleDateString([], { weekday: "short" });
    return d.toLocaleDateString([], { month: "short", day: "numeric" });
  };

  return (
    <div data-testid="chat-view" className="h-[calc(100vh-6rem)] flex gap-4">
      {/* Conversation History Sidebar */}
      <AnimatePresence>
        {showSidebar && (
          <motion.div
            initial={{ width: 0, opacity: 0 }}
            animate={{ width: 260, opacity: 1 }}
            exit={{ width: 0, opacity: 0 }}
            transition={{ duration: 0.2 }}
            className="flex-shrink-0 flex flex-col h-full"
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
        )}
      </AnimatePresence>

      {/* Main Chat Area */}
      <div className="flex-1 flex flex-col min-w-0">
        {/* Header */}
        <div className="flex items-center justify-between mb-4">
          <div className="flex items-center gap-3">
            <Button
              data-testid="toggle-chat-sidebar"
              variant="outline"
              onClick={() => setShowSidebar(!showSidebar)}
              className="rounded-xl border-slate-200 dark:border-slate-700 h-9 w-9 p-0"
            >
              {showSidebar ? <ChevronLeft className="w-4 h-4" /> : <MessageSquare className="w-4 h-4" />}
            </Button>
            <div>
              <h1 className="text-2xl sm:text-3xl font-medium tracking-tight text-slate-900 dark:text-white" style={{ fontFamily: "'Outfit', sans-serif" }}>
                AI Financial Advisor
              </h1>
              <p className="text-sm text-slate-500 dark:text-slate-400 mt-0.5">Ask anything about your investments</p>
            </div>
          </div>
          {messages.length > 0 && (
            <Button
              data-testid="clear-chat-button"
              variant="outline"
              onClick={handleClear}
              className="rounded-xl border-slate-200 dark:border-slate-700 text-slate-500 dark:text-slate-400 hover:text-red-500 hover:border-red-200"
            >
              <Trash2 className="w-4 h-4 mr-2" strokeWidth={1.5} />
              Clear
            </Button>
          )}
        </div>

        {/* Messages */}
        <Card className="flex-1 bg-white dark:bg-slate-900 border-slate-100 dark:border-slate-800 rounded-2xl shadow-none overflow-hidden flex flex-col">
          <ScrollArea className="flex-1 p-6">
            {loadingMessages ? (
              <div className="flex items-center justify-center h-full">
                <div className="w-8 h-8 border-2 border-emerald-600 border-t-transparent rounded-full animate-spin" />
              </div>
            ) : messages.length === 0 ? (
              <div className="flex flex-col items-center justify-center h-full text-center py-16">
                <div className="w-14 h-14 bg-emerald-50 dark:bg-emerald-900/20 rounded-2xl flex items-center justify-center mb-6">
                  <Bot className="w-7 h-7 text-emerald-600" strokeWidth={1.5} />
                </div>
                <h3 className="text-lg font-medium text-slate-900 dark:text-white mb-2" style={{ fontFamily: "'Outfit', sans-serif" }}>
                  Your AI Financial Advisor
                </h3>
                <p className="text-sm text-slate-500 dark:text-slate-400 mb-8 max-w-md">
                  I can analyze your portfolio, suggest investment strategies, help with tax planning, and answer any financial question.
                </p>
                <div className="grid grid-cols-1 sm:grid-cols-2 gap-3 max-w-lg">
                  {suggestedQuestions.map((q) => (
                    <button
                      key={q}
                      data-testid={`suggested-question-${q.slice(0, 10).replace(/\s/g, '-').toLowerCase()}`}
                      onClick={() => { setInput(q); inputRef.current?.focus(); }}
                      className="text-left text-sm text-slate-600 dark:text-slate-300 bg-slate-50 dark:bg-slate-800 hover:bg-emerald-50 dark:hover:bg-emerald-900/20 hover:text-emerald-700 dark:hover:text-emerald-400 p-3 rounded-xl border border-slate-100 dark:border-slate-700 hover:border-emerald-200 dark:hover:border-emerald-800 transition-all duration-200"
                    >
                      {q}
                    </button>
                  ))}
                </div>
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
                      <div
                        className={`max-w-[75%] px-4 py-3 text-sm leading-relaxed ${
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
                      {msg.role === "user" && (
                        <div className="w-8 h-8 bg-emerald-600 rounded-xl flex-shrink-0 flex items-center justify-center mt-1">
                          <User className="w-4 h-4 text-white" strokeWidth={1.5} />
                        </div>
                      )}
                    </motion.div>
                  ))}
                </AnimatePresence>
                {sending && (
                  <div className="flex gap-3 justify-start">
                    <div className="w-8 h-8 bg-emerald-50 dark:bg-emerald-900/20 rounded-xl flex-shrink-0 flex items-center justify-center mt-1">
                      <Bot className="w-4 h-4 text-emerald-600" strokeWidth={1.5} />
                    </div>
                    <div className="chat-ai-bubble px-4 py-3 flex items-center gap-1">
                      <span className="w-2 h-2 bg-slate-400 rounded-full loading-dot" />
                      <span className="w-2 h-2 bg-slate-400 rounded-full loading-dot" />
                      <span className="w-2 h-2 bg-slate-400 rounded-full loading-dot" />
                    </div>
                  </div>
                )}
                <div ref={messagesEndRef} />
              </div>
            )}
          </ScrollArea>

          {/* Input */}
          <CardContent className="p-4 border-t border-slate-100 dark:border-slate-800">
            <form onSubmit={handleSend} className="flex items-center gap-3">
              <input
                ref={inputRef}
                data-testid="chat-input"
                value={input}
                onChange={(e) => setInput(e.target.value)}
                placeholder="Ask about your investments..."
                disabled={sending}
                className="flex-1 bg-slate-50 dark:bg-slate-800 border border-slate-200 dark:border-slate-700 rounded-xl px-4 py-3 text-sm text-slate-900 dark:text-white placeholder:text-slate-400 dark:placeholder:text-slate-500 focus:outline-none focus:border-emerald-500 focus:ring-1 focus:ring-emerald-500 transition-colors"
              />
              <Button
                data-testid="send-message-button"
                type="submit"
                disabled={!input.trim() || sending}
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
