/**
 * Scan Builder — the three Design panes of the owner's screenshots: Filters (the group tree), Columns (expression AS name) and
 * Group/Sort (group column, sort column + direction, number of symbols).
 */
import { useState, type ReactNode } from "react";
import {
  AddButton, ExprEditor, OpSelect, RowActions, tokenSelect, C,
} from "./editor-parts";
import {
  LIMITS, addChild, addTerm, countFilters, depthOf, duplicateNode, newColumn, newFilter, newGroup, newId, removeNode, updateNode,
  type Catalog, type ColumnDef, type ColumnFormat, type FilterNode, type GroupNode, type ScanSpec,
} from "./scan-model";

type NodeCounts = Record<string, { passed: number; unknown: number }> | null;

function CommentBox({ value, onChange, what }: { value: string; onChange: (v: string) => void; what: string }) {
  return (
    <input aria-label={`Comment on this ${what}`} data-testid="sb-comment-input" value={value} maxLength={200} placeholder="A note for yourself"
      onChange={(e) => onChange(e.target.value)}
      style={{ marginTop: 6, width: "min(100%, 420px)", padding: "5px 9px", borderRadius: 8, border: "1px solid var(--line-2)", background: "var(--bg-2)", color: "var(--cp-ink-2)", fontSize: 12.5 }} />
  );
}

// ── Filters ──────────────────────────────────────────────────────────────────────────────────────────────────────────

function FilterRow({ f, cat, root, setRoot, counts }: { f: FilterNode; cat: Catalog; root: GroupNode; setRoot: (g: GroupNode) => void; counts: NodeCounts }) {
  const [commentOpen, setCommentOpen] = useState(!!f.comment);
  const set = (patch: Partial<FilterNode>) => setRoot(updateNode(root, f.id, (n) => ({ ...(n as FilterNode), ...patch })));
  const tooMany = countFilters(root) >= LIMITS.maxFilters;
  return (
    <div data-testid="sb-filter-row" data-node-id={f.id} data-enabled={f.enabled} style={{ padding: "6px 0", opacity: f.enabled ? 1 : 0.5 }}>
      <div className="flex flex-wrap items-center" style={{ gap: "6px 8px" }}>
        <ExprEditor e={f.left} cat={cat} side="left" onChange={(left) => set({ left })} />
        <OpSelect op={f.op} cat={cat} onChange={(op) => set({ op })} />
        <ExprEditor e={f.right} cat={cat} side="right" onChange={(right) => set({ right })} />
        <RowActions
          what="filter" testPrefix="sb-filter"
          onTerm={() => set({ right: addTerm(f.right) })}
          onComment={() => setCommentOpen((v) => !v)} commentOn={commentOpen}
          onDuplicate={tooMany ? undefined : () => setRoot(duplicateNode(root, f.id))}
          enabled={f.enabled} onToggle={(enabled) => set({ enabled })}
          debug={counts ? counts[f.id] ?? null : null}
          onDelete={() => setRoot(removeNode(root, f.id))}
        />
      </div>
      {commentOpen && <CommentBox value={f.comment} what="filter" onChange={(comment) => set({ comment })} />}
    </div>
  );
}

function GroupBlock({ g, cat, root, setRoot, counts, isRoot }: { g: GroupNode; cat: Catalog; root: GroupNode; setRoot: (g: GroupNode) => void; counts: NodeCounts; isRoot?: boolean }) {
  const [commentOpen, setCommentOpen] = useState(!!g.comment);
  const set = (patch: Partial<GroupNode>) => setRoot(updateNode(root, g.id, (n) => ({ ...(n as GroupNode), ...patch })));
  const depth = depthOf(root, g.id) ?? 1;
  const tooMany = countFilters(root) >= LIMITS.maxFilters;
  const full = g.children.length >= LIMITS.maxChildren;
  const universes = cat.universes;
  return (
    <div data-testid={isRoot ? "sb-group-root" : "sb-group"} data-node-id={g.id} data-join={g.join} data-enabled={g.enabled}
      style={isRoot ? undefined : { marginTop: 6, paddingLeft: 14, borderLeft: "2px solid var(--line-2)", opacity: g.enabled ? 1 : 0.5 }}>
      <div className="flex flex-wrap items-center" style={{ gap: "4px 6px", fontSize: 13.5, color: "var(--cp-ink-2)" }}>
        <span>Stock passes</span>
        <select aria-label="All or any of the filters" data-testid="sb-join" value={g.join} onChange={(e) => set({ join: e.target.value as GroupNode["join"] })} style={tokenSelect(C.measure, 700)}>
          <option value="all">all</option>
          <option value="any">any</option>
        </select>
        <span>of the below filters in</span>
        <select aria-label="Segment" data-testid="sb-universe" value={g.universe ?? ""} onChange={(e) => set({ universe: e.target.value || (isRoot ? g.universe : null) })} style={tokenSelect(C.measure, 700)}>
          {!isRoot && <option value="">the same segment</option>}
          {universes.map((u) => <option key={u.key} value={u.key}>{u.label}{u.size ? ` (${u.size.toLocaleString("en-IN")})` : ""}</option>)}
        </select>
        <span>segment:</span>
        <RowActions
          what="group" testPrefix={isRoot ? "sb-root" : "sb-group"}
          onComment={() => setCommentOpen((v) => !v)} commentOn={commentOpen}
          onDuplicate={isRoot || tooMany ? undefined : () => setRoot(duplicateNode(root, g.id))}
          enabled={isRoot ? undefined : g.enabled} onToggle={isRoot ? undefined : (enabled) => set({ enabled })}
          debug={counts ? counts[g.id] ?? null : null}
          onDelete={isRoot ? undefined : () => setRoot(removeNode(root, g.id))}
        />
      </div>
      {commentOpen && <CommentBox value={g.comment} what="group" onChange={(comment) => set({ comment })} />}
      <div style={{ paddingLeft: isRoot ? 12 : 4 }}>
        {g.children.length === 0 && (
          <p className="m-0" data-testid="sb-group-empty" style={{ padding: "8px 0", fontSize: 12.5, color: "var(--cp-ink-3)" }}>
            {isRoot ? "No filters yet: every stock in the segment passes. Add a filter below." : "An empty group passes every stock."}
          </p>
        )}
        {g.children.map((c) => (c.kind === "filter"
          ? <FilterRow key={c.id} f={c} cat={cat} root={root} setRoot={setRoot} counts={counts} />
          : <GroupBlock key={c.id} g={c} cat={cat} root={root} setRoot={setRoot} counts={counts} />))}
        <div className="flex flex-wrap" style={{ gap: 8, padding: "8px 0 4px" }}>
          <AddButton label="filter" testId="sb-add-filter" disabled={tooMany || full} title={tooMany ? `At most ${LIMITS.maxFilters} filters` : "Add a filter to this group"}
            onClick={() => setRoot(addChild(root, g.id, newFilter(cat)))} />
          <AddButton label="group" testId="sb-add-group" disabled={depth >= LIMITS.maxDepth || full} title={depth >= LIMITS.maxDepth ? `Groups nest at most ${LIMITS.maxDepth} deep` : "Add a group of filters (all / any) inside this one"}
            onClick={() => setRoot(addChild(root, g.id, newGroup("any")))} />
        </div>
      </div>
    </div>
  );
}

export function FiltersPane({ spec, cat, onChange, counts }: { spec: ScanSpec; cat: Catalog; onChange: (s: ScanSpec) => void; counts: NodeCounts }) {
  return (
    <div data-testid="sb-pane-filters" className="flex min-w-0 flex-col">
      <GroupBlock isRoot g={spec.filters} cat={cat} root={spec.filters} counts={counts} setRoot={(filters) => onChange({ ...spec, filters })} />
      <p className="m-0" style={{ paddingTop: 6, fontSize: 12, color: "var(--cp-ink-3)" }}>
        Expressions read left to right, as written: Close − 1 day ago Close ÷ 1 day ago Close × 100 is the day’s % change.
        A filter with missing data (too little history, no fundamental) does not pass.
      </p>
    </div>
  );
}

// ── Columns ──────────────────────────────────────────────────────────────────────────────────────────────────────────

const FORMATS: Array<{ key: ColumnFormat; label: string }> = [
  { key: "pct", label: "%" }, { key: "price", label: "price" }, { key: "volume", label: "volume" }, { key: "number", label: "number" },
];

function ColumnRow({ c, cat, spec, onChange }: { c: ColumnDef; cat: Catalog; spec: ScanSpec; onChange: (s: ScanSpec) => void }) {
  const setCol = (patch: Partial<ColumnDef>) => onChange({ ...spec, columns: spec.columns.map((x) => (x.id === c.id ? { ...x, ...patch } : x)) });
  const full = spec.columns.length >= LIMITS.maxColumns;
  const isSort = spec.sort.column === c.id;
  return (
    <div data-testid="sb-column-row" data-col-id={c.id} data-enabled={c.enabled} className="flex flex-wrap items-center" style={{ gap: "6px 8px", padding: "6px 0", opacity: c.enabled ? 1 : 0.5 }}>
      <ExprEditor e={c.expr} cat={cat} side="col" onChange={(expr) => setCol({ expr })} />
      <RowActions
        what="column" testPrefix="sb-column"
        onTerm={() => setCol({ expr: addTerm(c.expr) })}
        onDuplicate={full ? undefined : () => {
          const i = spec.columns.findIndex((x) => x.id === c.id);
          const copy: ColumnDef = { ...JSON.parse(JSON.stringify(c)), id: newId("c"), alias: `${c.alias} copy`.slice(0, 40) };
          onChange({ ...spec, columns: [...spec.columns.slice(0, i + 1), copy, ...spec.columns.slice(i + 1)] });
        }}
        enabled={c.enabled} onToggle={isSort ? undefined : (enabled) => setCol({ enabled })}
        onDelete={spec.columns.length <= 1 || isSort ? undefined : () => onChange({ ...spec, columns: spec.columns.filter((x) => x.id !== c.id) })}
      />
      <span style={{ fontSize: 13, color: "var(--cp-ink-3)" }}>AS</span>
      <input aria-label="Column name" data-testid="sb-alias" value={c.alias} maxLength={40} onChange={(e) => setCol({ alias: e.target.value })}
        style={{ width: 130, padding: "3px 7px", borderRadius: 7, border: "1px solid var(--line-2)", background: "var(--bg-2)", color: "var(--cp-ink)", fontSize: 13, fontWeight: 600, textTransform: "uppercase" }} />
      <select aria-label="Show as" data-testid="sb-format" value={c.format} onChange={(e) => setCol({ format: e.target.value as ColumnFormat })} style={tokenSelect(C.muted)}>
        {FORMATS.map((f) => <option key={f.key} value={f.key}>{f.label}</option>)}
      </select>
      {isSort && <span className="cp-mono-note" title="The result is sorted by this column (Group/Sort)">sort</span>}
    </div>
  );
}

export function ColumnsPane({ spec, cat, onChange }: { spec: ScanSpec; cat: Catalog; onChange: (s: ScanSpec) => void }) {
  const full = spec.columns.length >= LIMITS.maxColumns;
  return (
    <div data-testid="sb-pane-columns" className="flex min-w-0 flex-col">
      {spec.columns.map((c) => <ColumnRow key={c.id} c={c} cat={cat} spec={spec} onChange={onChange} />)}
      <div style={{ paddingTop: 8 }}>
        <AddButton label="column" testId="sb-add-column" disabled={full} title={full ? `At most ${LIMITS.maxColumns} columns` : "Add a result column"}
          onClick={() => onChange({ ...spec, columns: [...spec.columns, newColumn()] })} />
      </div>
      <p className="m-0" style={{ paddingTop: 8, fontSize: 12, color: "var(--cp-ink-3)" }}>Symbol and company name are always shown first. The column the result is sorted by cannot be turned off or deleted.</p>
    </div>
  );
}

// ── Group / Sort ─────────────────────────────────────────────────────────────────────────────────────────────────────

function Line({ children }: { children: ReactNode }) {
  return <div className="flex flex-wrap items-center" style={{ gap: "6px 10px", padding: "14px 0", borderBottom: "1px solid var(--cp-line)", fontSize: 13.5, color: "var(--cp-ink-2)" }}>{children}</div>;
}

export function GroupSortPane({ spec, onChange }: { spec: ScanSpec; onChange: (s: ScanSpec) => void }) {
  const cols = spec.columns.filter((c) => c.enabled);
  return (
    <div data-testid="sb-pane-groupsort" className="flex min-w-0 flex-col">
      <Line>Group column: <strong style={{ color: "var(--cp-ink)" }}>Symbol</strong><span style={{ fontSize: 12, color: "var(--cp-ink-3)" }}>one row per stock</span></Line>
      <Line>
        Sort column:
        <select aria-label="Sort column" data-testid="sb-sort-column" value={spec.sort.column} onChange={(e) => onChange({ ...spec, sort: { ...spec.sort, column: e.target.value } })} style={tokenSelect(C.measure, 600)}>
          {cols.map((c) => <option key={c.id} value={c.id}>{c.alias}</option>)}
        </select>
        , direction:
        <select aria-label="Sort direction" data-testid="sb-sort-dir" value={spec.sort.dir} onChange={(e) => onChange({ ...spec, sort: { ...spec.sort, dir: e.target.value as "asc" | "desc" } })} style={tokenSelect(C.measure, 600)}>
          <option value="desc">Descending</option>
          <option value="asc">Ascending</option>
        </select>
      </Line>
      <div style={{ padding: "14px 0", borderBottom: "1px solid var(--cp-line)" }}>
        <label htmlFor="sb-limit" style={{ fontSize: 13.5, color: "var(--cp-ink-2)" }}>
          Number of symbols: <strong data-testid="sb-limit-value" className="cp-num" style={{ color: "var(--cp-ink)" }}>{spec.limit}</strong>
        </label>
        <input id="sb-limit" data-testid="sb-limit" type="range" min={LIMITS.minLimit} max={LIMITS.maxLimit} value={spec.limit}
          onChange={(e) => onChange({ ...spec, limit: Math.min(LIMITS.maxLimit, Math.max(LIMITS.minLimit, Number(e.target.value))) })}
          style={{ display: "block", width: "100%", marginTop: 10, accentColor: "var(--mint)" }} />
      </div>
      <p className="m-0" style={{ paddingTop: 10, fontSize: 12, color: "var(--cp-ink-3)" }}>
        Charts over time, other group columns and saving results to a watchlist are not in this version.
      </p>
    </div>
  );
}
