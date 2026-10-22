/**
 * Smart trading desk — the stock search box shared by the desk header, the Strategy Builder and the Options & futures lab.
 *
 * Google-like type-ahead over every NSE stock: a symbol, part of a company name ("pc jew"), an ISIN, or a typo ("pcjewellers").
 *
 *   GET /api/markets/symbol-lookup?q=&limit=&fno_only=   ranked stocks, with the matched part to highlight (symbol-lookup-data.ts)
 *   localStorage `nivesh.desk.symbol-recents`            the last 8 stocks picked in this browser (not sent anywhere)
 *   topSetups (a prop)                                   today's scanner list the desk already holds, shown for empty text
 *
 * The box is a controlled input (`value`, `onChange`) so a parent form keeps its own submit: Enter with no highlighted result is
 * left to the form (the header turns a question into a Copilot ask; the lab and the builder take the typed ticker as before).
 * Enter on a highlighted result, a click or a tap calls `onSelect(symbol)`. A lookup that fails shows one quiet line and leaves
 * the box working as it did before there was a lookup. ARIA: combobox + listbox + option, aria-activedescendant, aria-expanded.
 */
import { useEffect, useId, useMemo, useRef, useState, type CSSProperties, type KeyboardEvent, type ReactNode } from "react";
import { StockIcon } from "../../components/EntityIcon";
import type { DeskPersona } from "./context";
import {
  LOOKUP_DEBOUNCE_MS, clearRecents, pushRecent, readRecents, useLookup, type LookupResult, type Recent,
} from "./symbol-lookup-data";

export { LOOKUP_DEBOUNCE_MS };

export interface SetupHint { symbol: string; name?: string | null }

export interface SymbolSearchProps {
  value: string;
  onChange: (text: string) => void;
  /** A result was picked (Enter on a highlighted row, a click or a tap). */
  onSelect: (symbol: string, item: LookupResult | null) => void;
  persona: DeskPersona;
  /** Only stocks in the F&O master (the Options & futures lab). */
  fnoOnly?: boolean;
  /** Today's scanner list for the empty box; without it the lookup's own popular list is used. */
  topSetups?: SetupHint[];
  placeholder?: string;
  ariaLabel: string;
  inputTestId: string;
  /** Prefix of the dropdown's test ids (default "symsearch"). */
  testIdPrefix?: string;
  inputId?: string;
  inputStyle?: CSSProperties;
  autoFocus?: boolean;
  invalid?: boolean;
  maxLength?: number;
  /** Hang the list from the nearest positioned ancestor instead of this box (the header pill, which is wider than the input). */
  anchorToParent?: boolean;
  /** Minimum width of the dropdown in px when the box is narrower than a row needs. */
  listMinWidth?: number;
  /** The text when the box loses focus (the builder checks the symbol then). */
  onBlurText?: (text: string) => void;
  /** Shown beside the input inside its wrapper (an icon). */
  leading?: ReactNode;
}

const PLAIN = {
  fno: "Options available", scan: "On today’s AI list", recent: "Recent", top: "Top setups today", none: "No prices",
};
const TRADER = { fno: "F&O", scan: "In today’s scan", recent: "Recent", top: "Top setups today", none: "No prices" };

/** Merge highlight ranges into text pieces: [text, highlighted]. */
export function pieces(text: string, ranges: Array<[number, number]> | undefined): Array<[string, boolean]> {
  if (!ranges || ranges.length === 0) return [[text, false]];
  const rs = [...ranges].filter(([s, e]) => e > s && s >= 0 && s < text.length).sort((a, b) => a[0] - b[0]);
  const out: Array<[string, boolean]> = [];
  let at = 0;
  for (const [s, e0] of rs) {
    const e = Math.min(e0, text.length);
    if (s < at) continue;
    if (s > at) out.push([text.slice(at, s), false]);
    out.push([text.slice(s, e), true]);
    at = e;
  }
  if (at < text.length) out.push([text.slice(at), false]);
  return out;
}

function Marked({ text, ranges }: { text: string; ranges?: Array<[number, number]> }) {
  return (
    <>
      {pieces(text, ranges).map(([t, on], i) => (on ? <mark key={i} data-testid="symsearch-mark" style={{ background: "transparent", color: "var(--mint)", fontWeight: 700 }}>{t}</mark> : <span key={i}>{t}</span>))}
    </>
  );
}

interface Row { key: string; symbol: string; name: string | null; item: LookupResult | null; section?: string }

const tag: CSSProperties = { flex: "none", fontSize: 10, letterSpacing: "0.04em", padding: "2px 6px", borderRadius: 999, border: "1px solid var(--line-2)", color: "var(--cp-ink-3)", whiteSpace: "nowrap" };

export function SymbolSearch(p: SymbolSearchProps) {
  const uid = useId().replace(/:/g, "");
  const tp = p.testIdPrefix ?? "symsearch";
  const words = p.persona === "investor" ? PLAIN : TRADER;
  const [open, setOpen] = useState(false);
  const [active, setActive] = useState(-1);
  const [recents, setRecents] = useState<Recent[]>(() => readRecents());
  const box = useRef<HTMLDivElement>(null);
  const text = p.value;
  const t = text.trim();
  const lookup = useLookup(text, { enabled: open, wantEmpty: !p.topSetups, fnoOnly: p.fnoOnly, limit: 8 });
  const lookupData = lookup.status === "ok" ? lookup.data : lookup.status === "loading" ? lookup.prev : null;
  const listId = `${uid}-list`;

  const rows: Row[] = useMemo(() => {
    if (t) {
      return (lookupData?.results ?? []).map((r) => ({ key: r.symbol, symbol: r.symbol, name: r.name ?? null, item: r }));
    }
    const out: Row[] = [];
    const seen = new Set<string>();
    for (const r of recents) {
      if (seen.has(r.symbol)) continue;
      seen.add(r.symbol);
      out.push({ key: `r-${r.symbol}`, symbol: r.symbol, name: r.name, item: null, section: words.recent });
    }
    const top: SetupHint[] = p.topSetups ?? (lookupData?.popular ?? []).map((x) => ({ symbol: x.symbol, name: x.name ?? null }));
    for (const s of top.slice(0, 8)) {
      out.push({ key: `t-${s.symbol}`, symbol: s.symbol, name: s.name ?? null, item: null, section: words.top });
    }
    return out;
  }, [t, lookupData, recents, p.topSetups, p.fnoOnly, words.recent, words.top]);

  useEffect(() => { setActive(-1); }, [t, rows.length]);

  const choose = (r: Row) => {
    setOpen(false);
    setActive(-1);
    setRecents(pushRecent({ symbol: r.symbol, name: r.name }));
    p.onSelect(r.symbol, r.item);
  };

  const onKey = (e: KeyboardEvent<HTMLInputElement>) => {
    if (e.key === "ArrowDown" || e.key === "ArrowUp") {
      e.preventDefault();
      if (!open) { setOpen(true); return; }
      if (rows.length === 0) return;
      const dir = e.key === "ArrowDown" ? 1 : -1;
      setActive((a) => (a < 0 ? (dir === 1 ? 0 : rows.length - 1) : (a + dir + rows.length) % rows.length));
    } else if (e.key === "Enter") {
      if (open && active >= 0 && rows[active]) { e.preventDefault(); choose(rows[active]); }
      else setOpen(false);                                   // not ours: the parent form's submit takes the typed text
    } else if (e.key === "Escape") {
      if (open) { e.preventDefault(); setOpen(false); setActive(-1); }
    } else if (e.key === "Tab") {
      setOpen(false);
    }
  };

  const activeId = open && active >= 0 && rows[active] ? `${uid}-opt-${active}` : undefined;
  const showList = open && (t ? true : rows.length > 0 || lookup.status === "loading");
  const status = lookup.status;
  let sectionSeen = "";

  const body = (() => {
    if (t && status === "error") {
      return (
        <li role="presentation" data-testid={`${tp}-error`} style={{ padding: "10px 12px", fontSize: 12.5, color: "var(--cp-ink-3)" }}>
          Search isn’t available right now. Press Enter to use “{t.toUpperCase()}” as typed.
        </li>
      );
    }
    if (t && rows.length === 0) {
      if (status === "loading" || status === "idle") return <li role="presentation" data-testid={`${tp}-loading`} style={{ padding: "10px 12px", fontSize: 12.5, color: "var(--cp-ink-3)" }}>Searching…</li>;
      return (
        <li role="presentation" data-testid={`${tp}-empty`} style={{ padding: "10px 12px", fontSize: 12.5, color: "var(--cp-ink-2)" }}>
          <div>{p.fnoOnly ? `No F&O stock matches “${t}”` : `No NSE stock matches “${t}”`}</div>
          <div style={{ color: "var(--cp-ink-3)", marginTop: 3 }}>Try the ticker, part of the company name, or its ISIN.</div>
        </li>
      );
    }
    return rows.map((r, i) => {
      const it = r.item;
      const head = r.section && r.section !== sectionSeen ? r.section : null;
      if (r.section) sectionSeen = r.section;
      const on = i === active;
      return (
        <li key={r.key} role="presentation" style={{ listStyle: "none" }}>
          {head && (
            <div role="presentation" data-testid={`${tp}-section-${head === words.recent ? "recent" : "top"}`} className="flex items-center justify-between" style={{ padding: "8px 12px 4px", fontSize: 10, letterSpacing: "0.1em", textTransform: "uppercase", color: "var(--cp-ink-3)" }}>
              <span>{head}</span>
              {head === words.recent && (
                <button type="button" data-testid={`${tp}-recent-clear`} onMouseDown={(e) => e.preventDefault()} onClick={() => setRecents(clearRecents())} style={{ border: 0, background: "none", color: "var(--cp-ink-3)", cursor: "pointer", fontSize: 11, textTransform: "none", letterSpacing: 0, textDecoration: "underline" }}>Clear</button>
              )}
            </div>
          )}
          <div
            id={`${uid}-opt-${i}`} role="option" aria-selected={on} data-testid={`${tp}-option-${r.symbol}`} data-active={on ? "true" : "false"}
            data-nopx={it?.has_prices === false ? "true" : undefined}
            onMouseDown={(e) => e.preventDefault()} onMouseMove={() => setActive(i)} onClick={() => choose(r)}
            className="flex items-center"
            style={{ gap: 10, minHeight: 44, padding: "6px 12px", cursor: "pointer", background: on ? "var(--bg-3)" : "transparent", opacity: it?.has_prices === false ? 0.7 : 1 }}
          >
            <StockIcon symbol={r.symbol} name={r.name} size={26} />
            <span className="flex min-w-0 flex-1 flex-col" style={{ lineHeight: 1.25 }}>
              <span className="cp-num" style={{ fontSize: 13, color: "var(--cp-ink)" }}><Marked text={r.symbol} ranges={it?.highlight?.symbol} /></span>
              {r.name && <span style={{ fontSize: 12, color: "var(--cp-ink-3)", overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}><Marked text={r.name} ranges={it?.highlight?.name} /></span>}
            </span>
            <span className="flex items-center justify-end" style={{ gap: 4, flex: "0 1 auto", maxWidth: "55%", minWidth: 0, overflow: "hidden", flexWrap: "nowrap" }}>
              {it?.fno_eligible && <span style={tag}>{words.fno}</span>}
              {it?.in_scanner && <span style={tag}>{words.scan}</span>}
              {it?.has_prices === false && <span style={{ ...tag, color: "var(--amber)" }}>{words.none}</span>}
              {it?.sector && <span style={{ ...tag, flex: "0 1 auto", minWidth: 0, maxWidth: 120, overflow: "hidden", textOverflow: "ellipsis" }}>{it.sector}</span>}
            </span>
          </div>
        </li>
      );
    });
  })();

  return (
    <div
      ref={box} className={`${p.anchorToParent ? "" : "relative "}flex min-w-0 items-center`} style={{ flex: 1, gap: 8 }}
      onBlur={(e) => {
        if (box.current && e.relatedTarget instanceof Node && box.current.contains(e.relatedTarget)) return;
        setOpen(false);
        p.onBlurText?.(text);
      }}
    >
      {p.leading}
      <input
        id={p.inputId} data-testid={p.inputTestId} role="combobox" aria-expanded={showList} aria-controls={listId} aria-autocomplete="list"
        aria-activedescendant={activeId} aria-label={p.ariaLabel} aria-invalid={p.invalid || undefined} aria-haspopup="listbox"
        value={text} placeholder={p.placeholder} maxLength={p.maxLength ?? 40} autoComplete="off" autoCapitalize="none" spellCheck={false} autoFocus={p.autoFocus}
        onChange={(e) => { p.onChange(e.target.value); setOpen(true); }}
        onFocus={() => setOpen(true)}
        onClick={() => setOpen(true)}
        onKeyDown={onKey}
        style={p.inputStyle}
      />
      {showList && (
        <ul
          id={listId} role="listbox" aria-label={p.ariaLabel} data-testid={`${tp}-listbox`} data-debounce-ms={LOOKUP_DEBOUNCE_MS}
          className="m-0 p-0"
          style={{ position: "absolute", top: "calc(100% + 6px)", left: 0, right: 0, zIndex: 40, maxHeight: "min(60vh, 420px)", overflowY: "auto", overflowX: "hidden", borderRadius: 14, background: "var(--bg-2)", border: "1px solid var(--line-2)", boxShadow: "0 12px 32px rgba(0,0,0,0.35)", listStyle: "none", paddingBottom: 4, paddingTop: 4, opacity: status === "loading" && t ? 0.7 : 1, minWidth: p.listMinWidth ? `min(${p.listMinWidth}px, 92vw)` : 0 }}
        >
          {body}
        </ul>
      )}
      <span role="status" aria-live="polite" className="sr-only" style={{ position: "absolute", width: 1, height: 1, overflow: "hidden", clip: "rect(0 0 0 0)" }}>
        {open && t && status === "ok" ? `${rows.length} ${rows.length === 1 ? "match" : "matches"}` : ""}
      </span>
    </div>
  );
}
