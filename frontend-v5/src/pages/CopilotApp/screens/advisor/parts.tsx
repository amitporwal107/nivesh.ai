/**
 * Advisor screens — pieces shared by the Client book, Client 360, the SIP
 * board and the advisor workspace mount:
 *
 *   useAdvisorSession   who may see an advisor screen, opening a client, leaving one
 *   AdvisorOnly         the screen, or the notice that explains why it is not shown
 *   QuerySection        a titled card around one request: loading, failed, or its data
 *   AssetName           a holding's name with the fund house or company icon
 */
import { useState, type ReactNode } from "react";
import type { UseQueryResult } from "@tanstack/react-query";
import { useActivateProfile, useDeactivateProfile } from "@/hooks/use-mfd";
import type { Tone as BookTone } from "@/pages/AdvisorDashboard/derive";
import { useImpersonationStore } from "@/stores/impersonation.store";
import { useToastStore } from "@/stores/toast.store";
import { FundName, NameCell, StockName } from "../../components/EntityIcon";
import { Btn, EmptyBlock, ErrorBlock, Pill, ScreenHeader, Section, type Tone } from "../../components/ui";
import { useCopilotShell } from "../../lib/shell-context";
import { assetKind } from "./data";

/** The original advisor workspace's tone names → this shell's. */
export const BOOK_TONE: Record<BookTone, Tone> = { neg: "danger", warm: "amber", pos: "mint", accent: "indigo", neutral: "ink" };

/** The Client 360 view for one client. The screen reads the client from the address. */
export function client360View(profileId: string): string {
  return `advisor/client-360?client=${encodeURIComponent(profileId)}`;
}

// ── who is looking ───────────────────────────────────────────────────────

export interface ClientRef {
  profile_id: string;
  name: string;
}

/**
 * "advisor"      an advisor at the root of their workspace: the screen shows
 * "viewing"      an advisor with a client open: every request is about that client
 * "not-advisor"  an account that manages one portfolio
 */
export type AdvisorGate = "advisor" | "viewing" | "not-advisor";

export interface AdvisorSession {
  gate: AdvisorGate;
  /**
   * Open a client the way the original app does (useActivateProfile → the
   * impersonation store, which every request then carries), then go to a view
   * inside the shell. "" is the Copilot home.
   */
  openClient: (client: ClientRef, view?: string) => void;
  /** The client being opened, until the shell has moved on. */
  openingId: string | null;
  backToBook: () => void;
  returning: boolean;
}

/**
 * Call this in the screen's top component, not in a child: opening a client
 * flips the impersonation store, and the callbacks here must still run after
 * that re-render.
 */
export function useAdvisorSession(): AdvisorSession {
  const { isAdvisorWorkspace, go } = useCopilotShell();
  const viewingId = useImpersonationStore((s) => s.profileId);
  const push = useToastStore((s) => s.push);
  const activate = useActivateProfile();
  const deactivate = useDeactivateProfile();
  const [openingId, setOpeningId] = useState<string | null>(null);
  // Set when the advisor leaves a client from this screen. Only an advisor can
  // be viewing a client, so the screen is shown without waiting for the shell
  // to recompute isAdvisorWorkspace.
  const [returned, setReturned] = useState(false);

  const openClient = (client: ClientRef, view = "") => {
    if (openingId) return;
    setOpeningId(client.profile_id);
    activate.mutate({ profileId: client.profile_id, name: client.name }, {
      onSuccess: () => {
        push({ kind: "success", title: `Opened ${client.name}'s portfolio` });
        go(view);
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

  // While a client is being opened the screen stays up until the shell has moved.
  const gate: AdvisorGate = openingId != null || (!viewingId && (isAdvisorWorkspace || returned))
    ? "advisor"
    : viewingId ? "viewing" : "not-advisor";

  return { gate, openClient, openingId, backToBook, returning: deactivate.isPending };
}

export function NotAnAdvisor() {
  const { go } = useCopilotShell();
  return (
    <div data-testid="advisor-not-advisor" className="flex flex-col" style={{ gap: 22 }}>
      <ScreenHeader eyebrow="Advisor" title="This screen is for advisor accounts" />
      <EmptyBlock
        title="Your account manages one portfolio"
        body="The advisor screens show a book of clients — who needs attention, their assets and their SIPs. This account is set up for a single investor, so there is no client book to show. If you advise clients, you can switch the account to advisor mode from the advisor workspace."
        action={
          <span className="flex flex-wrap items-center" style={{ gap: 8 }}>
            <Btn onClick={() => go("")}>Back to the Copilot</Btn>
            <Btn variant="ghost" data-testid="advisor-open-workspace" onClick={() => go("advisor/workspace")}>Open the advisor workspace ›</Btn>
          </span>
        }
      />
    </div>
  );
}

export function ViewingClient({ onBack, returning }: { onBack: () => void; returning: boolean }) {
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

/** The screen for an advisor at their workspace root; otherwise the notice that says why not. */
export function AdvisorOnly({ session, children }: { session: AdvisorSession; children: ReactNode }) {
  if (session.gate === "advisor") return <>{children}</>;
  if (session.gate === "viewing") return <ViewingClient onBack={session.backToBook} returning={session.returning} />;
  return <NotAnAdvisor />;
}

// ── one request, one card ────────────────────────────────────────────────

const SKELETON_WIDTHS = [92, 78, 64];

function Skeleton({ label }: { label: string }) {
  return (
    <div role="status" aria-label={label} className="flex flex-col" style={{ gap: 10 }}>
      {SKELETON_WIDTHS.map((w) => (
        <span key={w} className="cp-running" style={{ height: 14, borderRadius: 6, background: "var(--bg-2)", width: `${w}%` }} />
      ))}
    </div>
  );
}

/**
 * A titled card around one request. While it loads the card shows a
 * placeholder; if it fails the card says so and offers a retry; otherwise
 * `children` renders the data (including its own empty state).
 */
export function QuerySection<T>({ title, note, query, what, testId, flush, children }: {
  title: ReactNode;
  note?: ReactNode;
  query: UseQueryResult<T>;
  /** What is being loaded, as the subject of "… didn’t load". */
  what: string;
  testId?: string;
  /** The data fills the card edge to edge (a table). */
  flush?: boolean;
  children: (data: T) => ReactNode;
}) {
  return (
    <div data-testid={testId} className="min-w-0">
      <Section title={title} note={note} flush={flush && query.isSuccess}>
        {query.isPending ? (
          <Skeleton label={`Loading ${what.charAt(0).toLowerCase()}${what.slice(1)}`} />
        ) : query.isError ? (
          <ErrorBlock title={`${what} didn’t load`} error={query.error} onRetry={() => query.refetch()} />
        ) : (
          children(query.data)
        )}
      </Section>
    </div>
  );
}

/** A quiet line for a card that has nothing to list. */
export function Quiet({ children, testId }: { children: ReactNode; testId?: string }) {
  return <span data-testid={testId} style={{ display: "block", fontSize: 13, lineHeight: 1.55, color: "var(--cp-ink-3)" }}>{children}</span>;
}

// ── names ────────────────────────────────────────────────────────────────

const ICON = 24;

/**
 * A holding's name: a fund gets its fund house icon, a stock its company icon,
 * anything else (gold, a bond, an unknown type) the name alone.
 *
 * These endpoints name a stock but do not send its exchange symbol unless
 * `ticker` is set, so the company icon is keyed by the name.
 */
export function AssetName({ name, assetType, ticker, sub, testId }: {
  name: string;
  assetType?: string | null;
  ticker?: string | null;
  sub?: ReactNode;
  testId?: string;
}) {
  const kind = assetKind(assetType, name);
  if (kind === "fund") return <FundName name={name} sub={sub} size={ICON} testId={testId} />;
  if (kind === "stock") return <StockName symbol={ticker?.trim() || name} name={name} sub={sub} size={ICON} testId={testId} />;
  return <NameCell icon={null} name={name} sub={sub} testId={testId} />;
}
