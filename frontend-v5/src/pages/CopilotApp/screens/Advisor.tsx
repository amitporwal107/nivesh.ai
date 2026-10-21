/**
 * Advisor home — the client book at a glance, who needs attention, and the roster.
 * Design: frontend-v5/design/nivesh-copilot/NVAdvisor.dc.html.
 *
 * Data:
 *   firm, headline, tiles, queue, roster   GET /api/mfd/profiles               (useAdvisorBook)
 *   SIP tile                               GET /api/advisor/sip-board/summary  (useSipSummary)
 * Health, top issue and the "needs action" test are the same derivations the
 * current advisor workspace uses (pages/AdvisorDashboard/derive), so the two
 * pages agree on every number.
 *
 * Two ways into a client:
 *   "Open in Copilot" switches to the client the way the current app does
 *   (useActivateProfile → impersonation store), then goes to the Copilot home.
 *   "Client 360" reads the client without switching: it goes to
 *   advisor/client-360?client=<profile id>.
 *
 * Model portfolios and report drafts have no backend and say so.
 */
import { useMemo, useState } from "react";
import { useAdvisorBook } from "@/hooks/use-advisor";
import { decorateProfile, fmtDaysSince, healthTone, type AdvisorProfile } from "@/pages/AdvisorDashboard/derive";
import { MfdWorkspaceC } from "@/services/contracts/advisor.contract";
import {
  AskChips, Btn, DataTable, EmptyBlock, Eyebrow, Footnote, LoadingBlock, NotConnected, Pill,
  Screen, ScreenHeader, Section, Tiles, TONE_COLOR, fmtINR, fmtNum,
  type Column, type TileItem, type Tone,
} from "../components/ui";
import { useCopilotShell } from "../lib/shell-context";
import { SCREENS } from ".";
import { useSipSummary } from "./advisor/data";
import { AdvisorOnly, BOOK_TONE, NotAnAdvisor, client360View, useAdvisorSession } from "./advisor/parts";
import { LoadFailed, isForbidden } from "./internal/shared";

const QUEUE_PREVIEW = 5;
const ROSTER_PREVIEW = 10;

const BUCKET_TONE: Record<string, Tone> = { high: "danger", medium: "amber" };

/** The reason a client is in the queue: the priority engine's first reason, else the derived top issue. */
function issueOf(p: AdvisorProfile): string {
  return p.priority?.reasons?.[0] ?? p._issue?.label ?? "";
}

type OpenClient = (p: AdvisorProfile) => void;

/** The SIP board is linked only once it is a registered screen (screens/index.ts). */
const SIP_BOARD_VIEW = "advisor/sip-board";
const HAS_SIP_BOARD = SIP_BOARD_VIEW in SCREENS;

const LINK_BUTTON = { fontSize: 13, color: "var(--cp-ink)", background: "none", border: 0, padding: 0, cursor: "pointer", fontFamily: "var(--sans)" } as const;

// ── the book ─────────────────────────────────────────────────────────────

function QueueRow({ p, onOpen, openingId }: { p: AdvisorProfile; onOpen: OpenClient; openingId: string | null }) {
  const { mobile, go } = useCopilotShell();
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
      <span data-testid="advisor-queue-aum" className="cp-num" style={{ fontFamily: "var(--display)", fontSize: 20, ...(mobile ? { flex: "1 1 100%" } : null) }}>{fmtINR(p._aum, { compact: true })}</span>
      <Btn
        data-testid="advisor-queue-360"
        variant="ghost"
        aria-label={`Client 360: ${p.name}`}
        onClick={() => go(client360View(p.profile_id))}
        style={mobile ? { flex: "1 1 120px" } : undefined}
      >
        Client 360
      </Btn>
      <Btn
        data-testid="advisor-open-client"
        aria-label={`Open in Copilot: ${p.name}`}
        disabled={openingId != null}
        onClick={() => onOpen(p)}
        style={mobile ? { flex: "1 1 150px" } : undefined}
      >
        {openingId === p.profile_id ? "Opening…" : "Open in Copilot"}
      </Btn>
    </div>
  );
}

/** Reads the client without switching to them. Inside a row that itself opens the client. */
function See360({ p }: { p: AdvisorProfile }) {
  const { go } = useCopilotShell();
  return (
    <button
      type="button"
      data-testid="advisor-client-360"
      aria-label={`Client 360: ${p.name}`}
      onClick={(e) => { e.stopPropagation(); go(client360View(p.profile_id)); }}
      onKeyDown={(e) => e.stopPropagation()}
      style={LINK_BUTTON}
    >
      Client 360 ›
    </button>
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
  { key: "see", header: <span className="sr-only">Client 360</span>, width: "96px", align: "right", render: (p) => <See360 p={p} /> },
];

function Book({ onOpen, openingId }: { onOpen: OpenClient; openingId: string | null }) {
  const { go } = useCopilotShell();
  const book = useAdvisorBook();
  const sips = useSipSummary();
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
    // The advisor's own portfolio is a profile too; it is not a client, but Client 360 can read it.
    const self = book.data.profiles.find((p) => p.type === "SELF");
    return (
      <>
        <ScreenHeader eyebrow={eyebrow} pills={<Pill tone="indigo">Advisor mode</Pill>} title="Your client book" />
        <div data-testid="advisor-empty">
          <EmptyBlock
            title="No clients in your book yet"
            body="Add a client in the advisor workspace. Once their holdings are in, their health score, top issue and SIPs appear here."
            action={
              <span className="flex flex-wrap items-center" style={{ gap: 8 }}>
                <Btn data-testid="advisor-empty-add" variant="primary" onClick={() => go("advisor/workspace")}>Add a client in the advisor workspace ›</Btn>
                {self && (
                  <Btn data-testid="advisor-empty-own-360" variant="ghost" onClick={() => go(client360View(self.profile_id))}>See your own portfolio in Client 360 ›</Btn>
                )}
              </span>
            }
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
  const sipBoardLink = HAS_SIP_BOARD && (
    <button type="button" data-testid="advisor-open-sip-board" onClick={() => go(SIP_BOARD_VIEW)} style={{ ...LINK_BUTTON, fontSize: 12, textAlign: "left" }}>Open the SIP board ›</button>
  );
  let sipTile: TileItem;
  if (sips.isPending) {
    sipTile = { k: "SIPs", v: "…", s: "Loading" };
  } else if (sips.isError) {
    // Also where an answer that is not a SIP summary ends up: no figure is printed for it.
    sipTile = { k: "SIPs", v: "—", s: isForbidden(sips.error) ? "Not available to this account" : sipRetry };
  } else {
    const { active_sips_count: count, failed_count: failed, mandate_at_risk_count: mandates } = sips.data;
    const none = count === 0 && failed === 0 && mandates === 0;
    sipTile = {
      k: "SIPs",
      v: <span data-testid="advisor-tile-sips">{fmtNum(count)}</span>,
      s: (
        <span className="flex flex-col items-start" style={{ gap: 4 }}>
          <span data-testid="advisor-tile-sips-sub">{none ? "None recorded for your clients" : `${fmtNum(failed)} failed · ${fmtNum(mandates)} mandates expiring in 90 days`}</span>
          {sipBoardLink}
        </span>
      ),
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
        note="Sorted by health · select a row to open the client in the Copilot"
      >
        <DataTable
          columns={ROSTER_COLUMNS}
          rows={rosterShown}
          rowKey={(p) => p.profile_id}
          minWidth={740}
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
            "Closest thing today: POST /api/portfolio-builder/generate builds one proposed portfolio for the signed-in investor; it is not saved and is not tied to an advisor",
          ]}
        />
        <NotConnected
          testId="advisor-reports-not-connected"
          title="Client report drafts"
          body="The design shows review drafts waiting for your approval. Nivesh can take a request for a client’s review pack, but nothing writes the document, so there are no drafts to list or approve. Until then, a client’s holdings can be downloaded as a spreadsheet from their Client 360."
          needs={[
            "A worker that produces the review pack: POST /api/mfd/profiles/{id}/review-pack/generate only stores a task with status “queued”, and nothing changes it afterwards",
            "The status poll answers lower-case “queued”; the app’s contract accepts QUEUED / PROCESSING / COMPLETED / FAILED, so the shared hook rejects it",
            "A list of drafts awaiting the advisor’s approval, per client",
            "An approve-and-send step that records who approved what",
            "Exists today: holdings as CSV or Excel per client (wired in Client 360), and a proposal PDF for the signed-in investor at POST /api/portfolio-builder/export.pdf",
          ]}
        />
      </div>

      <Footnote>While a client is open, their profile is sent with every request and the server checks it belongs to your workspace · scores refresh in the background once they are an hour old</Footnote>
    </>
  );
}

export default function AdvisorScreen() {
  // Held here, not in <Book>: opening a client flips the impersonation store,
  // and the session's callbacks must still run after that re-render.
  const session = useAdvisorSession();
  return (
    <Screen testId="screen-advisor" width={1000}>
      <AdvisorOnly session={session}>
        <Book onOpen={session.openClient} openingId={session.openingId} />
      </AdvisorOnly>
    </Screen>
  );
}
