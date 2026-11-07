/**
 * Scan Builder — the scan definition (docs/scan_builder/DESIGN.md §3) and pure helpers to edit it. No React, no I/O.
 *
 * A scan is a filter tree (groups of filters, "Stock passes all / any of the below filters in <universe> segment"), result
 * columns (an expression AS an alias) and a sort / limit. Every number a run shows is computed by the backend on our own data
 * (NSE end-of-day bars, Kite quotes, NIDP fundamentals); nothing here evaluates a scan.
 *
 * Expressions are evaluated LEFT TO RIGHT as written (Chartink's rule, kept so a familiar formula reads the same):
 *   Close − 1 day ago Close ÷ 1 day ago Close × 100   ==   ((C − C1) ÷ C1) × 100
 */

export type Timeframe = "1d" | "1w" | "1M" | "5m" | "15m" | "1h";
export type Op = "gt" | "gte" | "lt" | "lte" | "eq" | "crosses_above" | "crosses_below";
export type ArithOp = "+" | "-" | "*" | "/";
export type Join = "all" | "any";
export type ColumnFormat = "number" | "pct" | "price" | "volume";
export type ParamValue = number | string;

export interface NumberOperand { kind: "number"; value: number }
export interface MeasureOperand { kind: "measure"; tf: Timeframe; offset: number; measure: string; params: Record<string, ParamValue> }
export interface FundamentalOperand { kind: "fundamental"; field: string }
export type Operand = NumberOperand | MeasureOperand | FundamentalOperand;

export interface Term { op: ArithOp | null; operand: Operand }
export interface Expr { terms: Term[] }

export interface FilterNode { id: string; kind: "filter"; left: Expr; op: Op; right: Expr; enabled: boolean; comment: string }
export interface GroupNode { id: string; kind: "group"; join: Join; universe: string | null; enabled: boolean; comment: string; children: ScanNode[] }
export type ScanNode = FilterNode | GroupNode;

export interface ColumnDef { id: string; alias: string; expr: Expr; enabled: boolean; format: ColumnFormat }
export interface ScanSpec {
  version: 1;
  name: string;
  description: string;
  filters: GroupNode;
  columns: ColumnDef[];
  sort: { column: string; dir: "asc" | "desc" };
  limit: number;
}

// ── catalog (GET /api/scan-builder/catalog), the parts the editor reads ─────────────────────────────────────────────

export interface CatalogParam { name: string; label?: string | null; type?: "int" | "float" | "source" | string | null; default?: ParamValue | null; min?: number | null; max?: number | null }
export interface CatalogMeasure { key: string; label: string; group?: string | null; params?: CatalogParam[] | null }
export interface CatalogFundamental { key: string; label: string; unit?: string | null }
export interface CatalogOperator { key: string; label: string }
export interface CatalogUniverse { key: string; label: string; size?: number | null }
export interface CatalogTimeframe { key: string; label: string; available: boolean; reason?: string | null }
export interface CatalogTemplate { key: string; name: string; description?: string | null; spec: ScanSpec }
export interface Catalog {
  measures: CatalogMeasure[];
  fundamentals: CatalogFundamental[];
  operators: CatalogOperator[];
  universes: CatalogUniverse[];
  timeframes: CatalogTimeframe[];
  templates: CatalogTemplate[];
  refresh_seconds: number;
  default_spec?: ScanSpec | null;
}

// ── limits (DESIGN §3) ───────────────────────────────────────────────────────────────────────────────────────────────

export const LIMITS = { maxDepth: 4, maxFilters: 40, maxColumns: 12, maxTerms: 8, maxChildren: 30, maxOffset: 250, minLimit: 1, maxLimit: 500 } as const;
export const SOURCES = ["open", "high", "low", "close", "volume"] as const;

export const OP_LABEL: Record<Op, string> = {
  gt: "Greater than", gte: "Greater than equal to", lt: "Less than", lte: "Less than equal to", eq: "Equals",
  crosses_above: "Crossed above", crosses_below: "Crossed below",
};
export const ARITH_LABEL: Record<ArithOp, string> = { "+": "+", "-": "−", "*": "×", "/": "÷" };
export const TF_LABEL: Record<string, string> = { "1d": "Daily", "1w": "Weekly", "1M": "Monthly", "5m": "5 minute", "15m": "15 minute", "1h": "1 hour" };
const TF_UNIT: Record<string, [string, string]> = { "1d": ["day", "days"], "1w": ["week", "weeks"], "1M": ["month", "months"], "5m": ["candle", "candles"], "15m": ["candle", "candles"], "1h": ["candle", "candles"] };

// ── ids ──────────────────────────────────────────────────────────────────────────────────────────────────────────────

let seq = 0;
/** A new node / column id, [A-Za-z0-9_-]{1,24} as the contract asks. */
export function newId(prefix: "f" | "g" | "c"): string {
  seq = (seq + 1) % 1_000_000;
  return `${prefix}${Date.now().toString(36).slice(-5)}${seq.toString(36)}${Math.floor(Math.random() * 1296).toString(36)}`.slice(0, 24);
}

// ── constructors ─────────────────────────────────────────────────────────────────────────────────────────────────────

export const num = (value: number): Operand => ({ kind: "number", value });
export const measure = (name: string, opts: { tf?: Timeframe; offset?: number; params?: Record<string, ParamValue> } = {}): MeasureOperand => (
  { kind: "measure", tf: opts.tf ?? "1d", offset: opts.offset ?? 0, measure: name, params: opts.params ?? {} }
);
export const expr = (...operands: Array<Operand | [ArithOp, Operand]>): Expr => ({
  terms: operands.map((o, i) => (Array.isArray(o) ? { op: o[0], operand: o[1] } : { op: i === 0 ? null : "*", operand: o })),
});

/** The params a measure starts with: its catalog defaults. */
export function defaultParams(m: CatalogMeasure | undefined): Record<string, ParamValue> {
  const out: Record<string, ParamValue> = {};
  for (const p of m?.params ?? []) if (p.default != null) out[p.name] = p.default;
  return out;
}

export function newFilter(cat?: Catalog | null): FilterNode {
  const close = cat?.measures.find((m) => m.key === "close");
  return { id: newId("f"), kind: "filter", left: { terms: [{ op: null, operand: measure(close?.key ?? "close") }] }, op: "gt", right: { terms: [{ op: null, operand: num(0) }] }, enabled: true, comment: "" };
}

export function newGroup(join: Join = "all"): GroupNode {
  return { id: newId("g"), kind: "group", join, universe: null, enabled: true, comment: "", children: [] };
}

export function newColumn(): ColumnDef {
  return { id: newId("c"), alias: "Close", expr: { terms: [{ op: null, operand: measure("close") }] }, enabled: true, format: "price" };
}

/** The scan a new draft starts from when the catalog sends none (DESIGN §3 "Default new scan"). */
export function localDefaultSpec(): ScanSpec {
  const chg: ColumnDef = {
    id: "c_chg", alias: "% Change", enabled: true, format: "pct",
    expr: expr(measure("close"), ["-", measure("close", { offset: 1 })], ["/", measure("close", { offset: 1 })], ["*", num(100)]),
  };
  return {
    version: 1, name: "New scan", description: "",
    filters: { id: "g_root", kind: "group", join: "all", universe: "cash", enabled: true, comment: "", children: [] },
    columns: [chg, { id: "c_price", alias: "Price", enabled: true, format: "price", expr: expr(measure("close")) }, { id: "c_vol", alias: "Volume", enabled: true, format: "volume", expr: expr(measure("volume")) }],
    sort: { column: "c_chg", dir: "desc" },
    limit: 50,
  };
}

export const clone = <T,>(v: T): T => JSON.parse(JSON.stringify(v)) as T;
export const sameSpec = (a: ScanSpec | null | undefined, b: ScanSpec | null | undefined): boolean => JSON.stringify(a ?? null) === JSON.stringify(b ?? null);

// ── tree edits (immutable) ───────────────────────────────────────────────────────────────────────────────────────────

/** `root` with node `id` replaced by fn(node). */
export function updateNode(root: GroupNode, id: string, fn: (n: ScanNode) => ScanNode): GroupNode {
  if (root.id === id) return fn(root) as GroupNode;
  return { ...root, children: root.children.map((c) => (c.id === id ? fn(c) : c.kind === "group" ? updateNode(c, id, fn) : c)) };
}

export function removeNode(root: GroupNode, id: string): GroupNode {
  return { ...root, children: root.children.filter((c) => c.id !== id).map((c) => (c.kind === "group" ? removeNode(c, id) : c)) };
}

/** A deep copy of a node with fresh ids. */
export function withNewIds<T extends ScanNode>(n: T): T {
  if (n.kind === "filter") return { ...clone(n), id: newId("f") };
  return { ...clone(n), id: newId("g"), children: n.children.map((c) => withNewIds(c)) } as T;
}

/** `root` with a copy of node `id` inserted right after it. */
export function duplicateNode(root: GroupNode, id: string): GroupNode {
  const out: ScanNode[] = [];
  for (const c of root.children) {
    const next = c.kind === "group" ? duplicateNode(c, id) : c;
    out.push(next);
    if (c.id === id) out.push(withNewIds(c));
  }
  return { ...root, children: out };
}

export function addChild(root: GroupNode, groupId: string, child: ScanNode): GroupNode {
  return updateNode(root, groupId, (g) => (g.kind === "group" ? { ...g, children: [...g.children, child] } : g));
}

export function countFilters(g: GroupNode): number {
  return g.children.reduce((n, c) => n + (c.kind === "filter" ? 1 : countFilters(c)), 0);
}

/** Depth of a group (root = 1). */
export function depthOf(root: GroupNode, id: string, d = 1): number | null {
  if (root.id === id) return d;
  for (const c of root.children) {
    if (c.kind === "group") {
      const r = depthOf(c, id, d + 1);
      if (r != null) return r;
    }
  }
  return null;
}

export function addTerm(e: Expr, op: ArithOp = "*", operand: Operand = num(1)): Expr {
  return e.terms.length >= LIMITS.maxTerms ? e : { terms: [...e.terms, { op, operand }] };
}

export function removeTerm(e: Expr, index: number): Expr {
  if (index <= 0 || e.terms.length <= 1) return e;
  return { terms: e.terms.filter((_, i) => i !== index) };
}

export function setTerm(e: Expr, index: number, t: Term): Expr {
  return { terms: e.terms.map((x, i) => (i === index ? { ...t, op: i === 0 ? null : t.op ?? "*" } : x)) };
}

// ── words for the screen ─────────────────────────────────────────────────────────────────────────────────────────────

/** "latest" for 0, "1 day ago", "3 weeks ago", … */
export function offsetLabel(tf: string, offset: number): string {
  if (!offset) return "latest";
  const [one, many] = TF_UNIT[tf] ?? ["candle", "candles"];
  return `${offset} ${offset === 1 ? one : many} ago`;
}

/** "RSI(14)", "EMA(close, 21)", "Close". Params in the catalog's order. */
export function measureText(m: MeasureOperand, cat?: Catalog | null): string {
  const def = cat?.measures.find((x) => x.key === m.measure);
  const label = def?.label ?? m.measure;
  const order = (def?.params ?? []).map((p) => p.name);
  const keys = [...order, ...Object.keys(m.params).filter((k) => !order.includes(k))];
  const vals = keys.filter((k) => m.params[k] != null).map((k) => String(m.params[k]));
  return vals.length ? `${label}(${vals.join(", ")})` : label;
}

/** One operand as plain words, e.g. "Daily 1 day ago Close", "Weekly RSI(14)", "Number 55", "PE (TTM)". */
export function operandText(o: Operand, cat?: Catalog | null): string {
  if (o.kind === "number") return `Number ${o.value}`;
  if (o.kind === "fundamental") return cat?.fundamentals.find((f) => f.key === o.field)?.label ?? o.field;
  const off = o.offset ? `${offsetLabel(o.tf, o.offset)} ` : "";
  return `${TF_LABEL[o.tf] ?? o.tf} ${off}${measureText(o, cat)}`;
}

/** An expression left to right: "Daily Close − Daily 1 day ago Close ÷ …". */
export function exprText(e: Expr, cat?: Catalog | null): string {
  return e.terms.map((t, i) => `${i ? `${ARITH_LABEL[t.op ?? "*"]} ` : ""}${operandText(t.operand, cat)}`).join(" ");
}

export function filterText(f: FilterNode, cat?: Catalog | null): string {
  return `${exprText(f.left, cat)} ${OP_LABEL[f.op] ?? f.op} ${exprText(f.right, cat)}`;
}

/** The measure groups in the picker's order; the catalog's own groups come first, in the order they appear. */
export function measureGroups(cat: Catalog): Array<{ group: string; items: CatalogMeasure[] }> {
  const out: Array<{ group: string; items: CatalogMeasure[] }> = [];
  for (const m of cat.measures) {
    const g = m.group || "Other";
    let slot = out.find((x) => x.group === g);
    if (!slot) out.push((slot = { group: g, items: [] }));
    slot.items.push(m);
  }
  return out;
}

/** Problems the editor can see before a run (the server validates fully). */
export function draftProblems(s: ScanSpec): string[] {
  const out: string[] = [];
  if (!s.name.trim()) out.push("The scan needs a name.");
  if (s.name.length > 80) out.push("The name is longer than 80 characters.");
  if (countFilters(s.filters) > LIMITS.maxFilters) out.push(`At most ${LIMITS.maxFilters} filters.`);
  if (!s.columns.length) out.push("Add at least one column.");
  if (s.columns.some((c) => !c.alias.trim())) out.push("Every column needs a name after AS.");
  return out;
}
