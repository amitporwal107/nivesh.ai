/**
 * A small, dependency-free dropdown-button primitive shared by the workspace components (Toolbar's timeframe/
 * chart-type/More menus, DrawingRail's tool-group flyouts). Mirrors the existing account-menu pattern
 * (`src/components/layout/Topbar.tsx`: local open state, outside-click + Escape to close, `role="menu"` /
 * `role="menuitem"`) rather than adding a menu library — no new npm dependency for this.
 */
import { useEffect, useId, useRef, useState } from "react";

export interface MenuItem {
  id: string;
  label: string;
  onSelect?: () => void;
  selected?: boolean;
  disabled?: boolean;
  /** Required when `disabled` is true (§38.9 a11y: "disabled items say why") — shown as the item's title/tooltip. */
  disabledReason?: string;
  testId?: string;
}

export interface MenuButtonProps {
  /** The trigger button's visible content. */
  label: React.ReactNode;
  /** Accessible name for the trigger, when `label` alone is not enough (an icon-only button, for instance). */
  ariaLabel?: string;
  title?: string;
  items: MenuItem[];
  disabled?: boolean;
  disabledReason?: string;
  testId?: string;
  className?: string;
  style?: React.CSSProperties;
  /** Renders the trigger only (no built-in chevron/padding) — DrawingRail uses this for its icon-square tools. */
  bare?: boolean;
}

export function MenuButton({ label, ariaLabel, title, items, disabled, disabledReason, testId, className, style, bare }: MenuButtonProps) {
  const [open, setOpen] = useState(false);
  const ref = useRef<HTMLDivElement>(null);
  const menuId = useId();

  useEffect(() => {
    if (!open) return;
    const onOutside = (e: MouseEvent) => { if (ref.current && !ref.current.contains(e.target as Node)) setOpen(false); };
    const onKey = (e: KeyboardEvent) => { if (e.key === "Escape") setOpen(false); };
    document.addEventListener("mousedown", onOutside);
    document.addEventListener("keydown", onKey);
    return () => { document.removeEventListener("mousedown", onOutside); document.removeEventListener("keydown", onKey); };
  }, [open]);

  const effectiveTitle = disabled ? disabledReason : title;

  return (
    <div ref={ref} className={className} style={{ position: "relative", display: "inline-block", ...style }}>
      <button
        type="button"
        data-testid={testId}
        aria-label={ariaLabel}
        aria-haspopup="menu"
        aria-expanded={open}
        aria-controls={open ? menuId : undefined}
        aria-disabled={disabled || undefined}
        title={effectiveTitle}
        disabled={disabled}
        onClick={() => !disabled && setOpen((v) => !v)}
        className={bare ? undefined : "nv-btn"}
        style={bare ? { background: "none", border: 0, padding: 0, cursor: disabled ? "not-allowed" : "pointer", opacity: disabled ? 0.45 : 1 } : { opacity: disabled ? 0.55 : 1, cursor: disabled ? "not-allowed" : "pointer" }}
      >
        {label}
      </button>
      {open && !disabled && (
        <div
          id={menuId}
          role="menu"
          aria-label={typeof label === "string" ? `${label} menu` : "Menu"}
          style={{
            position: "absolute", top: "calc(100% + 6px)", left: 0, minWidth: 180, zIndex: 40,
            background: "var(--bg-1)", border: "1px solid var(--c-line-strong)", borderRadius: 10,
            boxShadow: "var(--shadow-pop)", padding: 4, display: "grid", gap: 1,
          }}
        >
          {items.map((it) => (
            <button
              key={it.id}
              type="button"
              role="menuitemradio"
              aria-checked={!!it.selected}
              aria-label={it.label}
              data-testid={it.testId}
              disabled={it.disabled}
              title={it.disabled ? `${it.label} — ${it.disabledReason}` : it.label}
              aria-disabled={it.disabled || undefined}
              onClick={() => { if (it.disabled) return; it.onSelect?.(); setOpen(false); }}
              style={{
                display: "flex", alignItems: "center", justifyContent: "space-between", gap: 10,
                width: "100%", textAlign: "left", padding: "7px 10px", borderRadius: 7, border: 0,
                fontSize: 12.5, fontFamily: "var(--sans)",
                background: it.selected ? "var(--mint-soft)" : "transparent",
                color: it.disabled ? "var(--c-ink-4)" : it.selected ? "var(--mint)" : "var(--c-ink-2)",
                cursor: it.disabled ? "not-allowed" : "pointer",
              }}
            >
              <span>{it.label}</span>
              {it.disabled && <span className="nv-mono" style={{ fontSize: 9, color: "var(--c-ink-4)" }}>soon</span>}
            </button>
          ))}
        </div>
      )}
    </div>
  );
}

export default MenuButton;
