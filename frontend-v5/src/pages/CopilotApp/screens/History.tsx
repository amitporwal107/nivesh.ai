import { useState } from "react";
import { useChatSessions, useDeleteChatSession, useUpdateChatSession } from "@/hooks/use-chat";
import { EmptyBlock, LoadingBlock, Screen, ScreenHeader } from "../components/ui";
import { useCopilotShell } from "../lib/shell-context";
import { isRecentThread, threadView } from "../lib/views";
import { ThreadRow } from "../shell/ThreadRow";

/**
 * Past conversations — threads not touched in the last 2 days (the rail shows
 * the recent ones). Same bookmark / tag / clear actions as the rail.
 * Data: GET /api/chat/sessions, PATCH and DELETE /api/chat/sessions/{id}.
 */
export default function HistoryScreen() {
  const { go } = useCopilotShell();
  const sessions = useChatSessions();
  const update = useUpdateChatSession();
  const remove = useDeleteChatSession();
  const [q, setQ] = useState("");

  const older = (sessions.data ?? []).filter((t) => !isRecentThread(t.updatedAt));
  const needle = q.trim().toLowerCase();
  const shown = needle ? older.filter((t) => t.title.toLowerCase().includes(needle) || t.tags.some((g) => g.includes(needle.replace(/^#/, "")))) : older;

  return (
    <Screen testId="screen-page-history">
      <ScreenHeader eyebrow="History" title="Past conversations" />
      {sessions.isPending && <LoadingBlock />}
      {sessions.isError && <EmptyBlock title="Threads didn’t load" />}
      {!sessions.isPending && !sessions.isError && older.length === 0 && <EmptyBlock title="No older conversations" />}
      {older.length > 0 && (
        <>
          <input
            data-testid="history-search"
            value={q}
            onChange={(e) => setQ(e.target.value)}
            placeholder="Search by title or #tag"
            aria-label="Search past conversations"
            style={{ width: "100%", maxWidth: 420, margin: "0 0 12px", padding: "8px 12px", borderRadius: 10, border: "1px solid var(--line-2)", background: "transparent", color: "var(--cp-ink)", fontSize: 13 }}
          />
          <div className="flex flex-col" style={{ gap: 2, maxWidth: 640 }}>
            {shown.length === 0 && <span style={{ fontSize: 13, color: "var(--cp-ink-4)" }}>No threads match.</span>}
            {shown.map((t) => (
              <ThreadRow
                key={t.id}
                thread={t}
                active={false}
                busy={update.isPending || remove.isPending}
                onOpen={() => go(threadView(t.id))}
                onBookmark={() => update.mutate({ id: t.id, bookmarked: !t.bookmarked })}
                onTags={(tags) => update.mutate({ id: t.id, tags })}
                onClear={() => remove.mutate(t.id)}
              />
            ))}
          </div>
        </>
      )}
    </Screen>
  );
}
