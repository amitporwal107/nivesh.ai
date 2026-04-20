import React, { useState, useEffect, useCallback } from "react";
import axios from "axios";
import { toast } from "sonner";
import {
  Sparkles, RefreshCw, RotateCcw, Save, PlayCircle, ChevronDown, ChevronUp, Edit3,
} from "lucide-react";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { Label } from "@/components/ui/label";
import { Textarea } from "@/components/ui/textarea";
import { Input } from "@/components/ui/input";
import { motion, AnimatePresence } from "framer-motion";

const API = `${process.env.REACT_APP_BACKEND_URL}/api`;

const PromptRow = ({ prompt, onSave, onReset }) => {
  const [expanded, setExpanded] = useState(false);
  const [editing, setEditing] = useState(false);
  const [text, setText] = useState(prompt.current);
  const [saving, setSaving] = useState(false);
  const [testing, setTesting] = useState(false);
  const [userText, setUserText] = useState("What should I do about my portfolio?");
  const [testResult, setTestResult] = useState(null);

  const save = async () => {
    setSaving(true);
    try {
      await axios.put(`${API}/admin/prompts/${prompt.name}`, { text }, { withCredentials: true });
      toast.success(`Prompt "${prompt.name}" saved`);
      setEditing(false);
      onSave();
    } catch (err) {
      toast.error(err.response?.data?.detail || "Save failed");
    } finally {
      setSaving(false);
    }
  };

  const reset = async () => {
    if (!window.confirm(`Reset "${prompt.name}" to its code default? Your custom text will be lost.`)) return;
    try {
      await axios.post(`${API}/admin/prompts/${prompt.name}/reset`, {}, { withCredentials: true });
      toast.success("Reset to default");
      setEditing(false);
      setText(prompt.default);
      onReset();
    } catch (err) {
      toast.error(err.response?.data?.detail || "Reset failed");
    }
  };

  const runTest = async () => {
    setTesting(true);
    setTestResult(null);
    try {
      const { data } = await axios.post(
        `${API}/admin/prompts/${prompt.name}/test`,
        { user_text: userText },
        { withCredentials: true },
      );
      setTestResult(data);
    } catch (err) {
      setTestResult({ error: err.response?.data?.detail || "Test failed" });
    } finally {
      setTesting(false);
    }
  };

  const startEdit = () => {
    setText(prompt.current);
    setEditing(true);
    setExpanded(true);
  };

  const cancelEdit = () => {
    setText(prompt.current);
    setEditing(false);
  };

  return (
    <div
      data-testid={`prompt-row-${prompt.name}`}
      className="rounded-2xl border border-slate-100 dark:border-slate-800 bg-slate-50/40 dark:bg-slate-900/40 overflow-hidden"
    >
      <button
        onClick={() => setExpanded(!expanded)}
        className="w-full p-4 flex items-center justify-between gap-3 hover:bg-slate-50 dark:hover:bg-slate-900/60 transition-colors"
        data-testid={`prompt-toggle-${prompt.name}`}
      >
        <div className="min-w-0 flex-1 text-left">
          <div className="flex items-center gap-2 flex-wrap">
            <code className="text-sm font-semibold text-slate-900 dark:text-white font-mono">{prompt.name}</code>
            {prompt.overridden && (
              <span className="text-[10px] font-bold tracking-wider uppercase px-2 py-0.5 rounded-md bg-amber-100 dark:bg-amber-950/40 text-amber-700 dark:text-amber-400">
                Overridden
              </span>
            )}
            <span className="text-[10px] text-slate-400">{prompt.length.toLocaleString()} chars</span>
          </div>
          {prompt.description && <p className="text-xs text-slate-500 dark:text-slate-400 mt-0.5">{prompt.description}</p>}
          {prompt.used_in && <p className="text-[11px] font-mono text-slate-400 mt-0.5">used in: {prompt.used_in}</p>}
        </div>
        {expanded ? <ChevronUp className="w-4 h-4 text-slate-400" /> : <ChevronDown className="w-4 h-4 text-slate-400" />}
      </button>

      <AnimatePresence>
        {expanded && (
          <motion.div
            initial={{ opacity: 0, height: 0 }} animate={{ opacity: 1, height: "auto" }} exit={{ opacity: 0, height: 0 }}
            className="border-t border-slate-100 dark:border-slate-800 p-4 space-y-3"
          >
            <div className="flex items-center gap-2 flex-wrap">
              {!editing ? (
                <Button size="sm" variant="outline" onClick={startEdit} className="rounded-lg" data-testid={`edit-${prompt.name}`}>
                  <Edit3 className="w-4 h-4 mr-1" /> Edit
                </Button>
              ) : (
                <>
                  <Button size="sm" onClick={save} disabled={saving || text === prompt.current}
                    className="bg-emerald-600 hover:bg-emerald-700 text-white rounded-lg"
                    data-testid={`save-${prompt.name}`}
                  >
                    <Save className="w-4 h-4 mr-1" /> {saving ? "Saving…" : "Save"}
                  </Button>
                  <Button size="sm" variant="outline" onClick={cancelEdit} className="rounded-lg">Cancel</Button>
                </>
              )}
              {prompt.overridden && (
                <Button size="sm" variant="outline" onClick={reset}
                  className="rounded-lg text-amber-700 dark:text-amber-400 border-amber-200 dark:border-amber-900"
                  data-testid={`reset-${prompt.name}`}
                >
                  <RotateCcw className="w-4 h-4 mr-1" /> Reset to default
                </Button>
              )}
            </div>

            <Textarea
              data-testid={`prompt-text-${prompt.name}`}
              value={editing ? text : prompt.current}
              onChange={(e) => setText(e.target.value)}
              readOnly={!editing}
              rows={Math.min(20, Math.max(6, (editing ? text : prompt.current).split("\n").length + 1))}
              className="font-mono text-[12px] leading-relaxed bg-white dark:bg-slate-950 border-slate-200 dark:border-slate-800 rounded-lg"
            />

            <div className="p-3 rounded-xl bg-white dark:bg-slate-950/60 border border-slate-100 dark:border-slate-800">
              <Label className="text-xs font-medium text-slate-600 dark:text-slate-300">Test prompt</Label>
              <p className="text-[11px] text-slate-400 mt-0.5 mb-2">Sends your message to gpt-4o-mini using this prompt as the system message.</p>
              <div className="flex items-center gap-2">
                <Input
                  data-testid={`prompt-user-text-${prompt.name}`}
                  value={userText}
                  onChange={(e) => setUserText(e.target.value)}
                  placeholder="User message to test with…"
                  className="h-9 text-sm rounded-lg"
                />
                <Button size="sm" onClick={runTest} disabled={testing}
                  className="bg-violet-600 hover:bg-violet-700 text-white rounded-lg"
                  data-testid={`test-${prompt.name}`}
                >
                  <PlayCircle className="w-4 h-4 mr-1" /> {testing ? "Running…" : "Test"}
                </Button>
              </div>
              {testResult && (
                <div className="mt-3">
                  {testResult.error ? (
                    <div className="p-3 rounded-lg bg-rose-50 dark:bg-rose-950/30 border border-rose-200 dark:border-rose-900 text-xs text-rose-700 dark:text-rose-300">
                      Error: {testResult.error}
                    </div>
                  ) : (
                    <div className="p-3 rounded-lg bg-slate-50 dark:bg-slate-950/40 border border-slate-200 dark:border-slate-800 text-xs whitespace-pre-wrap text-slate-700 dark:text-slate-300">
                      <div className="text-[10px] font-bold tracking-wider uppercase text-slate-400 mb-1">LLM response</div>
                      {testResult.response}
                    </div>
                  )}
                </div>
              )}
            </div>
          </motion.div>
        )}
      </AnimatePresence>
    </div>
  );
};

const PromptsSection = () => {
  const [prompts, setPrompts] = useState([]);
  const [loading, setLoading] = useState(true);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const { data } = await axios.get(`${API}/admin/prompts`, { withCredentials: true });
      setPrompts(data.prompts || []);
    } catch (err) {
      toast.error(err.response?.data?.detail || "Failed to load prompts");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => { load(); }, [load]);

  return (
    <Card data-testid="prompts-section" className="bg-white dark:bg-slate-800 border-slate-100 dark:border-slate-700 rounded-2xl">
      <CardContent className="p-6 space-y-5">
        <div className="flex items-center justify-between gap-3 flex-wrap">
          <div className="flex items-center gap-3">
            <div className="w-10 h-10 rounded-xl bg-violet-50 dark:bg-violet-950/40 flex items-center justify-center">
              <Sparkles className="w-5 h-5 text-violet-600" />
            </div>
            <div>
              <h3 className="text-base font-semibold text-slate-900 dark:text-white" style={{ fontFamily: "'Outfit', sans-serif" }}>
                LLM Prompts
              </h3>
              <p className="text-xs text-slate-500 dark:text-slate-400 mt-0.5">
                Every system prompt sent to the LLM. Edit live; changes apply to the next LLM call.
              </p>
            </div>
          </div>
          <Button variant="outline" size="sm" onClick={load} className="rounded-lg" data-testid="prompts-refresh">
            <RefreshCw className="w-4 h-4 mr-1" /> Refresh
          </Button>
        </div>

        {loading ? (
          <div className="flex items-center gap-3 text-sm text-slate-500">
            <div className="w-5 h-5 border-2 border-violet-600 border-t-transparent rounded-full animate-spin" />
            Loading prompts…
          </div>
        ) : (
          <div className="space-y-3">
            {prompts.map((p) => (
              <PromptRow key={p.name} prompt={p} onSave={load} onReset={load} />
            ))}
          </div>
        )}
      </CardContent>
    </Card>
  );
};

export default PromptsSection;
