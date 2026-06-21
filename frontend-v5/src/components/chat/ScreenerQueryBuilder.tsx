// Visual stock-screener query builder. Compose a complete screen from the NIDP
// primitive catalog — pick a metric, operator and value per condition, plus an
// optional market-cap bucket. The compiled query is the same natural-language
// string the backend parser consumes, so "Run screen" just submits it into chat.
import { useState } from "react";
import { Plus, X, Trash2, Sparkles } from "lucide-react";
import { Button } from "@/components/ui/button";
import {
  PRIMITIVE_GROUPS, PRIMITIVE_BY_KEY, compileScreenQuery,
  type BuilderCondition,
} from "@/components/chat/screenerPrimitives";

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

  const setCond = (id: number, patch: Partial<BuilderCondition>) =>
    setConds((cs) => cs.map((c) => (c.id === id ? { ...c, ...patch } : c)));
  const changeMetric = (id: number, key: string) =>
    setConds((cs) => cs.map((c) => (c.id === id ? { ...c, key, op: PRIMITIVE_BY_KEY[key]?.op ?? c.op } : c)));
  const addCond = () => setConds((cs) => [...cs, newCond()]);
  const removeCond = (id: number) => setConds((cs) => cs.filter((c) => c.id !== id));
  const reset = () => { setBucket(""); setConds([newCond("roe")]); };

  const query = compileScreenQuery(conds, bucket || undefined);
  const canRun = query.length > 0;

  return (
    <div className="rounded-xl bg-surface-1 border border-hairline-2 shadow-card overflow-hidden">
      {/* header */}
      <div className="flex items-center justify-between gap-3 px-4 py-3 border-b border-hairline">
        <div className="flex items-center gap-2">
          <Sparkles className="h-4 w-4 text-accent" />
          <span className="font-display text-[15px] text-ink tracking-tightish">Build a screen</span>
        </div>
        <button onClick={onClose} aria-label="Close query builder" className="p-1 rounded text-ink-3 hover:text-ink hover:bg-surface-2 transition-colors">
          <X className="h-4 w-4" />
        </button>
      </div>

      <div className="p-4 flex flex-col gap-3.5 max-h-[60vh] overflow-y-auto">
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
      </div>

      {/* footer */}
      <div className="flex items-center justify-between gap-3 px-4 py-3 border-t border-hairline">
        <button onClick={reset} className="text-[12.5px] text-ink-3 hover:text-ink transition-colors">Reset</button>
        <Button variant="accent" size="sm" disabled={!canRun} onClick={() => onRun(query)}>
          <Sparkles className="h-3.5 w-3.5" /> Run screen
        </Button>
      </div>
    </div>
  );
}
