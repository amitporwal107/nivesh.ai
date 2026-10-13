/**
 * Advisor home — the client book at a glance, who needs attention, and the roster.
 * Design: frontend-v5/design/nivesh-copilot/NVAdvisor.dc.html.
 *
 * Data:
 *   firm, headline, tiles, queue, roster   GET /api/mfd/profiles               (useAdvisorBook)
 *   SIP tile                               GET /api/advisor/sip-board/summary  (useSipBoardSummary)
 * Health, top issue and the "needs action" test are the same derivations the
 * current advisor workspace uses (pages/AdvisorDashboard/derive), so the two
 * pages agree on every number.
 *
 * "Open in Copilot" switches to the client the way the current app does
 * (useActivateProfile → impersonation store), then goes to the Copilot home.
 * Model portfolios and report drafts have no backend and say so.
 */
import { useMemo, useState } from "react";
import { Link } from "react-router-dom";
import { useAdvisorBook, useSipBoardSummary } from "@/hooks/use-advisor";
import { useActivateProfile, useDeactivateProfile } from "@/hooks/use-mfd";
import {
  decorateProfile, fmtDaysSince, healthTone,
  type AdvisorProfile, type Tone as BookTone,
} from "@/pages/AdvisorDashboard/derive";
import { MfdWorkspaceC } from "@/services/contracts/advisor.contract";
import { useImpersonationStore } from "@/stores/impersonation.store";
import { useToastStore } from "@/stores/toast.store";
import {
  AskChips, Btn, DataTable, EmptyBlock, Eyebrow, Footnote, LoadingBlock, NotConnected, Pill,
  Screen, ScreenHeader, Section, Tiles, TONE_COLOR, fmtINR, fmtNum,
  type Column, type TileItem, type Tone,
} from "../components/ui";
import { useCopilotShell } from "../lib/shell-context";
import { LoadFailed, isForbidden } from "./internal/shared";

const QUEUE_PREVIEW = 5;
const ROSTER_PREVIEW = 10;

/** The advisor workspace's tone names → this shell's. */
const BOOK_TONE: Record<BookTone, Tone> = { neg: "danger", warm: "amber", pos: "mint", accent: "indigo", neutral: "ink" };

const BUCKET_TONE: Record<string, Tone> = { high: "danger", medium: "amber" };

/** A finite number, or null. The SIP summary comes through an adapter that does not validate its response. */
function num(v: unknown): number | null {
  return typeof v === "number" && Number.isFinite(v) ? v : null;
}

/** The reason a client is in the queue: the priority engine's first reason, else the derived top issue. */
function issueOf(p: AdvisorProfile): string {
  return p.priority?.reasons?.[0] ?? p._issue?.label ?? "";
}

type OpenClient = (p: AdvisorProfile) => void;

// ── states that are not the book ─────────────────────────────────────────

function NotAnAdvisor() {
  const { go } = useCopilotShell();
  return (
    <div data-testid="advisor-not-advisor" className="flex flex-col" style={{ gap: 22 }}>
      <ScreenHeader eyebrow="Advisor" title="This screen is for advisor accounts" />
      <EmptyBlock
        title="Your account manages one portfolio"
        body="The advisor home shows a book of clients — who needs attention, their assets and their SIPs. This account is set up for a single investor, so there is no client book to show. If you advise clients, you can switch the account to advisor mode from the advisor workspace."
        action={
          <span className="flex flex-wrap items-center" style={{ gap: "8px 16px" }}>
            <Btn onClick={() => go("")}>Back to the Copilot</Btn>
            <Link to="/advisor" className="cp-link" style={{ fontSize: 13 }}>Open the advisor workspace ›</Link>
          </span>
        }
      />
    </div>
  );
}

function ViewingClient({ onBack, returning }: { onBack: () => void; returning: boolean }) {
  const { go } = useCopilotShell();
  const name = useImpersonationStore((s) => s.name);
  return (
    <div data-testid="advisor-viewing-client" className="flex flex-col" style={{ gap: 22 }}>
      <ScreenHeader
        eyebrow="Advisor"
        pills={<Pill tone="indigo">Viewing a client</Pill>}
        title={<>You are viewing <em data-testid="advisor-viewing-name">{name || "a client"}</em>.</>}
        sub="While a client is open, every screen and every answer is about that client. Go back to your book to see all your clients again."
      />
      <div className="flex flex-wrap" style={{ gap: 8 }}>
        <Btn data-testid="advisor-back-to-book" variant="primary" disabled={returning} onClick={onBack}>
          {returning ? "Returning…" : "Back to your book"}
        </Btn>
        <Btn onClick={() => go("")}>Stay with {name || "this client"}</Btn>
      </div>
    </div>
  );
}

// ── the book ─────────────────────────────────────────────────────────────

function QueueRow({ p, onOpen, openingId }: { p: AdvisorProfile; onOpen: OpenClient; openingId: string | null }) {
  const { mobile } = useCopilotShell();
  const tone = BUCKET_TONE[p.priority?.bucket ?? ""] ?? "ink";
  const issue = issueOf(p);
  return (
    <div data-testid="advisor-queue-row" className="cp-card flex flex-wrap items-center" style={{ gap: "8px 16px", padding: "14px 18px" }}>
      <span aria-hidden style={{ width: 3, alignSelf: "stretch", borderRadius: 2, background: tone === "ink" ? "var(--line-3)" : TONE_COLOR[tone] }} />
      <div className="flex flex-col min-w-0" style={{ flex: "1 1 220px", gap: 3 }}>
        <span data-testid="advisor-queue-name" style={{ fontSize: 15, fontWeight: 500, overflowWrap: "anywhere" }}>{p.name}</span>
        {issue && (
          <span data-testid="advisor-queue-issue" style={{ fontFamily: "var(--mono)", fontSize: 10, letterSpacing: "0.08em", textTransform: "uppercase", color: "var(--cp-ink-3)", overflowWrap: "anywhere" }}>{issue}</span>
        )}
      </div>
      <span data-testid="advisor-queue-aum" className="cp-num" style={{ fontFamily: "var(--display)", fontSize: 20 }}>{fmtINR(p._aum, { compact: true })}</span>
      <Btn
        data-testid="advisor-open-client"
        aria-label={`Open in Copilot: ${p.name}`}
        disabled={openingId != null}
        onClick={() => onOpen(p)}
        style={mobile ? { flex: "1 1 100%" } : undefined}
      >
        {openingId === p.profile_id ? "Opening…" : "Open in Copilot"}
      </Btn>
    </div>
  );
}

const ROSTER_COLUMNS: Column<AdvisorProfile>[] = [
  {
    key: "client", header: "Client", width: "minmax(0,1.3fr)",
    render: (p) => <span data-testid="advisor-client-row" data-profile-id={p.profile_id} style={{ fontWeight: 500, color: "var(--cp-ink)" }}>{p.name}</span>,
  },
  {
    key: "aum", header: "AUM", width: "90px", align: "right", num: true,
    render: (p) => <span data-testid="advisor-client-aum">{fmtINR(p._aum, { compact: true })}</span>,
  },
  {
    key: "health", header: "Health", width: "70px", align: "right", num: true,
    render: (p) => (
      <span data-testid="advisor-client-health" style={{ color: p._health == null ? "var(--cp-ink-3)" : TONE_COLOR[BOOK_TONE[healthTone(p._health)]] }}>
        {p._health ?? "—"}
      </span>
    ),
  },
  {
    key: "issue", header: "Top issue", width: "minmax(0,1.8fr)",
    render: (p) => <span data-testid="advisor-client-issue" title={issueOf(p) || undefined}>{p._issue?.label ?? "—"}</span>,
  },
  {
    key: "reviewed", header: "Reviewed", width: "90px", align: "right",
    render: (p) => (
      <span data-testid="advisor-client-reviewed" title={p.last_reviewed_at ?? undefined} style={{ fontFamily: "var(--mono)", fontSize: 11, textTransform: "uppercase", color: "var(--cp-ink-3)" }}>
        {(p.last_reviewed_at && fmtDaysSince(p.last_reviewed_at)) || "Not yet"}
      </span>
    ),
  },
];

function Book({ onOpen, openingId }: { onOpen: OpenClient; openingId: string | null }) {
  const book = useAdvisorBook();
  const sips = useSipBoardSummary();
  const [allQueue, setAllQueue] = useState(false);
  const [allRoster, setAllRoster] = useState(false);

  const clients = useMemo<AdvisorProfile[]>(
    () => (book.data?.profiles ?? []).filter((p) => p.type !== "SELF").map(decorateProfile),
    [book.data],
  );
  /** Clients whose derived action is anything but "All good", highest priority first. */
  const queue = useMemo(
    () => clients
      .filter((p) => p._action?.label !== "All good")
      .sort((a, b) => (b.priority?.score ?? 0) - (a.priority?.score ?? 0)),
    [clients],
  );
  /** Weakest health first; clients not scored yet go last. */
  const roster = useMemo(
    () => [...clients].sort((a, b) => (a._health ?? 101) - (b._health ?? 101)),
    [clients],
  );

  if (book.isPending) {
    return (
      <>
        <ScreenHeader eyebrow="Advisor" pills={<Pill tone="indigo">Advisor mode</Pill>} title="Your client book" />
        <LoadingBlock label="Loading your client book" rows={5} />
      </>
    );
  }
  if (book.isError) {
    return (
      <>
        <ScreenHeader eyebrow="Advisor" pills={<Pill tone="indigo">Advisor mode</Pill>} title="Your client book" />
        <LoadFailed
          what="Your client book"
          error={book.error}
          onRetry={() => book.refetch()}
          forbidden="The server refused to return a client book for this account (403). Client books are only available to advisor accounts."
        />
      </>
    );
  }

  const parsedWs = MfdWorkspaceC.safeParse(book.data.workspace);
  const ws = parsedWs.success ? parsedWs.data : undefined;
  if (ws?.type && String(ws.type).toUpperCase() !== "ADVISORY") return <NotAnAdvisor />;

  const eyebrow = (
    <span data-testid="advisor-firm">{["Advisor", ws?.firm_name, ws?.arn_or_ria].filter(Boolean).join(" · ")}</span>
  );

  if (clients.length === 0) {
    return (
      <>
        <ScreenHeader eyebrow={eyebrow} pills={<Pill tone="indigo">Advisor mode</Pill>} title="Your client book" />
        <div data-testid="advisor-empty">
          <EmptyBlock
            title="No clients in your book yet"
            body="Add a client in the advisor workspace. Once their holdings are in, their health score, top issue and SIPs appear here."
            action={<Link to="/advisor" className="cp-link" style={{ fontSize: 13 }}>Add a client in the advisor workspace ›</Link>}
          />
        </div>
      </>
    );
  }

  const n = queue.length;
  const hasAum = clients.some((p) => p._aum != null);
  const totalAum = clients.reduce((acc, p) => acc + (p._aum ?? 0), 0);

  const sipRetry = (
    <button type="button" data-testid="advisor-tile-sips-retry" onClick={() => sips.refetch()} style={{ fontSize: 12, color: "var(--cp-ink-2)", background: "none", border: 0, padding: 0, cursor: "pointer" }}>Didn’t load · Retry ›</button>
  );
  const sipActive = num(sips.data?.active_sips_count);
  const sipFailed = num(sips.data?.failed_count);
  const sipMandates = num(sips.data?.mandate_at_risk_count);
  let sipTile: TileItem;
  if (sips.isPending) {
    sipTile = { k: "SIPs", v: "…", s: "Loading" };
  } else if (sips.isError) {
    sipTile = { k: "SIPs", v: "—", s: isForbidden(sips.error) ? "Not available to this account" : sipRetry };
  } else if (sipActive == null) {
    // Answered, but without a count: say so rather than print a figure.
    sipTile = { k: "SIPs", v: "—", s: sipRetry };
  } else if (sipActive === 0 && !sipFailed && !sipMandates) {
    sipTile = { k: "SIPs", v: <span data-testid="advisor-tile-sips">0</span>, s: <span data-testid="advisor-tile-sips-sub">None recorded for your clients</span> };
  } else {
    sipTile = {
      k: "SIPs",
      v: <span data-testid="advisor-tile-sips">{fmtNum(sipActive)}</span>,
      s: <span data-testid="advisor-tile-sips-sub">{fmtNum(sipFailed)} failed · {fmtNum(sipMandates)} mandates expiring in 90 days</span>,
    };
  }

  const tiles: TileItem[] = [
    { k: "Clients", v: <span data-testid="advisor-tile-clients">{fmtNum(clients.length)}</span>, s: "In your book" },
    { k: "AUM", v: <span data-testid="advisor-tile-aum">{hasAum ? fmtINR(totalAum, { compact: true }) : "—"}</span>, s: "Holdings value, else the AUM you entered" },
    { k: "At risk", v: <span data-testid="advisor-tile-at-risk">{fmtNum(n)}</span>, s: "Need action today", tone: n > 0 ? "amber" : "ink" },
    sipTile,
  ];

  // Wording follows the Copilot's own cross-client prompt catalogue
  // (backend/routes/copilot_prompts.py, _advisor_prompts), so these are
  // questions it is built to answer. The last one names a real client.
  const first = queue[0];
  const prompts: Array<{ label: string; query: string }> = [
    { label: "Which clients are off their target allocation?", query: "Which clients are deviating more than 10% from their target allocation? List the bucket that is off." },
    { label: "Which clients are lagging the Nifty 50?", query: "Show clients whose portfolios are lagging NIFTY 50 by more than 5%. Include AUM and gap size." },
    { label: "Who has over 40% in one fund or stock?", query: "List clients with more than 40% of their portfolio in a single fund or stock. Show the position and weight." },
    { label: "Which clients stopped their SIPs recently?", query: "Which of my clients have stopped or paused SIPs in the last 3 months? Show last contribution date." },
    ...(first ? [{ label: `Draft a review for ${first.name}`, query: `Draft a portfolio review for my client ${first.name}: what changed, the top issue and the recommended next step.` }] : []),
  ];

  const queueShown = allQueue ? queue : queue.slice(0, QUEUE_PREVIEW);
  const rosterShown = allRoster ? roster : roster.slice(0, ROSTER_PREVIEW);

  return (
    <>
      <ScreenHeader
        eyebrow={eyebrow}
        pills={<Pill tone="indigo">Advisor mode</Pill>}
        title={n > 0
          ? <><span data-testid="advisor-attention-count">{n}</span> {n === 1 ? "client needs" : "clients need"} you <em style={{ color: "var(--amber)" }}>today</em>.</>
          : <>No client needs you <em>today</em>.</>}
        sub={`Your ${clients.length === 1 ? "client is" : `${fmtNum(clients.length)} clients are`} ranked on portfolio weakness, risk, assets, pending recommendations and time since the last review. Open any client in the Copilot to work on their plan.`}
      />

      <Tiles items={tiles} />

      <div data-testid="advisor-queue" className="flex flex-col" style={{ gap: 10 }}>
        <Eyebrow>Needs attention · ranked by priority</Eyebrow>
        {n === 0 ? (
          <div data-testid="advisor-queue-empty">
            <EmptyBlock title="Every client is on track" body="No client has a risk flag, a pending recommendation or an overdue review right now." />
          </div>
        ) : (
          queueShown.map((p) => <QueueRow key={p.profile_id} p={p} onOpen={onOpen} openingId={openingId} />)
        )}
        {n > QUEUE_PREVIEW && (
          <button type="button" className="cp-chip" style={{ alignSelf: "flex-start" }} aria-expanded={allQueue} onClick={() => setAllQueue((v) => !v)}>
            {allQueue ? `Show top ${QUEUE_PREVIEW}` : `Show all ${n}`}
          </button>
        )}
      </div>

      <AskChips title="Ask about your book" items={prompts} />

      <Section
        flush
        className="cp-card-raised"
        title={<>Roster · <span data-testid="advisor-roster-shown">{rosterShown.length}</span> of <span data-testid="advisor-roster-total">{roster.length}</span></>}
        note="Sorted by health · select a client to open them"
      >
        <DataTable
          columns={ROSTER_COLUMNS}
          rows={rosterShown}
          rowKey={(p) => p.profile_id}
          minWidth={640}
          onRowClick={onOpen}
        />
        {roster.length > ROSTER_PREVIEW && (
          <div style={{ padding: "12px 16px" }}>
            <button type="button" className="cp-chip" aria-expanded={allRoster} onClick={() => setAllRoster((v) => !v)}>
              {allRoster ? `Show first ${ROSTER_PREVIEW}` : `Show all ${roster.length} clients`}
            </button>
          </div>
        )}
      </Section>

      <div className="grid" style={{ gridTemplateColumns: "repeat(auto-fit,minmax(min(100%,300px),1fr))", gap: 12, alignItems: "start" }}>
        <NotConnected
          testId="advisor-models-not-connected"
          title="Approved model portfolios"
          body="The design lists your model portfolios with their asset mix and how many clients follow each. Nothing stores model portfolios or links a client to one."
          needs={[
            "A store of the advisor’s approved model portfolios (name and equity / debt / other mix)",
            "A link from each client to the model they follow",
            "An endpoint that lists the models with their client counts",
          ]}
        />
        <NotConnected
          testId="advisor-reports-not-connected"
          title="Client report drafts"
          body="The design shows review drafts waiting for your approval. The backend can queue a review pack for one client, but nothing writes the document, so there are no drafts to list or approve."
          needs={[
            "A worker that produces the review pack (the generate endpoint only queues a task)",
            "A list of drafts awaiting the advisor’s approval, per client",
            "An approve-and-send step that records who approved what",
          ]}
        />
      </div>

      <Footnote>While a client is open, their profile is sent with every request and the server checks it belongs to your workspace · scores refresh in the background once they are an hour old</Footnote>
    </>
  );
}

export default function AdvisorScreen() {
  const { isAdvisorWorkspace, go } = useCopilotShell();
  const viewingId = useImpersonationStore((s) => s.profileId);
  const push = useToastStore((s) => s.push);
  // Held here, not in <Book>: opening a client flips the impersonation store,
  // and the callbacks below must still run after that re-render.
  const activate = useActivateProfile();
  const deactivate = useDeactivateProfile();
  const [openingId, setOpeningId] = useState<string | null>(null);
  // Set when the advisor leaves a client from this screen. Only an advisor can
  // be viewing a client, so the book is shown without waiting for the shell to
  // recompute isAdvisorWorkspace.
  const [returned, setReturned] = useState(false);

  const openClient: OpenClient = (p) => {
    if (openingId) return;
    setOpeningId(p.profile_id);
    activate.mutate({ profileId: p.profile_id, name: p.name }, {
      onSuccess: () => {
        push({ kind: "success", title: `Opened ${p.name}'s portfolio` });
        go("");
      },
      onError: (e) => {
        setOpeningId(null);
        push({ kind: "error", title: "Could not open profile", description: e instanceof Error ? e.message : undefined });
      },
    });
  };

  const backToBook = () => {
    setReturned(true);
    deactivate.mutate();
  };

  // While a client is being opened the book stays on screen until the shell
  // has moved to the Copilot home.
  const showBook = openingId != null || (!viewingId && (isAdvisorWorkspace || returned));

  return (
    <Screen testId="screen-advisor" width={1000}>
      {showBook
        ? <Book onOpen={openClient} openingId={openingId} />
        : viewingId ? <ViewingClient onBack={backToBook} returning={deactivate.isPending} /> : <NotAnAdvisor />}
    </Screen>
  );
}
