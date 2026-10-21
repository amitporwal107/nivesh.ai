/**
 * ThreadRow — one thread in the rail: open, bookmark, tag, clear.
 * Actions sit beside the title (not inside the open button) and show on hover
 * or focus; on touch screens they are always visible. Clearing asks first.
 */
import { useState } from "react";
import type { ChatSession } from "@/services/adapters/chat.adapter";
import { relTime } from "../components/ui";

export function ThreadRow({ thread, active, busy, onOpen, onBookmark, onTags, onClear }: {
  thread: ChatSession;
  active: boolean;
  busy: boolean;
  onOpen: () => void;
  onBookmark: () => void;
  onTags: (tags: string[]) => void;
  onClear: () => void;
}) {
  const [mode, setMode] = useState<"idle" | "tagging" | "confirm">("idle");
  const [draft, setDraft] = useState("");

  const addTag = () => {
    const t = draft.trim().toLowerCase();
    setDraft("");
    if (t && !thread.tags.includes(t)) onTags([...thread.tags, t]);
  };

  return (
    <div className="cp-thread" data-testid="thread-row-wrap" data-active={active ? "true" : undefined} data-bookmarked={thread.bookmarked ? "true" : undefined}>
      <div className="cp-thread-main">
        <button type="button" data-testid="thread-row" className="cp-rail-row cp-thread-open" aria-current={active ? "page" : undefined} onClick={onOpen} title={thread.title}>
          <span style={{ whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis", minWidth: 0 }}>{thread.title}</span>
          <span className="cp-thread-time">{relTime(thread.updatedAt)}</span>
        </button>
        <span className="cp-thread-actions">
          <button type="button" data-testid="thread-tag" className="cp-thread-act" aria-label={`Tag “${thread.title}”`} title="Tags" onClick={() => setMode(mode === "tagging" ? "idle" : "tagging")}>#</button>
          <button type="button" data-testid="thread-clear" className="cp-thread-act" aria-label={`Clear “${thread.title}”`} title="Clear thread" onClick={() => setMode("confirm")}>✕</button>
        </span>
        <button
          type="button"
          data-testid="thread-bookmark"
          className="cp-thread-act cp-thread-star"
          aria-pressed={thread.bookmarked}
          aria-label={thread.bookmarked ? `Remove bookmark from “${thread.title}”` : `Bookmark “${thread.title}”`}
          title={thread.bookmarked ? "Remove bookmark" : "Bookmark"}
          disabled={busy}
          onClick={onBookmark}
        >{thread.bookmarked ? "★" : "☆"}</button>
      </div>

      {thread.tags.length > 0 && (
        <div className="cp-thread-tags">
          {thread.tags.map((t) => (
            <span key={t} className="cp-tag" data-testid="thread-tag-chip">
              {t}
              <button type="button" aria-label={`Remove tag ${t}`} disabled={busy} onClick={() => onTags(thread.tags.filter((x) => x !== t))}>×</button>
            </span>
          ))}
        </div>
      )}

      {mode === "tagging" && (
        <form className="cp-thread-pop" onSubmit={(e) => { e.preventDefault(); addTag(); }}>
          <input
            autoFocus
            data-testid="thread-tag-input"
            value={draft}
            maxLength={24}
            placeholder="Add a tag, press Enter"
            aria-label="New tag"
            onChange={(e) => setDraft(e.target.value)}
            onKeyDown={(e) => { if (e.key === "Escape") { setDraft(""); setMode("idle"); } }}
          />
          <button type="button" className="cp-thread-act" onClick={() => { setDraft(""); setMode("idle"); }}>Done</button>
        </form>
      )}

      {mode === "confirm" && (
        <div className="cp-thread-pop" role="alertdialog" aria-label="Confirm clear">
          <span>Clear this thread?</span>
          <button type="button" data-testid="thread-clear-confirm" className="cp-thread-act" data-danger="true" disabled={busy} onClick={() => { setMode("idle"); onClear(); }}>Clear</button>
          <button type="button" className="cp-thread-act" onClick={() => setMode("idle")}>Keep</button>
        </div>
      )}
    </div>
  );
}
