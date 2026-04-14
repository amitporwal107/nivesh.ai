import React, { useState, useEffect, useRef } from "react";
import axios from "axios";
import { Send, Trash2, Bot, User } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { ScrollArea } from "@/components/ui/scroll-area";
import { motion, AnimatePresence } from "framer-motion";

const BACKEND_URL = process.env.REACT_APP_BACKEND_URL;
const API = `${BACKEND_URL}/api`;

const ChatView = () => {
  const [messages, setMessages] = useState([]);
  const [input, setInput] = useState("");
  const [sending, setSending] = useState(false);
  const [loadingMessages, setLoadingMessages] = useState(true);
  const messagesEndRef = useRef(null);
  const inputRef = useRef(null);

  useEffect(() => {
    fetchMessages();
  }, []);

  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages]);

  const fetchMessages = async () => {
    try {
      const res = await axios.get(`${API}/chat/messages`, { withCredentials: true });
      setMessages(res.data);
    } catch (err) {
      console.error("Failed to load messages", err);
    } finally {
      setLoadingMessages(false);
    }
  };

  const handleSend = async (e) => {
    e.preventDefault();
    const text = input.trim();
    if (!text || sending) return;

    setInput("");
    setSending(true);

    // Optimistic: add user message immediately
    const tempUserMsg = { message_id: "temp_user", role: "user", content: text, created_at: new Date().toISOString() };
    setMessages((prev) => [...prev, tempUserMsg]);

    try {
      const res = await axios.post(`${API}/chat/send`, { message: text }, { withCredentials: true });
      setMessages((prev) => {
        const filtered = prev.filter((m) => m.message_id !== "temp_user");
        return [...filtered, res.data.user_message, res.data.ai_message];
      });
    } catch {
      setMessages((prev) => prev.filter((m) => m.message_id !== "temp_user"));
    } finally {
      setSending(false);
      inputRef.current?.focus();
    }
  };

  const handleClear = async () => {
    try {
      await axios.delete(`${API}/chat/clear`, { withCredentials: true });
      setMessages([]);
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

  return (
    <div data-testid="chat-view" className="h-[calc(100vh-6rem)] flex flex-col">
      {/* Header */}
      <div className="flex items-center justify-between mb-4">
        <div>
          <h1 className="text-2xl sm:text-3xl font-medium tracking-tight text-slate-900 dark:text-white" style={{ fontFamily: "'Outfit', sans-serif" }}>
            AI Financial Advisor
          </h1>
          <p className="text-sm text-slate-500 dark:text-slate-400 mt-1">Ask anything about your investments</p>
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
                      className={`max-w-[75%] px-4 py-3 text-sm leading-relaxed whitespace-pre-wrap ${
                        msg.role === "user"
                          ? "chat-user-bubble"
                          : "chat-ai-bubble"
                      }`}
                    >
                      {msg.content}
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
  );
};

export default ChatView;
