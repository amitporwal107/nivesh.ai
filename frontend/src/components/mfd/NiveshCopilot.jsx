import React, { useState, useCallback, useEffect, useRef } from "react";
import axios from "axios";
import { toast } from "sonner";
import { Button } from "@/components/ui/button";
import { Textarea } from "@/components/ui/textarea";
import {
  Sparkles, X, Send, Copy, MessageSquare, Mail, Loader2,
  BookOpen, Zap, AlertTriangle, Receipt, TrendingUp, Target,
} from "lucide-react";

const API = `${process.env.REACT_APP_BACKEND_URL}/api`;

/**
 * Nivesh Copilot — embedded CIO assistant panel.
 *
 * Three modes in one slide-in drawer (right side, 420px wide):
 *   1. Brief → one LLM call returns {summary, risk, tax, performance, priority}
 *              Auto-loads on open, cached 24h backend-side.
 *   2. Ask   → free-form Q&A, portfolio context injected server-side.
 *   3. Draft → generates a WhatsApp/email client message, channel + tone pickers.
 *
 * Token-efficient choices:
 *   - Default model = Gemini 2.5 Flash (cheapest working option).
 *   - /brief is a single bundled call (not 4 separate /explain calls).
 *   - Responses cached 24h in Mongo `copilot_cache`.
 *   - No auto-fire for Ask/Draft — user must click.
 *
 * Props:
 *   open        : bool
 *   onClose     : () => void
 *   clientName  : string — rendered in header
 */
const SUGGESTED_PROMPTS = [
  "Why is the health score dropping?",
  "What's the single biggest risk right now?",
  "Which fund should I trim first?",
  "What tax moves should I consider this FY?",
];

export default function NiveshCopilot({ open, onClose, clientName }) {
  const [tab, setTab] = useState("brief");       // brief | ask | draft
  const [model, setModel] = useState("gemini");
  const [models, setModels] = useState([]);

  // Brief state
  const [brief, setBrief] = useState(null);
  const [briefLoading, setBriefLoading] = useState(false);

  // Ask state
  const [askInput, setAskInput] = useState("");
  const [askHistory, setAskHistory] = useState([]); // [{role, content}]
  const [askLoading, setAskLoading] = useState(false);
  const askScrollRef = useRef(null);

  // Draft state
  const [channel, setChannel] = useState("whatsapp");
  const [tone, setTone] = useState("warm_professional");
  const [advisorNote, setAdvisorNote] = useState("");
  const [draft, setDraft] = useState("");
  const [draftLoading, setDraftLoading] = useState(false);

  // ── Load models once ──
  useEffect(() => {
    if (!open || models.length) return;
    axios
      .get(`${API}/copilot/models`, { withCredentials: true })
      .then((r) => {
        setModels(r.data?.models || []);
        if (r.data?.default) setModel(r.data.default);
      })
      .catch(() => { /* non-critical */ });
  }, [open, models.length]);

  // ── Auto-load brief on first open ──
  const loadBrief = useCallback(async (forceModel) => {
    setBriefLoading(true);
    try {
      const { data } = await axios.post(
        `${API}/copilot/brief`,
        { model: forceModel || model },
        { withCredentials: true },
      );
      setBrief({ ...data.brief, cached: data.cached });
    } catch (e) {
      toast.error(e?.response?.data?.detail || "Copilot brief failed");
    } finally {
      setBriefLoading(false);
    }
  }, [model]);

  useEffect(() => {
    if (open && tab === "brief" && brief == null && !briefLoading) {
      loadBrief();
    }
  }, [open, tab, brief, briefLoading, loadBrief]);

  // ── Ask submit ──
  const submitAsk = useCallback(async (question) => {
    const q = (question || askInput).trim();
    if (!q) return;
    setAskInput("");
    const newHistory = [...askHistory, { role: "user", content: q }];
    setAskHistory(newHistory);
    setAskLoading(true);
    try {
      const { data } = await axios.post(
        `${API}/copilot/ask`,
        { model, question: q, history: askHistory.slice(-6) },
        { withCredentials: true },
      );
      setAskHistory([...newHistory, { role: "assistant", content: data.response }]);
    } catch (e) {
      setAskHistory([
        ...newHistory,
        { role: "assistant", content: `⚠️ ${e?.response?.data?.detail || "Copilot failed"}` },
      ]);
    } finally {
      setAskLoading(false);
      setTimeout(() => {
        askScrollRef.current?.scrollTo({ top: askScrollRef.current.scrollHeight, behavior: "smooth" });
      }, 50);
    }
  }, [askInput, askHistory, model]);

  // ── Draft message ──
  const generateDraft = useCallback(async () => {
    setDraftLoading(true);
    try {
      const { data } = await axios.post(
        `${API}/copilot/client-message`,
        { model, channel, tone, additional_note: advisorNote || null },
        { withCredentials: true },
      );
      setDraft(data.response);
    } catch (e) {
      toast.error(e?.response?.data?.detail || "Draft generation failed");
    } finally {
      setDraftLoading(false);
    }
  }, [model, channel, tone, advisorNote]);

  const copyDraft = async () => {
    try {
      await navigator.clipboard.writeText(draft);
      toast.success("Copied to clipboard");
    } catch { /* noop */ }
  };

  const shareWhatsApp = () => {
    const url = `https://wa.me/?text=${encodeURIComponent(draft)}`;
    window.open(url, "_blank");
  };

  if (!open) return null;

  return (
    <>
      {/* Backdrop */}
      <div
        className="fixed inset-0 bg-black/30 z-40 backdrop-blur-sm"
        onClick={onClose}
        data-testid="copilot-backdrop"
      />
      {/* Drawer */}
      <div
        className="fixed top-0 right-0 bottom-0 w-full sm:w-[440px] bg-white dark:bg-slate-950 border-l border-slate-200 dark:border-slate-800 shadow-2xl z-50 flex flex-col"
        data-testid="copilot-drawer"
      >
        {/* Header */}
        <div className="flex-shrink-0 px-4 py-3 border-b border-slate-200 dark:border-slate-800 bg-gradient-to-r from-indigo-600 to-violet-600 text-white">
          <div className="flex items-center justify-between">
            <div className="flex items-center gap-2">
              <div className="w-8 h-8 rounded-lg bg-white/20 flex items-center justify-center">
                <Sparkles className="w-4 h-4" />
              </div>
              <div>
                <div className="text-sm font-bold leading-tight">Nivesh Copilot</div>
                <div className="text-[10px] opacity-80">CIO for {clientName || "this client"}</div>
              </div>
            </div>
            <button
              type="button" onClick={onClose}
              className="w-7 h-7 rounded-md hover:bg-white/20 flex items-center justify-center"
              data-testid="copilot-close"
            >
              <X className="w-4 h-4" />
            </button>
          </div>

          {/* Tabs */}
          <div className="mt-3 flex items-center gap-1 bg-white/10 rounded-lg p-1">
            {[
              { id: "brief", label: "Brief", icon: BookOpen },
              { id: "ask",   label: "Ask",   icon: MessageSquare },
              { id: "draft", label: "Draft", icon: Mail },
            ].map(({ id, label, icon: Icon }) => (
              <button
                key={id} type="button"
                onClick={() => setTab(id)}
                data-testid={`copilot-tab-${id}`}
                className={`flex-1 flex items-center justify-center gap-1.5 text-xs font-semibold py-1.5 rounded-md transition ${
                  tab === id ? "bg-white text-indigo-700" : "text-white/80 hover:text-white"
                }`}
              >
                <Icon className="w-3.5 h-3.5" /> {label}
              </button>
            ))}
          </div>

          {/* Model switcher */}
          <div className="mt-2 flex items-center gap-2 text-[10px]">
            <span className="opacity-80">Model:</span>
            <select
              value={model} onChange={(e) => { setModel(e.target.value); setBrief(null); }}
              className="bg-white/15 border border-white/20 rounded px-2 py-0.5 text-[10px] text-white outline-none"
              data-testid="copilot-model-select"
            >
              {models.map((m) => (
                <option key={m.key} value={m.key} className="text-slate-900">
                  {m.label} · {m.tier}
                </option>
              ))}
            </select>
          </div>
        </div>

        {/* Body */}
        <div className="flex-1 overflow-hidden flex flex-col">
          {/* ── Brief tab ─────────────────────────────────────────── */}
          {tab === "brief" && (
            <div className="flex-1 overflow-y-auto px-4 py-4 space-y-3" data-testid="copilot-brief-panel">
              {briefLoading && (
                <div className="flex items-center gap-2 text-xs text-slate-500">
                  <Loader2 className="w-3.5 h-3.5 animate-spin" /> Asking Copilot…
                </div>
              )}
              {!briefLoading && brief && (
                <>
                  <BriefSection label="Summary" icon={BookOpen} tone="indigo" text={brief.summary} testid="brief-summary" />
                  <BriefSection label="Risk" icon={AlertTriangle} tone="rose" text={brief.risk} testid="brief-risk" />
                  <BriefSection label="Tax" icon={Receipt} tone="amber" text={brief.tax} testid="brief-tax" />
                  <BriefSection label="Performance" icon={TrendingUp} tone="emerald" text={brief.performance} testid="brief-performance" />
                  <BriefSection label="Priority" icon={Target} tone="violet" text={brief.priority} testid="brief-priority" emphasise />
                  <div className="pt-2 flex items-center justify-between text-[10px] text-slate-400">
                    <span>{brief.cached ? "Cached response · 24h fresh" : "Fresh from Copilot"}</span>
                    <button
                      type="button"
                      onClick={() => { setBrief(null); loadBrief(); }}
                      className="text-indigo-600 hover:underline font-semibold"
                      data-testid="copilot-brief-regenerate"
                    >
                      Regenerate
                    </button>
                  </div>
                </>
              )}
            </div>
          )}

          {/* ── Ask tab ───────────────────────────────────────────── */}
          {tab === "ask" && (
            <div className="flex-1 flex flex-col overflow-hidden">
              <div ref={askScrollRef} className="flex-1 overflow-y-auto px-4 py-4 space-y-3" data-testid="copilot-ask-panel">
                {askHistory.length === 0 && (
                  <div className="space-y-2">
                    <div className="text-[11px] uppercase tracking-wider font-bold text-slate-500">
                      Try asking
                    </div>
                    {SUGGESTED_PROMPTS.map((p) => (
                      <button
                        key={p} type="button"
                        onClick={() => submitAsk(p)}
                        data-testid={`copilot-suggest-${p.slice(0, 12).replace(/\s/g, "-").toLowerCase()}`}
                        className="w-full text-left text-xs px-3 py-2 rounded-lg border border-slate-200 dark:border-slate-800 hover:border-indigo-300 hover:bg-indigo-50/40 dark:hover:bg-indigo-900/20 transition"
                      >
                        <Zap className="w-3 h-3 inline mr-1.5 text-indigo-500" />
                        {p}
                      </button>
                    ))}
                  </div>
                )}
                {askHistory.map((m, i) => (
                  <div
                    key={i}
                    data-testid={`copilot-ask-${m.role}-${i}`}
                    className={`flex ${m.role === "user" ? "justify-end" : "justify-start"}`}
                  >
                    <div
                      className={`max-w-[85%] text-xs leading-relaxed rounded-2xl px-3 py-2 whitespace-pre-wrap ${
                        m.role === "user"
                          ? "bg-indigo-600 text-white rounded-br-sm"
                          : "bg-slate-100 dark:bg-slate-800 text-slate-800 dark:text-slate-100 rounded-bl-sm"
                      }`}
                    >
                      {m.content}
                    </div>
                  </div>
                ))}
                {askLoading && (
                  <div className="flex justify-start">
                    <div className="bg-slate-100 dark:bg-slate-800 rounded-2xl rounded-bl-sm px-3 py-2 text-xs text-slate-500 flex items-center gap-2">
                      <Loader2 className="w-3 h-3 animate-spin" /> Thinking…
                    </div>
                  </div>
                )}
              </div>
              <div className="flex-shrink-0 border-t border-slate-200 dark:border-slate-800 p-3 bg-white dark:bg-slate-950">
                <form
                  onSubmit={(e) => { e.preventDefault(); submitAsk(); }}
                  className="flex items-end gap-2"
                >
                  <Textarea
                    value={askInput}
                    onChange={(e) => setAskInput(e.target.value)}
                    onKeyDown={(e) => {
                      if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); submitAsk(); }
                    }}
                    placeholder="Ask about this portfolio…"
                    className="flex-1 min-h-[38px] max-h-[120px] text-xs resize-none"
                    data-testid="copilot-ask-input"
                  />
                  <Button
                    type="submit" size="sm"
                    disabled={askLoading || !askInput.trim()}
                    data-testid="copilot-ask-send"
                    className="h-9 px-3"
                  >
                    <Send className="w-3.5 h-3.5" />
                  </Button>
                </form>
              </div>
            </div>
          )}

          {/* ── Draft tab ─────────────────────────────────────────── */}
          {tab === "draft" && (
            <div className="flex-1 overflow-y-auto px-4 py-4 space-y-3" data-testid="copilot-draft-panel">
              <div className="grid grid-cols-2 gap-2">
                <label className="text-[11px] font-semibold text-slate-600 dark:text-slate-300">
                  Channel
                  <select
                    value={channel} onChange={(e) => setChannel(e.target.value)}
                    data-testid="copilot-channel-select"
                    className="mt-1 w-full text-xs rounded-md border border-slate-200 dark:border-slate-700 dark:bg-slate-900 px-2 py-1.5"
                  >
                    <option value="whatsapp">WhatsApp</option>
                    <option value="email">Email</option>
                  </select>
                </label>
                <label className="text-[11px] font-semibold text-slate-600 dark:text-slate-300">
                  Tone
                  <select
                    value={tone} onChange={(e) => setTone(e.target.value)}
                    data-testid="copilot-tone-select"
                    className="mt-1 w-full text-xs rounded-md border border-slate-200 dark:border-slate-700 dark:bg-slate-900 px-2 py-1.5"
                  >
                    <option value="warm_professional">Warm · professional</option>
                    <option value="formal">Formal</option>
                    <option value="concise">Concise</option>
                  </select>
                </label>
              </div>
              <label className="block text-[11px] font-semibold text-slate-600 dark:text-slate-300">
                Optional note to include
                <Textarea
                  value={advisorNote}
                  onChange={(e) => setAdvisorNote(e.target.value)}
                  placeholder="e.g. We're scheduling a review in April."
                  className="mt-1 text-xs resize-none min-h-[56px]"
                  maxLength={400}
                  data-testid="copilot-advisor-note"
                />
              </label>
              <Button
                type="button"
                onClick={generateDraft}
                disabled={draftLoading}
                data-testid="copilot-generate-draft"
                className="w-full h-9 text-xs"
              >
                {draftLoading ? (<><Loader2 className="w-3.5 h-3.5 mr-1.5 animate-spin" /> Drafting…</>) :
                               (<><Sparkles className="w-3.5 h-3.5 mr-1.5" /> Generate message</>)}
              </Button>
              {draft && (
                <div className="mt-3 space-y-2" data-testid="copilot-draft-output">
                  <div className="text-[11px] uppercase tracking-wider font-bold text-slate-500">
                    Draft · {channel}
                  </div>
                  <Textarea
                    value={draft}
                    onChange={(e) => setDraft(e.target.value)}
                    className="text-xs min-h-[140px] bg-slate-50 dark:bg-slate-900"
                    data-testid="copilot-draft-textarea"
                  />
                  <div className="flex items-center gap-2">
                    <Button
                      type="button" size="sm" variant="outline" onClick={copyDraft}
                      data-testid="copilot-draft-copy"
                      className="flex-1 h-8 text-xs"
                    >
                      <Copy className="w-3 h-3 mr-1" /> Copy
                    </Button>
                    {channel === "whatsapp" && (
                      <Button
                        type="button" size="sm" onClick={shareWhatsApp}
                        data-testid="copilot-draft-whatsapp"
                        className="flex-1 h-8 text-xs bg-emerald-600 hover:bg-emerald-700"
                      >
                        <MessageSquare className="w-3 h-3 mr-1" /> Send
                      </Button>
                    )}
                  </div>
                </div>
              )}
            </div>
          )}
        </div>
      </div>
    </>
  );
}

// ── Helpers ────────────────────────────────────────────────────────────
function BriefSection({ label, icon: Icon, tone, text, testid, emphasise }) {
  if (!text) return null;
  const toneMap = {
    indigo:  "border-indigo-300 bg-indigo-50/70 dark:bg-indigo-900/20 text-indigo-900 dark:text-indigo-100",
    rose:    "border-rose-300 bg-rose-50/70 dark:bg-rose-900/20 text-rose-900 dark:text-rose-100",
    amber:   "border-amber-300 bg-amber-50/70 dark:bg-amber-900/20 text-amber-900 dark:text-amber-100",
    emerald: "border-emerald-300 bg-emerald-50/70 dark:bg-emerald-900/20 text-emerald-900 dark:text-emerald-100",
    violet:  "border-violet-400 bg-violet-50/80 dark:bg-violet-900/30 text-violet-900 dark:text-violet-100",
  };
  return (
    <div
      data-testid={testid}
      className={`rounded-xl border-l-4 ${toneMap[tone]} px-3 py-2.5 ${emphasise ? "shadow-sm" : ""}`}
    >
      <div className="flex items-center gap-1.5 text-[10px] uppercase tracking-wider font-bold opacity-80">
        <Icon className="w-3 h-3" /> {label}
      </div>
      <p className={`mt-1 text-xs leading-relaxed ${emphasise ? "font-semibold" : ""}`}>
        {text}
      </p>
    </div>
  );
}
