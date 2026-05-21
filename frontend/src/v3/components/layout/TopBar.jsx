import React from "react";
import { Clock, Menu, Search, Plus, Settings as SettingsIcon } from "lucide-react";
import BrandMark from "../BrandMark";
import IconButton from "../IconButton";

/**
 * Mobile top bar — brand + history + menu. Desktop variant accepts a `eyebrow + title`
 * pattern instead of brand mark.
 */
export default function TopBar({ variant = "mobile", title, eyebrow, onMenu, onHistory, onSearch, onCreate, onSettings, actions = [] }) {
  if (variant === "desktop") {
    return (
      <div style={{ display: "flex", alignItems: "flex-end", justifyContent: "space-between", padding: "30px 0 24px 0" }}>
        <div>
          {eyebrow && <div className="v3-eyebrow" style={{ color: "var(--v3-ink-3)", marginBottom: 4 }}>{eyebrow}</div>}
          {title && (
            <h2 style={{ fontFamily: "var(--v3-font-display)", fontWeight: 600, fontSize: 24, letterSpacing: "-0.015em", color: "var(--v3-ink-1)" }}>
              {title}
            </h2>
          )}
        </div>
        <div style={{ display: "flex", gap: 8 }}>
          {actions.length > 0
            ? actions.map((a, i) => <IconButton key={i} {...a} />)
            : (
              <>
                <IconButton icon={Search} label="Search" onClick={onSearch} />
                <IconButton icon={Plus} label="New" onClick={onCreate} />
                <IconButton icon={SettingsIcon} label="Settings" onClick={onSettings} />
              </>
            )}
        </div>
      </div>
    );
  }

  return (
    <div
      style={{
        display: "flex",
        alignItems: "center",
        justifyContent: "space-between",
        padding: "16px var(--v3-mobile-gutter) 14px",
      }}
    >
      <BrandMark withWordmark size={32} />
      <div style={{ display: "flex", gap: 8 }}>
        {actions.length > 0
          ? actions.map((a, i) => <IconButton key={i} {...a} />)
          : (
            <>
              <IconButton icon={Clock} label="History" onClick={onHistory} />
              <IconButton icon={Menu} label="Menu" onClick={onMenu} />
            </>
          )}
      </div>
    </div>
  );
}
