import { useState, type ReactNode } from "react";
import { useChatSessions } from "@/hooks/use-chat";
import { useScreeners } from "@/hooks/use-screeners";
import {
  Btn, EmptyBlock, LoadingBlock, NotConnected, Screen, ScreenHeader, TONE_COLOR, fmtDate, fmtNum, relTime,
  type Tone,
} from "../components/ui";
import { useCopilotShell } from "../lib/shell-context";
import { threadView } from "../lib/views";
import { LoadError } from "./markets/parts";

const THREADS_SHOWN = 6;

/**
 * Saved — the things a user can come back to. Design:
 * design/nivesh-copilot/NVPages.dc.html (page === "saved").
 *
 *   Reports → not connected (the product cannot save a report yet)
 *   Screens → GET /api/screeners (useScreeners)
 *   Threads → GET /api/chat/sessions (useChatSessions); the product has no
 *             pinning, so these are the most recent threads
 */
export default function SavedScreen() {
  return (
    <Screen testId="screen-page-saved">
      <ScreenHeader
        eyebrow="Saved"
        title="Reports, screens and threads"
        sub="A saved screen keeps its rules and a thread keeps its conversation. Neither keeps a data snapshot, so running a screen again uses today’s data."
      />

      <Group title="Reports">
        <NotConnected
          testId="saved-reports-nc"
          title="Saving a report is not connected yet"
          body="The design keeps research and portfolio reports here with the data they were built on, ready to re-run. The product has no store for a saved report."
          needs={[
            "An endpoint to save a Copilot answer as a report, with its data snapshot and the time it was built",
            "A list of the user’s saved reports, and a way to re-run one on today’s data",
          ]}
        />
      </Group>

      <SavedScreens />
      <RecentThreads />
    </Screen>
  );
}

function Group({ title, count, children }: { title: string; count?: number; children: ReactNode }) {
  return (
    <section className="flex flex-col" style={{ gap: 10 }}>
      <span className="cp-eyebrow">{title}{count != null ? ` · ${fmtNum(count)}` : ""}</span>
      {children}
    </section>
  );
}

function CardGrid({ children, testId }: { children: ReactNode; testId: string }) {
  return (
    <div className="grid" style={{ gridTemplateColumns: "repeat(auto-fit,minmax(min(100%,280px),1fr))", gap: 12 }} data-testid={testId}>
      {children}
    </div>
  );
}

/** One saved item: a mono kicker, a serif title, a quiet line and its actions. */
function SavedCard({ kicker, tone, title, meta, detail, actions, testId }: {
  kicker: string;
  tone: Tone;
  title: string;
  meta?: string;
  detail?: string;
  actions: ReactNode;
  testId: string;
}) {
  return (
    <article className="cp-card flex flex-col" style={{ gap: 8, padding: "16px 18px" }} data-testid={testId}>
      <span className="cp-mono-note" style={{ letterSpacing: "0.1em", color: TONE_COLOR[tone] }}>{kicker}</span>
      <span style={{ fontFamily: "var(--display)", fontSize: 20, lineHeight: 1.2, overflowWrap: "anywhere" }} data-testid={`${testId}-title`}>{title}</span>
      {detail && <span style={{ fontFamily: "var(--mono)", fontSize: 11, lineHeight: 1.5, color: "var(--cp-ink-3)", overflowWrap: "anywhere" }}>{detail}</span>}
      {meta && <span style={{ fontSize: 12, color: "var(--cp-ink-3)" }}>{meta}</span>}
      <div className="flex flex-wrap" style={{ gap: "4px 16px", marginTop: "auto" }}>{actions}</div>
    </article>
  );
}

function CardAction({ onClick, children, quiet, testId }: { onClick: () => void; children: ReactNode; quiet?: boolean; testId?: string }) {
  return (
    <button
      type="button"
      onClick={onClick}
      data-testid={testId}
      style={{ padding: 0, border: 0, background: "none", cursor: "pointer", fontSize: 13, fontFamily: "var(--sans)", color: quiet ? "var(--cp-ink-3)" : "var(--cp-ink-2)" }}
    >
      {children}
    </button>
  );
}

function SavedScreens() {
  const { ask, go } = useCopilotShell();
  const q = useScreeners();

  return (
    <Group title="Screens" count={q.data?.length}>
      {q.isPending ? (
        <LoadingBlock label="Loading saved screens" />
      ) : q.isError ? (
        <LoadError title="Saved screens didn’t load" error={q.error} onRetry={() => q.refetch()} />
      ) : q.data.length === 0 ? (
        <EmptyBlock
          title="No saved screens yet"
          body="Build a rule list in the Screener and save it; it will appear here to run again."
          action={<Btn onClick={() => go("tool/screener")}>Open the Screener ›</Btn>}
        />
      ) : (
        <CardGrid testId="saved-screens">
          {q.data.map((s) => {
            const rules = s.conditions.length;
            return (
              <SavedCard
                key={s.screener_id}
                testId="saved-screen"
                kicker={`Screen · ${fmtNum(rules)} ${rules === 1 ? "rule" : "rules"}${s.bucket ? ` · ${s.bucket} cap` : ""}`}
                tone="mint"
                title={s.name}
                detail={s.query}
                meta={s.updated_at ? `Saved ${fmtDate(s.updated_at)}` : undefined}
                actions={
                  <>
                    <CardAction onClick={() => ask(s.query)} testId="saved-screen-run">Run again ›</CardAction>
                    <CardAction onClick={() => go("tool/screener")} quiet>Edit in the Screener ›</CardAction>
                  </>
                }
              />
            );
          })}
        </CardGrid>
      )}
    </Group>
  );
}

function RecentThreads() {
  const { go } = useCopilotShell();
  const q = useChatSessions();
  const [all, setAll] = useState(false);

  return (
    <Group title="Threads · most recent" count={q.data?.length}>
      {q.isPending ? (
        <LoadingBlock label="Loading threads" />
      ) : q.isError ? (
        <LoadError title="Threads didn’t load" error={q.error} onRetry={() => q.refetch()} />
      ) : q.data.length === 0 ? (
        <EmptyBlock
          title="No threads yet"
          body="Ask the Copilot a question and the conversation will be kept here."
          action={<Btn onClick={() => go("")}>Ask the Copilot ›</Btn>}
        />
      ) : (
        <>
          <CardGrid testId="saved-threads">
            {(all ? q.data : q.data.slice(0, THREADS_SHOWN)).map((t) => (
              <SavedCard
                key={t.id}
                testId="saved-thread"
                kicker="Thread"
                tone="indigo"
                title={t.title}
                meta={t.updatedAt ? `Updated ${relTime(t.updatedAt)}` : undefined}
                actions={<CardAction onClick={() => go(threadView(t.id))} testId="saved-thread-open">Continue ›</CardAction>}
              />
            ))}
          </CardGrid>
          {q.data.length > THREADS_SHOWN && (
            <Btn className="self-start" variant="ghost" onClick={() => setAll((v) => !v)} data-testid="saved-threads-toggle">
              {all ? "Show fewer" : `Show all ${fmtNum(q.data.length)}`}
            </Btn>
          )}
        </>
      )}
    </Group>
  );
}
