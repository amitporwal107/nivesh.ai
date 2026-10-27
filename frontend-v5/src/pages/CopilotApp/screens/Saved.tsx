import { useState, type ReactNode } from "react";
import { Link } from "react-router-dom";
import { useChatSessions, useDeleteChatSession } from "@/hooks/use-chat";
import { useScreeners } from "@/hooks/use-screeners";
import {
  Btn, EmptyBlock, LoadingBlock, NotConnected, Screen, ScreenHeader, TONE_COLOR, fmtDate, fmtNum, relTime,
  type Tone,
} from "../components/ui";
import { useCopilotShell } from "../lib/shell-context";
import { threadView } from "../lib/views";
import { useThematicPrefs } from "./markets/hooks";
import { LoadError } from "./markets/parts";
import { NothingToExport, downloadHoldings, useToggleStarredQuestion, type ExportFormat } from "./workspace/saved-data";
import { useSavedStrategies } from "./workspace/strategies";

const THREADS_SHOWN = 6;
const WATCHLIST_VIEW = "page/watchlist?wl=screens";   // the Watchlist page opens on its Saved screens list

/**
 * Saved — the things a user can come back to. Design:
 * design/nivesh-copilot/NVPages.dc.html (page === "saved").
 *
 *   Reports   → the holdings file: GET /api/portfolio/holdings/export (CSV or
 *               Excel). Keeping a Copilot answer as a report has no store, and
 *               the block under it says so.
 *   Screens   → rule screens: GET /api/screeners (useScreeners)
 *               ready-made screens kept from the Screener:
 *               GET /api/strategy-builder/strategies (workspace/strategies.ts)
 *   Questions → starred research questions: GET /api/thematic/prefs
 *               (useThematicPrefs), un-starred with POST /api/thematic/favorites/toggle
 *   Threads   → GET /api/chat/sessions (useChatSessions), deleted with
 *               DELETE /api/chat/sessions/{id} (useDeleteChatSession). The
 *               product has no pinning, so these are the most recent threads.
 */
export default function SavedScreen() {
  return (
    <Screen testId="screen-page-saved">
      <ScreenHeader
        eyebrow="Saved"
        title="Reports, screens, questions and threads"
        sub="A saved screen keeps its rules, a starred question keeps its wording and a thread keeps its conversation. None of them keeps a data snapshot, so running one again uses today’s data."
      />

      <Group title="Reports">
        <HoldingsExport />
        <NotConnected
          testId="saved-reports-nc"
          title="Saving a report is not connected yet"
          body="A Copilot answer cannot be kept as a report with the data it was built on, and a thread cannot be pinned or renamed: the product has no store for either. What can be kept today is on this page."
          needs={[
            "An endpoint to save a Copilot answer as a report with its data snapshot and build time, and one to list a user’s reports (none exists; POST /api/copilot/feedback only records a thumbs up or down)",
            "Pin and rename on chat sessions: routes/chat.py has list, create and delete only, and the title is taken from the first message",
            "Saved what-if scenarios: GET /api/scenarios/saved exists but no screen saves one, and the client contract (saved_scenarios, saved_at) does not match what the route returns (saved, created_at)",
            "Saved chart layouts (GET /api/research/chart-layouts) belong to the original Research charts, which this app does not mount",
          ]}
        />
      </Group>

      <SavedScreens />
      <StarredQuestions />
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
    <article className="cp-card flex min-w-0 flex-col" style={{ gap: 8, padding: "16px 18px" }} data-testid={testId}>
      <span className="cp-mono-note" style={{ letterSpacing: "0.1em", color: TONE_COLOR[tone] }}>{kicker}</span>
      <span style={{ fontFamily: "var(--display)", fontSize: 20, lineHeight: 1.2, overflowWrap: "anywhere" }} data-testid={`${testId}-title`}>{title}</span>
      {detail && <span style={{ fontFamily: "var(--mono)", fontSize: 11, lineHeight: 1.5, color: "var(--cp-ink-3)", overflowWrap: "anywhere" }}>{detail}</span>}
      {meta && <span style={{ fontSize: 12, color: "var(--cp-ink-3)" }}>{meta}</span>}
      <div className="flex flex-wrap items-center" style={{ gap: "4px 16px", marginTop: "auto" }}>{actions}</div>
    </article>
  );
}

function CardAction({ onClick, children, quiet, danger, disabled, testId }: { onClick: () => void; children: ReactNode; quiet?: boolean; danger?: boolean; disabled?: boolean; testId?: string }) {
  return (
    <button
      type="button"
      onClick={onClick}
      disabled={disabled}
      data-testid={testId}
      style={{
        padding: 0, border: 0, background: "none", cursor: disabled ? "not-allowed" : "pointer", fontSize: 13, fontFamily: "var(--sans)",
        opacity: disabled ? 0.5 : 1, color: danger ? "var(--cp-danger)" : quiet ? "var(--cp-ink-3)" : "var(--cp-ink-2)",
      }}
    >
      {children}
    </button>
  );
}

// ── reports ──────────────────────────────────────────────────────────────

type ExportState =
  | { status: "idle" }
  | { status: "working"; format: ExportFormat }
  | { status: "done"; filename: string }
  | { status: "error"; error: unknown };

const FORMATS: Array<{ format: ExportFormat; label: string }> = [
  { format: "csv", label: "Download CSV" },
  { format: "xlsx", label: "Download Excel" },
];

/** The one report the product can already hand over: the holdings on file, as a spreadsheet. */
function HoldingsExport() {
  const [state, setState] = useState<ExportState>({ status: "idle" });
  const working = state.status === "working";

  const download = (format: ExportFormat) => {
    if (working) return;
    setState({ status: "working", format });
    downloadHoldings(format).then(
      (filename) => setState({ status: "done", filename }),
      (error: unknown) => setState({ status: "error", error }),
    );
  };

  return (
    <article className="cp-card flex min-w-0 flex-col" style={{ gap: 10, padding: "16px 18px" }} data-testid="saved-export">
      <span className="cp-mono-note" style={{ letterSpacing: "0.1em", color: TONE_COLOR.amber }}>Report · spreadsheet</span>
      <span style={{ fontFamily: "var(--display)", fontSize: 20, lineHeight: 1.2 }}>Your holdings as a file</span>
      <span style={{ fontSize: 13, lineHeight: 1.55, color: "var(--cp-ink-2)", maxWidth: 600 }}>
        Every holding on file, one row each: units, average cost, current price and value, amount invested, gain or loss, and where the holding came from. Built from today’s data each time you download it.
      </span>
      <div className="flex flex-wrap items-center" style={{ gap: 8 }}>
        {FORMATS.map((f) => (
          <Btn key={f.format} disabled={working} onClick={() => download(f.format)} data-testid={`saved-export-${f.format}`}>
            {state.status === "working" && state.format === f.format ? "Preparing…" : f.label}
          </Btn>
        ))}
      </div>
      {state.status === "done" && (
        <span role="status" data-testid="saved-export-done" style={{ fontSize: 13, color: "var(--cp-ink-2)", overflowWrap: "anywhere" }}>
          Sent <span style={{ color: "var(--cp-ink)" }}>{state.filename}</span> to your downloads.
        </span>
      )}
      {state.status === "error" && (
        <div data-testid="saved-export-error">
          <LoadError title="The file wasn’t downloaded" error={state.error instanceof NothingToExport ? state.error.message : state.error} />
        </div>
      )}
    </article>
  );
}

// ── screens ──────────────────────────────────────────────────────────────

function SavedScreens() {
  const { ask, go } = useCopilotShell();
  const rules = useScreeners();
  const strategies = useSavedStrategies();
  const count = rules.isSuccess && strategies.isSuccess ? rules.data.length + strategies.data.length : undefined;
  const nothing = rules.isSuccess && strategies.isSuccess && rules.data.length === 0 && strategies.data.length === 0;

  return (
    <Group title="Screens" count={count}>
      {nothing ? (
        <div data-testid="saved-screens-empty">
          <EmptyBlock
            title="No saved screens yet"
            body="Run a screen in the Screener and save it; it will appear here, and on your Watchlist as the stocks that pass it each day."
            action={<Btn onClick={() => go("tool/screener")}>Open the Screener ›</Btn>}
          />
        </div>
      ) : (
        <>
          {rules.isPending ? (
            <LoadingBlock label="Loading saved screens" />
          ) : rules.isError ? (
            <LoadError title="Saved screens didn’t load" error={rules.error} onRetry={() => rules.refetch()} />
          ) : rules.data.length > 0 ? (
            <CardGrid testId="saved-screens">
              {rules.data.map((s) => {
                const n = s.conditions.length;
                return (
                  <SavedCard
                    key={s.screener_id}
                    testId="saved-screen"
                    kicker={`Rule screen · ${fmtNum(n)} ${n === 1 ? "rule" : "rules"}${s.bucket ? ` · ${s.bucket} cap` : ""}`}
                    tone="mint"
                    title={s.name}
                    detail={s.query}
                    meta={s.updated_at ? `Saved ${fmtDate(s.updated_at)}` : undefined}
                    actions={
                      <>
                        <CardAction onClick={() => ask(s.query)} testId="saved-screen-run">Run again ›</CardAction>
                        <CardAction onClick={() => go(WATCHLIST_VIEW)} testId="saved-screen-watchlist" quiet>Today’s stocks ›</CardAction>
                        <CardAction onClick={() => go("tool/screener")} quiet>Edit in the Screener ›</CardAction>
                      </>
                    }
                  />
                );
              })}
            </CardGrid>
          ) : null}

          {strategies.isPending ? (
            <LoadingBlock label="Loading saved ready-made screens" rows={2} />
          ) : strategies.isError ? (
            <div data-testid="saved-strategies-error">
              <LoadError title="Saved ready-made screens didn’t load" error={strategies.error} onRetry={() => strategies.refetch()} />
            </div>
          ) : strategies.data.length > 0 ? (
            <CardGrid testId="saved-strategies">
              {strategies.data.map((s) => {
                const saved = s.updatedAt ?? s.createdAt;
                const funds = s.assetClass === "MF";
                return (
                  <SavedCard
                    key={s.id}
                    testId="saved-strategy"
                    kicker={`Strategy screen · ${funds ? "funds" : "stocks"}`}
                    tone="mint"
                    title={s.name}
                    detail={s.description ?? undefined}
                    meta={saved ? `Saved ${fmtDate(saved)}` : undefined}
                    actions={
                      <>
                        {!funds && <CardAction onClick={() => go(WATCHLIST_VIEW)} testId="saved-strategy-watchlist">Today’s stocks ›</CardAction>}
                        <Link to="/strategy-builder" className="cp-link" style={{ fontSize: 13 }}>Backtest in the strategy builder ›</Link>
                      </>
                    }
                  />
                );
              })}
            </CardGrid>
          ) : null}
        </>
      )}
    </Group>
  );
}

// ── starred research questions ───────────────────────────────────────────

function StarredQuestions() {
  const { ask, go } = useCopilotShell();
  const q = useThematicPrefs();
  const toggle = useToggleStarredQuestion();

  return (
    <Group title="Starred research questions" count={q.data?.favorites.length}>
      {q.isPending ? (
        <LoadingBlock label="Loading starred questions" rows={2} />
      ) : q.isError ? (
        <LoadError title="Starred questions didn’t load" error={q.error} onRetry={() => q.refetch()} />
      ) : q.data.favorites.length === 0 ? (
        <div data-testid="saved-questions-empty">
          <EmptyBlock
            title="No starred questions yet"
            body="Star a question on the Research screen and it is kept here, ready to ask again."
            action={<Btn onClick={() => go("tool/research")}>Open Research ›</Btn>}
          />
        </div>
      ) : (
        <CardGrid testId="saved-questions">
          {q.data.favorites.map((question) => (
            <SavedCard
              key={question}
              testId="saved-question"
              kicker="Research question"
              tone="amber"
              title={question}
              actions={
                <>
                  <CardAction onClick={() => ask(question)} testId="saved-question-ask">Ask again ›</CardAction>
                  <CardAction onClick={() => toggle.mutate(question)} disabled={toggle.isPending} testId="saved-question-unstar" quiet>Remove the star</CardAction>
                </>
              }
            />
          ))}
        </CardGrid>
      )}
      {toggle.isError && (
        <div data-testid="saved-question-error">
          <LoadError title="The star wasn’t removed" error={toggle.error} />
        </div>
      )}
    </Group>
  );
}

// ── threads ──────────────────────────────────────────────────────────────

function RecentThreads() {
  const { go } = useCopilotShell();
  const q = useChatSessions();
  const remove = useDeleteChatSession();
  const [all, setAll] = useState(false);
  const [confirming, setConfirming] = useState<string | null>(null);

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
                actions={
                  <>
                    <CardAction onClick={() => go(threadView(t.id))} testId="saved-thread-open">Continue ›</CardAction>
                    {confirming === t.id ? (
                      <>
                        <CardAction onClick={() => { setConfirming(null); remove.mutate(t.id); }} disabled={remove.isPending} testId="saved-thread-delete-confirm" danger>Delete it</CardAction>
                        <CardAction onClick={() => setConfirming(null)} quiet>Keep</CardAction>
                      </>
                    ) : (
                      <CardAction onClick={() => setConfirming(t.id)} disabled={remove.isPending} testId="saved-thread-delete" quiet>Delete</CardAction>
                    )}
                  </>
                }
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
      {remove.isError && (
        <div data-testid="saved-thread-delete-error">
          <LoadError title="The thread wasn’t deleted" error={remove.error} />
        </div>
      )}
    </Group>
  );
}
