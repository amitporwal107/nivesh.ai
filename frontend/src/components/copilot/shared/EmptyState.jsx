import React from "react";
import { Inbox, AlertTriangle, Sparkles, Search, FileText, BarChart3 } from "lucide-react";

const ICONS = {
  inbox: Inbox,
  warning: AlertTriangle,
  ai: Sparkles,
  search: Search,
  doc: FileText,
  chart: BarChart3,
};

/**
 * EmptyState — slot-based illustration + headline + CTA.
 * Doc 06 §6.2 — restricted to six canonical illustrations.
 */
const EmptyState = ({
  icon = "inbox",
  headline,
  supporting,
  primaryCta,
  secondaryHref,
  secondaryLabel,
  testId,
}) => {
  const Icon = ICONS[icon] || Inbox;
  return (
    <div
      data-testid={testId || "empty-state"}
      className="flex flex-col items-center justify-center text-center py-10 px-6 rounded-[var(--cp-radius-lg)] border border-dashed border-[color:var(--cp-border-subtle)] bg-[color:var(--cp-surface-1)]"
    >
      <div className="w-12 h-12 mb-3 rounded-full bg-[color:var(--cp-surface-2)] flex items-center justify-center">
        <Icon className="w-5 h-5 text-slate-500" />
      </div>
      <h4 className="text-sm font-semibold text-[color:var(--cp-text-primary)]">{headline}</h4>
      {supporting && (
        <p className="text-xs text-[color:var(--cp-text-secondary)] mt-1 max-w-sm">{supporting}</p>
      )}
      {primaryCta && (
        <button
          type="button"
          data-testid={`${testId || "empty-state"}-cta`}
          onClick={primaryCta.onClick}
          className="mt-4 inline-flex items-center px-4 py-2 rounded-full text-xs font-medium text-white shadow-sm"
          style={{ background: "var(--cp-accent-brand)" }}
        >
          {primaryCta.label}
        </button>
      )}
      {secondaryHref && (
        <a
          href={secondaryHref}
          className="mt-2 text-[11px] text-[color:var(--cp-accent-brand)] hover:underline"
        >
          {secondaryLabel || "Learn more"}
        </a>
      )}
    </div>
  );
};

export default EmptyState;
