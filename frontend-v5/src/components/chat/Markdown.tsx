/**
 * Tiny markdown renderer for copilot answers.
 *
 * The LLM writes its narrative in markdown (headings, bullets, numbered lists,
 * **bold**, *italic*, `code`). Rendering it as raw text — which the chat used to
 * do via `whitespace-pre-wrap` — surfaces literal `**` / `###` / `-` characters
 * and reads as broken output. This component renders the small markdown subset
 * the copilot actually emits, with no extra dependency. It is intentionally
 * forgiving of half-written markdown so it looks right while tokens stream in
 * (an unclosed `**bold` simply shows as literal text until the closing `**`
 * arrives, then snaps to bold).
 */
import React from "react";
import { cn } from "@/lib/utils";

const INLINE_RE = /(\*\*([^*]+)\*\*|\*([^*\n]+)\*|`([^`]+)`)/g;
const BLOCK_LEAD = /^(#{1,3})\s|^\s*[-*]\s|^\s*\d+\.\s/;

function renderInline(text: string, keyBase: string): React.ReactNode[] {
  const nodes: React.ReactNode[] = [];
  let last = 0;
  let i = 0;
  let m: RegExpExecArray | null;
  INLINE_RE.lastIndex = 0;
  while ((m = INLINE_RE.exec(text)) !== null) {
    if (m.index > last) nodes.push(text.slice(last, m.index));
    if (m[2] !== undefined) {
      nodes.push(<strong key={`${keyBase}-${i}`} className="font-semibold text-ink">{m[2]}</strong>);
    } else if (m[3] !== undefined) {
      nodes.push(<em key={`${keyBase}-${i}`}>{m[3]}</em>);
    } else if (m[4] !== undefined) {
      nodes.push(
        <code key={`${keyBase}-${i}`} className="px-1 py-0.5 rounded bg-surface-2 text-[0.88em] font-mono">{m[4]}</code>,
      );
    }
    last = m.index + m[0].length;
    i++;
  }
  if (last < text.length) nodes.push(text.slice(last));
  return nodes;
}

export function Markdown(
  { children, className, caret }: { children: string; className?: string; caret?: boolean },
) {
  const lines = (children ?? "").replace(/\r\n/g, "\n").split("\n");
  const blocks: React.ReactNode[] = [];
  let i = 0;
  let key = 0;
  while (i < lines.length) {
    const line = lines[i];
    if (!line.trim()) { i++; continue; }

    const h = /^(#{1,3})\s+(.*)$/.exec(line);
    if (h) {
      const lvl = h[1].length;
      const cls = lvl === 1
        ? "text-[16px] font-semibold mt-3 mb-1"
        : lvl === 2 ? "text-[15px] font-semibold mt-3 mb-1" : "text-[14px] font-semibold mt-2 mb-0.5";
      blocks.push(<p key={key++} className={cn("text-ink leading-snug first:mt-0", cls)}>{renderInline(h[2], `h${key}`)}</p>);
      i++;
      continue;
    }

    if (/^\s*[-*]\s+/.test(line)) {
      const items: string[] = [];
      while (i < lines.length && /^\s*[-*]\s+/.test(lines[i])) { items.push(lines[i].replace(/^\s*[-*]\s+/, "")); i++; }
      blocks.push(
        <ul key={key++} className="list-disc pl-5 space-y-1 my-1.5 marker:text-ink-3">
          {items.map((it, idx) => <li key={idx}>{renderInline(it, `ul${key}-${idx}`)}</li>)}
        </ul>,
      );
      continue;
    }

    if (/^\s*\d+\.\s+/.test(line)) {
      const items: string[] = [];
      while (i < lines.length && /^\s*\d+\.\s+/.test(lines[i])) { items.push(lines[i].replace(/^\s*\d+\.\s+/, "")); i++; }
      blocks.push(
        <ol key={key++} className="list-decimal pl-5 space-y-1 my-1.5 marker:text-ink-3">
          {items.map((it, idx) => <li key={idx}>{renderInline(it, `ol${key}-${idx}`)}</li>)}
        </ol>,
      );
      continue;
    }

    const para: string[] = [];
    while (i < lines.length && lines[i].trim() && !BLOCK_LEAD.test(lines[i])) { para.push(lines[i]); i++; }
    blocks.push(<p key={key++} className="my-1.5 first:mt-0 last:mb-0">{renderInline(para.join(" "), `p${key}`)}</p>);
  }

  // Blinking caret riding the end of the last line while tokens stream in.
  if (caret) {
    const tip = (
      <span
        key="caret"
        className="inline-block w-[2px] h-[1.05em] ml-0.5 -mb-[0.12em] bg-accent align-baseline animate-caret"
      />
    );
    const last = blocks[blocks.length - 1];
    if (React.isValidElement(last) && last.type === "p") {
      blocks[blocks.length - 1] = React.cloneElement(
        last as React.ReactElement,
        {},
        ...React.Children.toArray((last as React.ReactElement).props.children),
        tip,
      );
    } else {
      blocks.push(<p key="caret-line" className="my-0">{tip}</p>);
    }
  }

  return <div className={className}>{blocks}</div>;
}
