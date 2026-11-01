/**
 * "Save as a watchlist" — the form that follows a screen's results on the
 * Screener. It only collects the name: the caller does the write with the
 * existing save call for that kind of screen (saved rule screens, or saved
 * strategies), and hands back the pending / error / saved state.
 */
import { useId, useState, type FormEvent } from "react";
import { Btn } from "../../components/ui";
import { useCopilotShell } from "../../lib/shell-context";
import { LoadError } from "../markets/parts";

const WATCHLIST_VIEW = "page/watchlist?wl=screens";   // the Watchlist page opens on its Saved screens list

/** A quiet link to the Watchlist screen. */
export function OpenWatchlist({ testId, children = "Open the Watchlist ›" }: { testId?: string; children?: string }) {
  const { go } = useCopilotShell();
  return (
    <button
      type="button"
      data-testid={testId}
      onClick={() => go(WATCHLIST_VIEW)}
      style={{ padding: 0, border: 0, background: "none", cursor: "pointer", fontSize: 13, fontFamily: "var(--sans)", color: "var(--mint)" }}
    >
      {children}
    </button>
  );
}

export function SaveAsWatchlist({ idPrefix, defaultName = "", maxLength = 80, prompt = "Keep this screen as a watchlist. It will list whatever passes it each day.", buttonLabel = "Save as a watchlist", pending, error, savedName, onSave }: {
  /** Prefix for the test ids: `<prefix>`, `-name`, `-save`, `-error`, `-done`, `-open`. */
  idPrefix: string;
  defaultName?: string;
  /** The longest name the save call accepts. */
  maxLength?: number;
  /** The sentence above the name field. */
  prompt?: string;
  /** The save button's words. */
  buttonLabel?: string;
  pending: boolean;
  error: unknown;
  /** The name it was saved under; set once the save has succeeded. */
  savedName: string | null;
  onSave: (name: string) => void;
}) {
  const inputId = useId();
  const [name, setName] = useState(defaultName);
  const trimmed = name.trim();

  const submit = (e: FormEvent) => {
    e.preventDefault();
    if (!trimmed || pending) return;
    onSave(trimmed);
  };

  return (
    <div data-testid={idPrefix} className="cp-card flex min-w-0 flex-col" style={{ gap: 10, padding: "12px 14px" }}>
      {savedName ? (
        <div data-testid={`${idPrefix}-done`} role="status" className="flex flex-wrap items-center" style={{ gap: "6px 14px", fontSize: 13, lineHeight: 1.5, color: "var(--cp-ink-2)" }}>
          <span style={{ flex: "1 1 240px", minWidth: 0, overflowWrap: "anywhere" }}>
            Saved as <span style={{ color: "var(--cp-ink)", fontWeight: 500 }}>{savedName}</span>. It is on your Watchlist under “Your screens as watchlists”, and lists whatever passes it each day.
          </span>
          <OpenWatchlist testId={`${idPrefix}-open`} />
        </div>
      ) : (
        <>
          <form onSubmit={submit} className="flex flex-wrap items-center" style={{ gap: 8 }}>
            <label htmlFor={inputId} style={{ flex: "1 1 100%", fontSize: 13, color: "var(--cp-ink-2)" }}>
              {prompt}
            </label>
            <input
              id={inputId}
              data-testid={`${idPrefix}-name`}
              value={name}
              onChange={(e) => setName(e.target.value)}
              placeholder="Name this watchlist…"
              maxLength={maxLength}
              autoComplete="off"
              style={{ flex: "1 1 180px", minWidth: 0, padding: "8px 10px", borderRadius: 10, border: "1px solid var(--line-2)", background: "var(--bg-1)", color: "var(--cp-ink)", fontFamily: "var(--sans)", fontSize: 13 }}
            />
            <Btn type="submit" disabled={!trimmed || pending} data-testid={`${idPrefix}-save`}>
              {pending ? "Saving…" : buttonLabel}
            </Btn>
          </form>
          {error != null && (
            <div data-testid={`${idPrefix}-error`}>
              <LoadError title="The watchlist wasn’t saved" error={error} />
            </div>
          )}
        </>
      )}
    </div>
  );
}
