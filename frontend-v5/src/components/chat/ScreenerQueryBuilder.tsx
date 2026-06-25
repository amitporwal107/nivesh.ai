// Visual stock-screener query builder + saved screens. Compose a complete screen
// from the NIDP primitive catalog — pick a metric, operator and value per
// condition, plus an optional market-cap bucket. The compiled query is the same
// natural-language string the backend parser consumes, so "Run screen" just
// submits it into chat. Screens can be saved (per user, MongoDB) and reloaded
// for view / edit / delete.
import { useState } from "react";
import { Plus, X, Trash2, Sparkles, Save, Play, Pencil, Bookmark } from "lucide-react";
import { Button } from "@/components/ui/button";
import {
  PRIMITIVE_GROUPS, PRIMITIVE_BY_KEY, compileScreenQuery, SCREEN_TEMPLATES,
  type BuilderCondition, type ScreenTemplate,
} from "@/components/chat/screenerPrimitives";
import {
  useScreeners, useCreateScreener, useUpdateScreener, useDeleteScreener,
  type SavedScreener,
} from "@/hooks/use-screeners";

const BUCKETS = [
  { key: "", label: "Any size" },
  { key: "large", label: "Large cap" },
  { key: "mid", label: "Mid cap" },
  { key: "small", label: "Small cap" },
];

let _uid = 0;
const newCond = (key = "roe"): BuilderCondition => ({ id: ++_uid, key, op: PRIMITIVE_BY_KEY[key]?.op ?? "over", value: "" });

export function ScreenerQueryBuilder({
  onRun,
  onClose,
}: {
  onRun: (query: string) => void;
  onClose: () => void;
}) {
  const [bucket, setBucket] = useState("");
  const [conds, setConds] = useState<BuilderCondition[]>([newCond("roe"), newCond("pe")]);
  const [name, setName] = useState("");
  const [editingId, setEditingId] = useState<string | null>(null);

  const saved = useScreeners();
  const createS = useCreateScreener();
  const updateS = useUpdateScreener();
  const deleteS = useDeleteScreener();
  const savedList = saved.data ?? [];

  const setCond = (id: number, patch: Partial<BuilderCondition>) =>
    setConds((cs) => cs.map((c) => (c.id === id ? { ...c, ...patch } : c)));
  const changeMetric = (id: number, key: string) =>
    setConds((cs) => cs.map((c) => (c.id === id ? { ...c, key, op: PRIMITIVE_BY_KEY[key]?.op ?? c.op } : c)));
  const addCond = () => setConds((cs) => [...cs, newCond()]);
  const removeCond = (id: number) => setConds((cs) => (cs.length > 1 ? cs.filter((c) => c.id !== id) : cs));
  const reset = () => { setBucket(""); setConds([newCond("roe")]); setName(""); setEditingId(null); };

  const query = compileScreenQuery(conds, bucket || undefined);
  const canRun = query.length > 0;
  const busy = createS.isPending || updateS.isPending;

  // Load a classic template into the builder as a fresh (unsaved) screen the
  // user can tweak, run, or save under their own name.
  const loadTemplate = (t: ScreenTemplate) => {
    setConds(t.conds.map((c) => ({ id: ++_uid, key: c.key, op: c.op, value: c.value })));
    setBucket(t.bucket || "");
    setName(t.name);
    setEditingId(null);
  };

  // Load a saved screen back into the builder for view / edit.
  const loadScreen = (s: SavedScreener) => {
    const mapped = (s.conditions ?? [])
      .filter((c) => PRIMITIVE_BY_KEY[c.key] && !PRIMITIVE_BY_KEY[c.key].bucket)
      .map((c) => ({ id: ++_uid, key: c.key, op: (c.op === "under" ? "under" : "over") as "over" | "under", value: String(c.value ?? "") }));
    setConds(mapped.length ? mapped : [newCond()]);
    setBucket(s.bucket || "");
    setName(s.name);
    setEditingId(s.screener_id);
  };

  const save = () => {
    if (!canRun || !name.trim()) return;
    const body = {
      name: name.trim(),
      query,
      conditions: conds.filter((c) => c.value.trim() !== "").map((c) => ({ key: c.key, op: c.op, value: c.value.trim() })),
      bucket,
    };
    if (editingId) updateS.mutate({ id: editingId, body });
    else createS.mutate(body, { onSuccess: (s) => setEditingId(s.screener_id) });
  };

  return (
    <div className="rounded-xl bg-surface-1 border border-hairline-2 shadow-card overflow-hidden">
      {/* header */}
      <div className="flex items-center justify-between gap-3 px-4 py-3 border-b border-hairline">
        <div className="flex items-center gap-2">
          <Sparkles className="h-4 w-4 text-accent" />
          <span className="font-display text-[15px] text-ink tracking-tightish">{editingId ? "Edit screen" : "Build a screen"}</span>
        </div>
        <button onClick={onClose} aria-label="Close query builder" className="p-1 rounded text-ink-3 hover:text-ink hover:bg-surface-2 transition-colors">
          <X className="h-4 w-4" />
        </button>
      </div>

      <div className="p-4 flex flex-col gap-3.5 max-h-[62vh] overflow-y-auto">
        {/* classic templates — one-click starting points (mirror backend presets) */}
        {SCREEN_TEMPLATES.length > 0 && (
          <div>
            <div className="mb-1.5 flex items-center gap-1.5 text-[11.5px] font-medium text-ink-2">
              <Sparkles className="h-3.5 w-3.5 text-ink-3" /> Start from a template
            </div>
            <div className="flex flex-wrap gap-1.5">
              {SCREEN_TEMPLATES.map((t) => (
                <button
                  key={t.name}
                  onClick={() => loadTemplate(t)}
                  title={t.hint}
                  className="rounded-full border border-hairline bg-surface-1 px-2.5 py-1 text-[12px] text-ink-2 hover:bg-surface-2 hover:text-ink hover:border-accent/40 transition-colors"
                >
                  {t.name}
                </button>
              ))}
            </div>
            <div className="mt-3 border-t border-hairline" />
          </div>
        )}

        {/* saved screens */}
        {savedList.length > 0 && (
          <div>
            <div className="mb-1.5 flex items-center gap-1.5 text-[11.5px] font-medium text-ink-2">
              <Bookmark className="h-3.5 w-3.5 text-ink-3" /> Saved screens
            </div>
            <div className="flex flex-col gap-1.5">
              {savedList.map((s) => (
                <div
                  key={s.screener_id}
                  className={
                    "group flex items-center gap-2 rounded-md border px-2.5 py-2 transition-colors " +
                    (editingId === s.screener_id ? "border-accent bg-[rgb(var(--accent)/0.06)]" : "border-hairline bg-surface-1 hover:bg-surface-2/60")
                  }
                >
                  <button onClick={() => loadScreen(s)} className="min-w-0 flex-1 text-left" title="Load into builder">
                    <span className="block text-[13px] text-ink truncate">{s.name}</span>
                    <span className="block font-mono text-[10.5px] text-ink-3 truncate">{s.query}</span>
                  </button>
                  <button onClick={() => onRun(s.query)} aria-label="Run screen" title="Run" className="shrink-0 p-1.5 rounded text-ink-3 hover:text-accent hover:bg-surface-2 transition-colors">
                    <Play className="h-3.5 w-3.5" />
                  </button>
                  <button onClick={() => loadScreen(s)} aria-label="Edit screen" title="Edit" className="shrink-0 p-1.5 rounded text-ink-3 hover:text-ink hover:bg-surface-2 transition-colors">
                    <Pencil className="h-3.5 w-3.5" />
                  </button>
                  <button onClick={() => { if (editingId === s.screener_id) reset(); deleteS.mutate(s.screener_id); }} aria-label="Delete screen" title="Delete" className="shrink-0 p-1.5 rounded text-ink-3 hover:text-neg hover:bg-surface-2 transition-colors">
                    <Trash2 className="h-3.5 w-3.5" />
                  </button>
                </div>
              ))}
            </div>
            <div className="mt-3 border-t border-hairline" />
          </div>
        )}

        {/* cap-bucket segmented control */}
        <div>
          <div className="mb-1.5 text-[11.5px] font-medium text-ink-2">Universe</div>
          <div className="inline-flex rounded-lg border border-hairline bg-surface-2/50 p-0.5">
            {BUCKETS.map((b) => (
              <button
                key={b.key}
                onClick={() => setBucket(b.key)}
                className={
                  "px-3 py-1.5 text-[12.5px] rounded-md transition-colors " +
                  (bucket === b.key ? "bg-surface-1 text-ink shadow-sm font-medium" : "text-ink-3 hover:text-ink")
                }
              >
                {b.label}
              </button>
            ))}
          </div>
        </div>

        {/* condition rows */}
        <div className="flex flex-col gap-2">
          <div className="text-[11.5px] font-medium text-ink-2">Conditions</div>
          {conds.map((c) => {
            const p = PRIMITIVE_BY_KEY[c.key];
            return (
              <div key={c.id} className="flex items-center gap-2">
                <select
                  value={c.key}
                  onChange={(e) => changeMetric(c.id, e.target.value)}
                  className="flex-1 min-w-0 rounded-md border border-hairline-2 bg-surface-1 px-2.5 py-2 text-[13px] text-ink outline-none focus:border-accent"
                >
                  {PRIMITIVE_GROUPS.map((g) => (
                    <optgroup key={g.cat} label={g.cat}>
                      {g.items.filter((it) => !it.bucket).map((it) => (
                        <option key={it.key} value={it.key}>{it.label}</option>
                      ))}
                    </optgroup>
                  ))}
                </select>
                <select
                  value={c.op}
                  onChange={(e) => setCond(c.id, { op: e.target.value as "over" | "under" })}
                  className="shrink-0 rounded-md border border-hairline-2 bg-surface-1 px-2 py-2 text-[13px] text-ink outline-none focus:border-accent"
                  aria-label="Operator"
                >
                  <option value="over">&gt;</option>
                  <option value="under">&lt;</option>
                </select>
                <div className="relative shrink-0 w-[104px]">
                  <input
                    type="number"
                    inputMode="decimal"
                    value={c.value}
                    onChange={(e) => setCond(c.id, { value: e.target.value })}
                    placeholder="value"
                    className="w-full rounded-md border border-hairline-2 bg-surface-1 pl-2.5 pr-8 py-2 text-[13px] tabular-nums outline-none focus:border-accent"
                  />
                  {p?.tag && <span className="pointer-events-none absolute right-2 top-1/2 -translate-y-1/2 text-[11px] text-ink-3">{p.tag}</span>}
                </div>
                <button
                  onClick={() => removeCond(c.id)}
                  disabled={conds.length === 1}
                  aria-label="Remove condition"
                  className="shrink-0 p-1.5 rounded text-ink-3 hover:text-neg hover:bg-surface-2 disabled:opacity-30 transition-colors"
                >
                  <Trash2 className="h-3.5 w-3.5" />
                </button>
              </div>
            );
          })}
          <button
            onClick={addCond}
            className="self-start inline-flex items-center gap-1.5 mt-0.5 px-2.5 py-1.5 rounded-md border border-hairline text-[12.5px] text-ink-2 hover:bg-surface-2 hover:text-ink transition-colors"
          >
            <Plus className="h-3.5 w-3.5" /> Add condition
          </button>
        </div>

        {/* compiled query preview — exactly what will be sent */}
        <div className="rounded-lg bg-surface-2/60 border border-hairline px-3.5 py-3">
          <div className="mb-1 font-mono text-[10px] uppercase tracking-[.16em] text-ink-3">Query</div>
          <code className="block font-mono text-[12.5px] text-ink-2 leading-relaxed break-words">
            {query || <span className="text-ink-3">Add a condition or pick a universe to build a screen</span>}
          </code>
        </div>

        {/* save row */}
        <div className="flex items-center gap-2">
          <input
            type="text"
            value={name}
            onChange={(e) => setName(e.target.value)}
            placeholder={editingId ? "Screen name" : "Save this screen as…"}
            maxLength={80}
            className="flex-1 min-w-0 rounded-md border border-hairline-2 bg-surface-1 px-2.5 py-2 text-[13px] outline-none focus:border-accent"
          />
          <button
            onClick={save}
            disabled={!canRun || !name.trim() || busy}
            className="shrink-0 inline-flex items-center gap-1.5 px-3 py-2 rounded-md border border-hairline text-[12.5px] font-medium text-ink-2 hover:bg-surface-2 hover:text-ink disabled:opacity-40 transition-colors"
          >
            <Save className="h-3.5 w-3.5" /> {editingId ? "Update" : "Save"}
          </button>
        </div>
      </div>

      {/* footer */}
      <div className="flex items-center justify-between gap-3 px-4 py-3 border-t border-hairline">
        <button onClick={reset} className="text-[12.5px] text-ink-3 hover:text-ink transition-colors">
          {editingId ? "New screen" : "Reset"}
        </button>
        <Button variant="accent" size="sm" disabled={!canRun} onClick={() => onRun(query)}>
          <Sparkles className="h-3.5 w-3.5" /> Run screen
        </Button>
      </div>
    </div>
  );
}
