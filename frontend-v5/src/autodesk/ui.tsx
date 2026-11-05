/**
 * Small building blocks that copy the prototype's markup (docs/autodesk/design/prototype/TD*.dc.html): eyebrows,
 * pills, cards, metric tiles, section headers, and the states every screen needs (loading, error, empty, Phase 2).
 * Styling is the design system's classes plus inline styles, as in the prototype.
 */
import type { CSSProperties, ReactNode } from "react";
import { Link } from "react-router-dom";
import { errorText, isUnauthorized } from "./api";

export type Tone = "mint" | "amber" | "danger" | "indigo" | "ink" | "ink2" | "ink3";

export const toneVar: Record<Tone, string> = {
  mint: "var(--mint)",
  amber: "var(--amber)",
  danger: "var(--danger)",
  indigo: "var(--indigo)",
  ink: "var(--ink)",
  ink2: "var(--ink-2)",
  ink3: "var(--ink-3)",
};

export function Eyebrow({ children, style }: { children: ReactNode; style?: CSSProperties }) {
  return <span className="nv-eyebrow" style={style}>{children}</span>;
}

export function Dot({ tone = "mint", style }: { tone?: Tone; style?: CSSProperties }) {
  return <span className="nv-dot" style={{ background: toneVar[tone], flex: "none", ...style }} />;
}

/** nv-pill with an optional dot. tone "ink" is the plain pill. */
export function Pill({ tone = "ink", dot, children, style, title, onClick }: {
  tone?: Tone; dot?: boolean; children: ReactNode; style?: CSSProperties; title?: string; onClick?: () => void;
}) {
  const cls = tone === "mint" || tone === "amber" || tone === "danger" || tone === "indigo" ? `nv-pill nv-pill-${tone}` : "nv-pill";
  const clickable = onClick ? { role: "button", tabIndex: 0, onKeyDown: (e: React.KeyboardEvent) => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); onClick(); } } } : {};
  return (
    <span className={cls} style={{ ...(onClick ? { cursor: "pointer" } : {}), ...style }} title={title} onClick={onClick} {...clickable}>
      {dot && <Dot tone={tone === "ink" || tone === "ink2" || tone === "ink3" ? "ink3" : tone} />}
      {children}
    </span>
  );
}

/** Screen header: eyebrow line with pills, a display-serif headline, an optional sub line. */
export function ScreenHeader({ eyebrow, pills, title, sub, mobile }: {
  eyebrow: ReactNode; pills?: ReactNode; title: ReactNode; sub?: ReactNode; mobile?: boolean;
}) {
  return (
    <section style={{ display: "flex", flexDirection: "column", gap: 12 }}>
      <div style={{ display: "flex", flexWrap: "wrap", gap: 8, alignItems: "center" }}>
        <Eyebrow>{eyebrow}</Eyebrow>
        {pills}
      </div>
      <h1 style={{ margin: 0, fontFamily: "var(--display)", fontWeight: 400, fontSize: mobile ? 30 : 44, lineHeight: 1.06, letterSpacing: "-0.02em", textWrap: "pretty", maxWidth: 920 } as CSSProperties}>
        {title}
      </h1>
      {sub && <p style={{ margin: 0, fontSize: 14.5, lineHeight: 1.55, color: "var(--ink-3)", maxWidth: 680, textWrap: "pretty" } as CSSProperties}>{sub}</p>}
    </section>
  );
}

/** "EYEBROW ........ Link ›" row above a block. */
export function SectionHead({ label, link, onLink, to }: { label: ReactNode; link?: string; onLink?: () => void; to?: string }) {
  return (
    <div style={{ display: "flex", justifyContent: "space-between", gap: 8, flexWrap: "wrap", alignItems: "baseline" }}>
      <Eyebrow>{label}</Eyebrow>
      {link && to && <Link to={to} className="ad-link">{link} ›</Link>}
      {link && !to && onLink && <button type="button" className="ad-link" onClick={onLink}>{link} ›</button>}
    </div>
  );
}

export function Card({ children, style, pad = "18px 22px", onClick, shadow = true }: {
  children: ReactNode; style?: CSSProperties; pad?: string; onClick?: () => void; shadow?: boolean;
}) {
  return (
    <div
      onClick={onClick}
      className={onClick ? "ad-hover-line" : undefined}
      style={{
        display: "flex", flexDirection: "column", gap: 10, padding: pad, borderRadius: 14, border: "1px solid var(--line)",
        background: "var(--bg-1)", boxShadow: shadow ? "var(--shadow-card)" : undefined, cursor: onClick ? "pointer" : undefined, ...style,
      }}
    >
      {children}
    </div>
  );
}

/** Bordered list container (rows separated by a top border), as the prototype's tables. */
export function ListBox({ children, style }: { children: ReactNode; style?: CSSProperties }) {
  return (
    <div style={{ border: "1px solid var(--line)", borderRadius: 14, background: "var(--bg-1)", boxShadow: "var(--shadow-card)", overflow: "hidden", ...style }}>
      {children}
    </div>
  );
}

/** Metric tile: eyebrow, display-serif value, small note. */
export function Tile({ k, v, s, tone = "ink", onClick, testId }: {
  k: ReactNode; v: ReactNode; s?: ReactNode; tone?: Tone; onClick?: () => void; testId?: string;
}) {
  return (
    <div
      data-testid={testId}
      onClick={onClick}
      className={onClick ? "ad-hover-line" : undefined}
      style={{ display: "flex", flexDirection: "column", gap: 5, padding: "14px 16px", borderRadius: 12, border: "1px solid var(--line)", background: "var(--bg-1)", cursor: onClick ? "pointer" : undefined, transition: "all .15s ease" }}
    >
      <span className="nv-eyebrow" style={{ fontSize: 9.5 }}>{k}</span>
      <span className="nv-num" style={{ fontFamily: "var(--display)", fontSize: 24, lineHeight: 1.1, color: toneVar[tone] }}>{v}</span>
      {s && <span style={{ fontSize: 11.5, lineHeight: 1.4, color: "var(--ink-3)" }}>{s}</span>}
    </div>
  );
}

export function TileGrid({ children, min = "200px" }: { children: ReactNode; min?: string }) {
  return <section style={{ display: "grid", gridTemplateColumns: `repeat(auto-fill,minmax(${min},1fr))`, gap: 10 }}>{children}</section>;
}

export function Button({ children, onClick, kind = "plain", disabled, type = "button", style, testId, title }: {
  children: ReactNode; onClick?: () => void; kind?: "plain" | "primary" | "danger" | "mint"; disabled?: boolean;
  type?: "button" | "submit"; style?: CSSProperties; testId?: string; title?: string;
}) {
  const k: Record<string, CSSProperties> = {
    plain: { border: "1px solid var(--line-2)", background: "var(--bg-2)", color: "var(--ink)" },
    primary: { border: "1px solid transparent", background: "var(--mint)", color: "#06120B", fontWeight: 500 },
    danger: { border: "1px solid var(--danger-line)", background: "var(--danger-soft)", color: "var(--danger)" },
    mint: { border: "1px solid var(--mint-line)", background: "var(--mint-soft)", color: "var(--mint)" },
  };
  return (
    <button
      type={type}
      data-testid={testId}
      title={title}
      disabled={disabled}
      onClick={onClick}
      style={{ cursor: disabled ? "not-allowed" : "pointer", opacity: disabled ? 0.55 : 1, padding: "8px 14px", borderRadius: 10, fontSize: 13, fontFamily: "var(--sans)", ...k[kind], ...style }}
    >
      {children}
    </button>
  );
}

export function Loading({ label = "Loading", rows = 3 }: { label?: string; rows?: number }) {
  return (
    <div aria-busy="true" aria-label={label} style={{ display: "flex", flexDirection: "column", gap: 10 }}>
      {Array.from({ length: rows }).map((_, i) => <div key={i} className="ad-skel" style={{ height: i === 0 ? 44 : 64 }} />)}
    </div>
  );
}

/** The API's own error, shown in place. A 401 tells the person to sign in again. */
export function ErrorBox({ error, what, onRetry }: { error: unknown; what?: string; onRetry?: () => void }) {
  const signedOut = isUnauthorized(error);
  return (
    <div role="alert" data-testid="error-box" style={{ display: "flex", flexDirection: "column", gap: 8, padding: "14px 18px", borderRadius: 12, border: "1px solid var(--danger-line)", background: "var(--danger-soft)", fontSize: 13.5, color: "var(--ink-2)" }}>
      <span className="nv-eyebrow" style={{ color: "var(--danger)" }}>{signedOut ? "Signed out" : `Could not load${what ? ` ${what}` : ""}`}</span>
      <span>{signedOut ? <>Your session has ended. <a href="/v5/login">Sign in</a> and come back to /autodesk/.</> : errorText(error)}</span>
      {onRetry && !signedOut && <span><button type="button" className="ad-link" onClick={onRetry}>Try again ›</button></span>}
    </div>
  );
}

export function Empty({ children, testId }: { children: ReactNode; testId?: string }) {
  return <div data-testid={testId} style={{ padding: "18px 20px", fontSize: 14, lineHeight: 1.5, color: "var(--ink-3)" }}>{children}</div>;
}

/** Marks a block whose data arrives with a later phase. Says what it will show; never shows sample figures. */
export function PhaseNote({ phase = 2, children, testId }: { phase?: number; children: ReactNode; testId?: string }) {
  return (
    <div data-testid={testId ?? "phase-note"} style={{ display: "flex", gap: 10, alignItems: "baseline", padding: "12px 14px", borderRadius: 10, border: "1px dashed var(--line-3)", fontSize: 13, lineHeight: 1.5, color: "var(--ink-3)" }}>
      <span className="nv-pill nv-pill-indigo" style={{ padding: "2px 8px", fontSize: 9.5, flex: "none" }}>Phase {phase}</span>
      <span>{children}</span>
    </div>
  );
}

/** Grid table with a mono header row (wide screens) — rows are rendered by the caller. */
export function TableHead({ cols, labels }: { cols: string; labels: string[] }) {
  return (
    <div style={{ display: "grid", gridTemplateColumns: cols, gap: 12, padding: "10px 18px", fontFamily: "var(--mono)", fontSize: 9.5, letterSpacing: "0.1em", textTransform: "uppercase", color: "var(--ink-3)" }}>
      {labels.map((l) => <span key={l}>{l}</span>)}
    </div>
  );
}

export function TableRow({ cols, children, onClick, first, testId }: { cols: string; children: ReactNode; onClick?: () => void; first?: boolean; testId?: string }) {
  return (
    <div
      data-testid={testId}
      onClick={onClick}
      className={onClick ? "ad-hover" : undefined}
      style={{ display: "grid", gridTemplateColumns: cols, gap: 12, padding: "11px 18px", borderTop: `1px solid ${first ? "transparent" : "var(--line)"}`, fontSize: 13, lineHeight: 1.45, alignItems: "baseline", cursor: onClick ? "pointer" : undefined }}
    >
      {children}
    </div>
  );
}

export const mono = (size = 11, color = "var(--ink-3)"): CSSProperties => ({ fontFamily: "var(--mono)", fontSize: size, color });
