/**
 * Scan Builder — the editor's building blocks: token selects, number fields, the measure picker, an operand / expression
 * editor and the per-row actions (operation, comment, duplicate, on/off, debug count, delete), drawn as the owner's Chartink
 * screenshots show a row: "[Daily] [1 day ago] Close  Greater than  Number 55   ⊞ 💬 ⧉ ◉ 🐞 ×".
 */
import { useEffect, useMemo, useRef, useState, type CSSProperties, type ReactNode } from "react";
import { Bug, Calculator, Copy, MessageSquare, Plus, X } from "lucide-react";
import {
  ARITH_LABEL, LIMITS, OP_LABEL, SOURCES, TF_LABEL, defaultParams, measureGroups, measureText, offsetLabel,
  type ArithOp, type Catalog, type CatalogMeasure, type Expr, type MeasureOperand, type Op, type Operand, type ParamValue, type Timeframe,
} from "./scan-model";

// ── styles ───────────────────────────────────────────────────────────────────────────────────────────────────────────

export const tokenSelect = (color: string, weight = 500): CSSProperties => ({
  appearance: "none", WebkitAppearance: "none", background: "transparent", border: 0, borderBottom: "1px dashed var(--line-2)",
  color, fontFamily: "var(--sans)", fontSize: 13.5, fontWeight: weight, padding: "1px 2px", cursor: "pointer", maxWidth: 220,
});
const numberChip: CSSProperties = {
  width: 76, padding: "2px 6px", borderRadius: 6, border: "1px solid var(--line-2)", background: "var(--bg-3)", color: "var(--cp-ink)",
  fontFamily: "var(--mono)", fontSize: 12.5, fontWeight: 600,
};
const paramChip: CSSProperties = { ...numberChip, width: 54, padding: "1px 4px", fontWeight: 500 };
const iconBtn: CSSProperties = {
  display: "inline-flex", alignItems: "center", justifyContent: "center", width: 26, height: 26, borderRadius: 7, border: 0,
  background: "transparent", color: "var(--cp-ink-3)", cursor: "pointer", flex: "none",
};
export const C = { tf: "var(--cp-ink-3)", measure: "var(--cp-ink)", op: "var(--cp-indigo)", arith: "var(--amber)", muted: "var(--cp-ink-3)" } as const;

// ── small controls ───────────────────────────────────────────────────────────────────────────────────────────────────

/** A number box that lets you type freely and commits only a real number. */
export function NumberField({ value, onChange, label, testId, small, min, max, step }: {
  value: number; onChange: (v: number) => void; label: string; testId?: string; small?: boolean; min?: number | null; max?: number | null; step?: number | "any";
}) {
  const [text, setText] = useState(String(value));
  useEffect(() => { setText((t) => (Number(t) === value ? t : String(value))); }, [value]);
  return (
    <input
      type="number" inputMode="decimal" aria-label={label} title={label} data-testid={testId}
      value={text} min={min ?? undefined} max={max ?? undefined} step={step ?? "any"}
      onChange={(e) => {
        setText(e.target.value);
        const v = Number(e.target.value);
        if (e.target.value.trim() !== "" && Number.isFinite(v)) onChange(v);
      }}
      onBlur={() => { if (text.trim() === "" || !Number.isFinite(Number(text))) setText(String(value)); }}
      style={small ? paramChip : numberChip}
    />
  );
}

export function IconButton({ label, onClick, children, testId, active, disabled }: {
  label: string; onClick: () => void; children: ReactNode; testId?: string; active?: boolean; disabled?: boolean;
}) {
  return (
    <button type="button" aria-label={label} title={label} data-testid={testId} onClick={onClick} disabled={disabled} aria-pressed={active}
      style={{ ...iconBtn, color: active ? "var(--mint)" : iconBtn.color, opacity: disabled ? 0.4 : 1 }}>
      {children}
    </button>
  );
}

/** An on/off switch (role=switch). */
export function Toggle({ on, onChange, label, testId }: { on: boolean; onChange: (on: boolean) => void; label: string; testId?: string }) {
  return (
    <button type="button" role="switch" aria-checked={on} aria-label={label} title={label} data-testid={testId} onClick={() => onChange(!on)}
      style={{ ...iconBtn, width: 30 }}>
      <span aria-hidden style={{ position: "relative", width: 24, height: 14, borderRadius: 999, background: on ? "var(--mint)" : "var(--bg-3)", border: "1px solid var(--line-2)", transition: "background .15s" }}>
        <span style={{ position: "absolute", top: 1, left: on ? 11 : 1, width: 10, height: 10, borderRadius: 999, background: on ? "var(--bg-0)" : "var(--cp-ink-3)", transition: "left .15s" }} />
      </span>
    </button>
  );
}

/** The per-row actions, Chartink's icon strip. `debug` = how many stocks passed this filter in the last run. */
export function RowActions({ onTerm, onComment, commentOn, onDuplicate, enabled, onToggle, debug, onDelete, what, testPrefix }: {
  onTerm?: () => void; onComment?: () => void; commentOn?: boolean; onDuplicate?: () => void; enabled?: boolean; onToggle?: (on: boolean) => void;
  debug?: { passed: number; unknown: number } | null; onDelete?: () => void; what: string; testPrefix: string;
}) {
  return (
    <span className="inline-flex flex-none items-center" style={{ gap: 2 }}>
      {onTerm && <IconButton label={`Add an operation (+ − × ÷) to this ${what}`} onClick={onTerm} testId={`${testPrefix}-term`}><Calculator size={14} /></IconButton>}
      {onComment && <IconButton label={`Comment on this ${what}`} onClick={onComment} active={commentOn} testId={`${testPrefix}-comment`}><MessageSquare size={14} /></IconButton>}
      {onDuplicate && <IconButton label={`Duplicate this ${what}`} onClick={onDuplicate} testId={`${testPrefix}-duplicate`}><Copy size={14} /></IconButton>}
      {onToggle && <Toggle on={enabled !== false} onChange={onToggle} label={enabled !== false ? `Turn this ${what} off` : `Turn this ${what} on`} testId={`${testPrefix}-toggle`} />}
      {debug !== undefined && (
        <span data-testid={`${testPrefix}-debug`} className="inline-flex items-center" title={debug ? `Last run: ${debug.passed} stocks passed this ${what}${debug.unknown ? `; ${debug.unknown} could not be decided (missing data)` : ""}` : "Run the scan to see how many stocks pass this"}
          style={{ gap: 3, padding: "0 4px", fontFamily: "var(--mono)", fontSize: 11, color: debug ? "var(--cp-ink-2)" : "var(--cp-ink-3)" }}>
          <Bug size={13} aria-hidden />
          {debug ? <span>{debug.passed}{debug.unknown ? <span style={{ color: "var(--cp-ink-3)" }}> · {debug.unknown}?</span> : null}</span> : null}
        </span>
      )}
      {onDelete && <IconButton label={`Delete this ${what}`} onClick={onDelete} testId={`${testPrefix}-delete`}><X size={14} /></IconButton>}
    </span>
  );
}

// ── the measure picker ───────────────────────────────────────────────────────────────────────────────────────────────

export type PickerChoice = { kind: "number" } | { kind: "measure"; measure: CatalogMeasure } | { kind: "fundamental"; key: string };

function Popover({ open, onClose, children, label }: { open: boolean; onClose: () => void; children: ReactNode; label: string }) {
  const ref = useRef<HTMLDivElement>(null);
  useEffect(() => {
    if (!open) return;
    const down = (e: MouseEvent) => { if (ref.current && !ref.current.contains(e.target as Node)) onClose(); };
    const key = (e: KeyboardEvent) => { if (e.key === "Escape") onClose(); };
    document.addEventListener("mousedown", down);
    document.addEventListener("keydown", key);
    return () => { document.removeEventListener("mousedown", down); document.removeEventListener("keydown", key); };
  }, [open, onClose]);
  if (!open) return null;
  return (
    <div ref={ref} role="dialog" aria-label={label} data-testid="sb-picker"
      className="cp-card"
      style={{ position: "absolute", zIndex: 40, top: "calc(100% + 6px)", left: 0, width: 300, maxHeight: 360, display: "flex", flexDirection: "column", boxShadow: "0 12px 32px rgba(0,0,0,.35)", background: "var(--bg-1)" }}>
      {children}
    </div>
  );
}

export function MeasurePicker({ cat, onPick, onClose, open, allowNumber = true }: {
  cat: Catalog; onPick: (c: PickerChoice) => void; onClose: () => void; open: boolean; allowNumber?: boolean;
}) {
  const [q, setQ] = useState("");
  const groups = useMemo(() => measureGroups(cat), [cat]);
  const needle = q.trim().toLowerCase();
  const hit = (s: string) => !needle || s.toLowerCase().includes(needle);
  const item = (key: string, label: string, onClick: () => void, testId: string) => (
    <button key={key} type="button" data-testid={testId} onClick={onClick} className="cp-row-link"
      style={{ display: "block", width: "100%", textAlign: "left", padding: "6px 12px", border: 0, background: "transparent", color: "var(--cp-ink)", fontSize: 13, cursor: "pointer" }}>
      {label}
    </button>
  );
  const fundamentals = cat.fundamentals.filter((f) => hit(f.label) || hit(f.key));
  return (
    <Popover open={open} onClose={onClose} label="Choose a measure">
      <div style={{ padding: 10, borderBottom: "1px solid var(--cp-line)" }}>
        <input autoFocus aria-label="Search measures" data-testid="sb-picker-search" placeholder="Search: rsi, ema, close, pe…" value={q} onChange={(e) => setQ(e.target.value)}
          style={{ width: "100%", padding: "7px 9px", borderRadius: 8, border: "1px solid var(--line-2)", background: "var(--bg-2)", color: "var(--cp-ink)", fontSize: 13 }} />
      </div>
      <div className="cp-scroll" style={{ overflowY: "auto", padding: "4px 0 8px" }}>
        {allowNumber && hit("number") && (
          <div>
            <div className="cp-eyebrow" style={{ padding: "8px 12px 2px" }}>Value</div>
            {item("number", "Number", () => onPick({ kind: "number" }), "sb-picker-item-number")}
          </div>
        )}
        {groups.map((g) => {
          const items = g.items.filter((m) => hit(m.label) || hit(m.key));
          if (!items.length) return null;
          return (
            <div key={g.group}>
              <div className="cp-eyebrow" style={{ padding: "8px 12px 2px" }}>{g.group}</div>
              {items.map((m) => item(m.key, m.label, () => onPick({ kind: "measure", measure: m }), `sb-picker-item-${m.key}`))}
            </div>
          );
        })}
        {fundamentals.length > 0 && (
          <div>
            <div className="cp-eyebrow" style={{ padding: "8px 12px 2px" }}>Fundamentals · as of the last EOD</div>
            {fundamentals.map((f) => item(`f-${f.key}`, f.label, () => onPick({ kind: "fundamental", key: f.key }), `sb-picker-item-${f.key}`))}
          </div>
        )}
      </div>
    </Popover>
  );
}

// ── operand / expression ─────────────────────────────────────────────────────────────────────────────────────────────

const OFFSETS = [0, 1, 2, 3, 4, 5, 6, 7, 10, 14, 20, 30, 50, 52, 100, 200, 250];

function TimeframeSelect({ tf, cat, onChange }: { tf: Timeframe; cat: Catalog; onChange: (tf: Timeframe) => void }) {
  const tfs = cat.timeframes.length ? cat.timeframes : [{ key: "1d", label: "Daily", available: true }, { key: "1w", label: "Weekly", available: true }, { key: "1M", label: "Monthly", available: true }];
  return (
    <select aria-label="Timeframe" data-testid="sb-tf" value={tf} onChange={(e) => onChange(e.target.value as Timeframe)} style={tokenSelect(C.tf)}>
      {tfs.map((t) => (
        <option key={t.key} value={t.key} disabled={!t.available} title={t.available ? undefined : t.reason ?? "coming next"}>
          {t.label}{t.available ? "" : " — coming next"}
        </option>
      ))}
    </select>
  );
}

function OffsetSelect({ tf, offset, onChange }: { tf: string; offset: number; onChange: (n: number) => void }) {
  const opts = OFFSETS.includes(offset) ? OFFSETS : [...OFFSETS, offset].sort((a, b) => a - b);
  return (
    <select aria-label="Candle" data-testid="sb-offset" value={offset} onChange={(e) => onChange(Math.min(LIMITS.maxOffset, Math.max(0, Number(e.target.value))))} style={tokenSelect(C.tf)}>
      {opts.map((n) => <option key={n} value={n}>{offsetLabel(tf, n)}</option>)}
    </select>
  );
}

function Params({ m, def, onChange }: { m: MeasureOperand; def?: CatalogMeasure; onChange: (p: Record<string, ParamValue>) => void }) {
  const ps = def?.params ?? [];
  if (!ps.length) return null;
  return (
    <span className="inline-flex items-center" style={{ gap: 3, color: C.muted }}>
      (
      {ps.map((p, i) => {
        const v = m.params[p.name] ?? p.default ?? (p.type === "source" ? "close" : 0);
        const label = `${def?.label ?? m.measure} ${p.label ?? p.name}`;
        return (
          <span key={p.name} className="inline-flex items-center" style={{ gap: 3 }}>
            {i > 0 && ","}
            {p.type === "source" ? (
              <select aria-label={label} data-testid={`sb-param-${p.name}`} value={String(v)} onChange={(e) => onChange({ ...m.params, [p.name]: e.target.value })} style={tokenSelect(C.measure, 400)}>
                {SOURCES.map((s) => <option key={s} value={s}>{s}</option>)}
              </select>
            ) : (
              <NumberField small label={label} testId={`sb-param-${p.name}`} value={Number(v)} min={p.min} max={p.max} step={p.type === "int" ? 1 : "any"}
                onChange={(n) => onChange({ ...m.params, [p.name]: p.type === "int" ? Math.round(n) : n })} />
            )}
          </span>
        );
      })}
      )
    </span>
  );
}

/** One operand: Number box, or [timeframe] [candle] measure(params), or a fundamental; the name opens the picker. */
export function OperandEditor({ o, cat, onChange, side }: { o: Operand; cat: Catalog; onChange: (o: Operand) => void; side: string }) {
  const [open, setOpen] = useState(false);
  const pick = (c: PickerChoice) => {
    setOpen(false);
    if (c.kind === "number") onChange({ kind: "number", value: o.kind === "number" ? o.value : 0 });
    else if (c.kind === "fundamental") onChange({ kind: "fundamental", field: c.key });
    else onChange({ kind: "measure", tf: o.kind === "measure" ? o.tf : "1d", offset: o.kind === "measure" ? o.offset : 0, measure: c.measure.key, params: defaultParams(c.measure) });
  };
  const nameBtn = (label: string, color: string) => (
    <button type="button" aria-haspopup="dialog" aria-expanded={open} data-testid={`sb-measure-${side}`} title="Change what this compares"
      onClick={() => setOpen((v) => !v)}
      style={{ border: 0, background: "transparent", padding: "1px 2px", cursor: "pointer", color, fontWeight: 600, fontSize: 13.5, borderBottom: "1px dashed var(--line-2)", fontFamily: "var(--sans)" }}>
      {label}
    </button>
  );
  return (
    <span className="relative inline-flex flex-wrap items-center" style={{ gap: 5 }}>
      {o.kind === "number" && (
        <>
          {nameBtn("Number", C.measure)}
          <NumberField label="Number" testId="sb-number" value={o.value} onChange={(value) => onChange({ kind: "number", value })} />
        </>
      )}
      {o.kind === "fundamental" && nameBtn(cat.fundamentals.find((f) => f.key === o.field)?.label ?? o.field, C.measure)}
      {o.kind === "measure" && (() => {
        const def = cat.measures.find((m) => m.key === o.measure);
        return (
          <>
            <TimeframeSelect tf={o.tf} cat={cat} onChange={(tf) => onChange({ ...o, tf })} />
            <OffsetSelect tf={o.tf} offset={o.offset} onChange={(offset) => onChange({ ...o, offset })} />
            {nameBtn(def?.label ?? o.measure, C.measure)}
            <Params m={o} def={def} onChange={(params) => onChange({ ...o, params })} />
          </>
        );
      })()}
      <MeasurePicker cat={cat} open={open} onClose={() => setOpen(false)} onPick={pick} />
    </span>
  );
}

/** An expression, left to right: operand, then [+ − × ÷ operand]…; each added term can be removed. */
export function ExprEditor({ e, cat, onChange, side }: { e: Expr; cat: Catalog; onChange: (e: Expr) => void; side: string }) {
  return (
    <span className="inline-flex flex-wrap items-center" style={{ gap: "4px 6px" }} data-testid={`sb-expr-${side}`}>
      {e.terms.map((t, i) => (
        <span key={i} className="inline-flex flex-wrap items-center" style={{ gap: 5 }}>
          {i > 0 && (
            <select aria-label="Operation" data-testid="sb-arith" value={t.op ?? "*"} onChange={(ev) => onChange({ terms: e.terms.map((x, j) => (j === i ? { ...x, op: ev.target.value as ArithOp } : x)) })}
              style={tokenSelect(C.arith, 700)}>
              {(Object.keys(ARITH_LABEL) as ArithOp[]).map((a) => <option key={a} value={a}>{ARITH_LABEL[a]}</option>)}
            </select>
          )}
          <OperandEditor o={t.operand} cat={cat} side={`${side}-${i}`} onChange={(operand) => onChange({ terms: e.terms.map((x, j) => (j === i ? { ...x, operand } : x)) })} />
          {i > 0 && (
            <IconButton label="Remove this operation" testId="sb-term-remove" onClick={() => onChange({ terms: e.terms.filter((_, j) => j !== i) })}><X size={12} /></IconButton>
          )}
        </span>
      ))}
    </span>
  );
}

export function OpSelect({ op, cat, onChange }: { op: Op; cat: Catalog; onChange: (op: Op) => void }) {
  const ops = cat.operators.length ? cat.operators : (Object.keys(OP_LABEL) as Op[]).map((k) => ({ key: k, label: OP_LABEL[k] }));
  return (
    <select aria-label="Comparison" data-testid="sb-op" value={op} onChange={(e) => onChange(e.target.value as Op)} style={tokenSelect(C.op, 600)}>
      {ops.map((o) => <option key={o.key} value={o.key}>{o.label}</option>)}
    </select>
  );
}

/** The quiet "+ filter" / "+ group" / "+ column" buttons under a list. */
export function AddButton({ label, onClick, testId, disabled, title }: { label: string; onClick: () => void; testId: string; disabled?: boolean; title?: string }) {
  return (
    <button type="button" data-testid={testId} onClick={onClick} disabled={disabled} title={title ?? label} className="cp-chip"
      style={{ display: "inline-flex", alignItems: "center", gap: 6, padding: "5px 11px", fontSize: 12.5 }}>
      <Plus size={13} aria-hidden /> {label}
    </button>
  );
}

export { measureText, TF_LABEL };
