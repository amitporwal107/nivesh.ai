/**
 * Settings.
 * Design: frontend-v5/design/nivesh-copilot/NVPages.dc.html (page === "settings").
 *
 * Real: the account (useMe), mode (Copilot prefs), risk profile, goals, theme,
 * connections (Gmail, CAS statement, broker accounts) and the data export.
 * The design's answer depth, constraints, memory and privacy controls have no
 * backend and are shown as NotConnected.
 */
import { useState, type ReactNode } from "react";
import { useLogout, useMe } from "@/hooks/use-auth";
import { useGoalArchive } from "@/hooks/use-goals";
import { useUIStore } from "@/stores/ui.store";
import type { Goal } from "@/types/goal";
import { Btn, EmptyBlock, ErrorBlock, LoadingBlock, NotConnected, Pill, Screen, ScreenHeader, Section, fmtDate, fmtINR, fmtNum } from "../components/ui";
import { useCopilotShell } from "../lib/shell-context";
import { useCopilotPrefs } from "../lib/store";
import { MODE_LABEL, type Mode } from "../lib/views";
import { InlineError, LinkButton, Row, ToggleChip, errorText, goalHorizonYears, riskAssessed, useProfileWizard } from "./account/parts";
import { hasStatement, toRead, useBrokerAccounts, useDataExport, useGmailSourceStatus, useOnboardingState, type Read } from "./account/queries";

type Wizard = ReturnType<typeof useProfileWizard>;

const MODES: Mode[] = ["investor", "trader", "advisor"];

/** Loading and error for one source inside a card; the row itself once it has validated data. */
function Loaded<T>({ read, what, children }: { read: Read<T>; what: string; children: (data: T) => ReactNode }) {
  if (read.state === "loading") return <div style={{ padding: "8px 0" }}><LoadingBlock label={`Loading ${what}`} rows={1} /></div>;
  if (read.state === "error") return <div style={{ padding: "8px 0" }}><ErrorBlock title={`${what} didn’t load`} error={read.error} onRetry={read.retry} /></div>;
  return <>{children(read.data)}</>;
}

// ── profile ──────────────────────────────────────────────────────────────

function ProfileCard({ wizard }: { wizard: Wizard }) {
  const { mode, isAdvisorWorkspace } = useCopilotShell();
  const setMode = useCopilotPrefs((s) => s.setMode);
  const me = useMe();
  const logout = useLogout();

  return (
    <Section title="Profile">
      <Loaded read={toRead(me)} what="Your account">
        {(user) => (
          <Row label="Signed in as" sub={user.name ? <span data-testid="settings-name">{user.name}</span> : undefined}>
            <span data-testid="settings-email" style={{ fontSize: 13, color: "var(--cp-ink-2)", overflowWrap: "anywhere" }}>{user.email}</span>
          </Row>
        )}
      </Loaded>

      <Row label="Mode" sub="Sets the tools in the menu. Advisor needs an advisor workspace." testId="settings-mode">
        <div role="group" aria-label="Mode" className="flex flex-wrap" style={{ gap: 6 }}>
          {MODES.map((m) => {
            const locked = m === "advisor" && !isAdvisorWorkspace;
            return (
              <ToggleChip
                key={m}
                data-testid={`settings-mode-${m}`}
                on={mode === m}
                disabled={locked}
                title={locked ? "This account is not an advisor workspace" : undefined}
                onClick={() => setMode(m)}
              >
                {MODE_LABEL[m]}
              </ToggleChip>
            );
          })}
        </div>
      </Row>

      <Loaded read={wizard.risk} what="Risk profile">
        {(profile) => (
          <Row
            label="Risk profile"
            testId="settings-risk"
            sub={profile ? riskAssessed(profile) || undefined : "Not assessed yet. A short questionnaire sets it."}
          >
            {profile && <span data-testid="settings-risk-category"><Pill tone="mint">{profile.category}</Pill></span>}
            <Btn data-testid="settings-risk-retake" onClick={wizard.openRisk}>{profile ? "Retake" : "Take the assessment"}</Btn>
          </Row>
        )}
      </Loaded>

      <div className="flex flex-wrap items-center" style={{ gap: 10, paddingTop: 14 }}>
        <Btn data-testid="settings-signout" disabled={logout.isPending} onClick={() => logout.mutate()}>
          {logout.isPending ? "Signing out…" : "Sign out"}
        </Btn>
      </div>
    </Section>
  );
}

// ── goals ────────────────────────────────────────────────────────────────

function goalNote(g: Goal): string {
  const years = goalHorizonYears(g.targetDate);
  const onTrack = Math.round(g.progress * 100);
  return [
    `${fmtINR(g.targetAmount / 100, { compact: true })} target`,
    years ? `${years}-year horizon` : null,
    g.monthlySip > 0 ? `${fmtINR(g.monthlySip / 100)} a month` : null,
    onTrack > 0 ? `${onTrack}% on track` : null,
  ].filter(Boolean).join(" · ");
}

function GoalsCard({ wizard }: { wizard: Wizard }) {
  const { goals } = wizard;
  const archive = useGoalArchive();
  const [confirmId, setConfirmId] = useState<string | null>(null);

  let body: ReactNode;
  if (goals.isPending) body = <LoadingBlock label="Loading goals" rows={2} />;
  else if (goals.isError) body = <ErrorBlock title="Goals didn’t load" error={goals.error} onRetry={() => goals.refetch()} />;
  else if (goals.data.goals.length === 0) {
    body = <EmptyBlock title="No goals yet" body="A goal gives Nivesh an amount and a horizon to plan against." />;
  } else {
    body = goals.data.goals.map((g) => (
      <Row key={g.id} testId="settings-goal" label={<span data-testid="settings-goal-name">{g.name}</span>} sub={goalNote(g)}>
        {confirmId === g.id ? (
          <>
            <Btn
              data-testid="settings-goal-archive-confirm"
              disabled={archive.isPending}
              onClick={() => archive.mutate(g.id, { onSettled: () => setConfirmId(null) })}
              style={{ color: "var(--cp-danger)", borderColor: "var(--danger-line)" }}
            >
              {archive.isPending ? "Archiving…" : "Yes, archive"}
            </Btn>
            <Btn variant="ghost" disabled={archive.isPending} onClick={() => setConfirmId(null)}>Keep</Btn>
          </>
        ) : (
          <Btn data-testid="settings-goal-archive" disabled={archive.isPending} onClick={() => setConfirmId(g.id)}>Archive</Btn>
        )}
      </Row>
    ));
  }

  return (
    <Section title="Goals">
      {body}
      {archive.isError && <div style={{ paddingTop: 8 }}><InlineError>Couldn’t archive that goal. {errorText(archive.error, "")}</InlineError></div>}
      <div style={{ paddingTop: 12 }}>
        <LinkButton tone="mint" data-testid="settings-add-goal" onClick={wizard.openGoal}>＋ Add a goal</LinkButton>
      </div>
    </Section>
  );
}

// ── appearance ───────────────────────────────────────────────────────────

function AppearanceCard() {
  const theme = useUIStore((s) => s.theme);
  const setTheme = useUIStore((s) => s.setTheme);
  return (
    <Section title="Appearance">
      <Row label="Theme" sub="Applies to all of Nivesh in this browser." testId="settings-theme">
        <div role="group" aria-label="Theme" className="flex flex-wrap" style={{ gap: 6 }}>
          <ToggleChip data-testid="settings-theme-light" on={theme === "light"} onClick={() => setTheme("light")}>Light</ToggleChip>
          <ToggleChip data-testid="settings-theme-dark" on={theme === "dark"} onClick={() => setTheme("dark")}>Dark</ToggleChip>
        </div>
      </Row>
    </Section>
  );
}

// ── connections ──────────────────────────────────────────────────────────

function ConnectionsCard() {
  const { go } = useCopilotShell();
  const gmail = useGmailSourceStatus();
  const state = useOnboardingState();
  const accounts = useBrokerAccounts();

  return (
    <Section title="Connections">
      <Loaded read={gmail} what="Gmail status">
        {(g) => (
          <Row label="Gmail" sub={g.connected ? `Read-only, used to find CAS emails${g.connected_at ? ` · connected ${fmtDate(g.connected_at)}` : ""}` : "Used to find CAS emails"}>
            <span data-testid="settings-gmail-status"><Pill tone={g.connected ? "mint" : "ink"}>{g.connected ? "Connected" : "Not connected"}</Pill></span>
          </Row>
        )}
      </Loaded>
      <Loaded read={toRead(state)} what="Statement status">
        {(s) => (
          <Row
            label="CAS statement"
            sub={hasStatement(s)
              ? [s.cas_statement_period ? `Period ${s.cas_statement_period}` : null, s.cas_statement_date ? `dated ${s.cas_statement_date}` : null].filter(Boolean).join(" · ") || "Imported"
              : "Upload one, or let Gmail find it"}
          >
            <span data-testid="settings-statement-status"><Pill tone={hasStatement(s) ? "mint" : "ink"}>{hasStatement(s) ? "On file" : "None on file"}</Pill></span>
          </Row>
        )}
      </Loaded>
      <Loaded read={toRead(accounts)} what="Broker accounts">
        {(list) => (
          <Row
            label="Broker accounts"
            sub={list.length > 0
              ? list.map((a) => a.label || a.broker_display || a.broker).filter(Boolean).join(", ")
              : "Broker sign-in isn’t available yet"}
          >
            <span className="cp-num" data-testid="settings-broker-count" style={{ fontSize: 13, color: "var(--cp-ink-2)" }}>{fmtNum(list.length)} connected</span>
          </Row>
        )}
      </Loaded>
      <div style={{ paddingTop: 14 }}>
        <Btn data-testid="settings-manage-connections" onClick={() => go("page/brokers")}>Manage connections</Btn>
      </div>
    </Section>
  );
}

// ── your data ────────────────────────────────────────────────────────────

function saveJson(data: unknown, filename: string) {
  const url = URL.createObjectURL(new Blob([JSON.stringify(data, null, 2)], { type: "application/json" }));
  const a = document.createElement("a");
  a.href = url;
  a.download = filename;
  document.body.appendChild(a);
  a.click();
  a.remove();
  URL.revokeObjectURL(url);
}

function DataCard() {
  const exportQuery = useDataExport();

  const download = async () => {
    const r = await exportQuery.refetch();
    if (r.isSuccess && r.data != null) saveJson(r.data, `nivesh-data-${new Date().toISOString().slice(0, 10)}.json`);
  };

  return (
    <Section title="Your data">
      <Row label="Download your data" sub="Your account record, holdings, action plans and consent records in one JSON file. A stored PAN is masked." testId="settings-export">
        <Btn data-testid="settings-export-button" disabled={exportQuery.isFetching} onClick={() => void download()}>
          {exportQuery.isFetching ? "Preparing…" : "Download"}
        </Btn>
      </Row>
      {exportQuery.isError && !exportQuery.isFetching && (
        <div style={{ padding: "8px 0" }}>
          <ErrorBlock title="The download didn’t start" error={exportQuery.error} onRetry={() => void download()} />
        </div>
      )}
      <Row label="Delete your account" sub="Not available in this app yet.">
        <Btn disabled title="Account deletion has no confirmed flow in this app yet">Delete</Btn>
      </Row>
    </Section>
  );
}

// ── screen ───────────────────────────────────────────────────────────────

export default function SettingsScreen() {
  const { go } = useCopilotShell();
  const wizard = useProfileWizard();
  const columns = "repeat(auto-fit,minmax(min(100%,400px),1fr))";

  return (
    <Screen testId="screen-page-settings">
      <div className="flex flex-wrap items-end justify-between" style={{ gap: 14 }}>
        <div style={{ flex: "1 1 320px", minWidth: 0 }}>
          <ScreenHeader
            eyebrow="Settings"
            title={<>Make Nivesh <em>yours</em></>}
            sub="Your risk profile, goals and connected sources drive what Nivesh recommends."
          />
        </div>
        <button
          type="button"
          className="cp-chip"
          data-testid="settings-redo-onboarding"
          onClick={() => go("onboarding")}
          style={{ borderColor: "var(--mint-line)", color: "var(--mint)" }}
        >
          Redo onboarding
        </button>
      </div>

      <div className="grid" style={{ gridTemplateColumns: columns, gap: 12, alignItems: "start" }}>
        <ProfileCard wizard={wizard} />
        <GoalsCard wizard={wizard} />
        <ConnectionsCard />
        <AppearanceCard />
        <DataCard />
      </div>

      <div className="grid" style={{ gridTemplateColumns: columns, gap: 12, alignItems: "start" }}>
        <NotConnected
          testId="settings-answer-depth-missing"
          title="Answer depth can’t be set yet"
          body="The design lets you choose how answers read: plain words, key numbers, or full depth."
          needs={[
            "A stored per-user answer-depth setting, with an endpoint to read and save it",
            "The Copilot using that setting when it writes an answer",
          ]}
        />
        <NotConnected
          testId="settings-constraints-missing"
          title="Constraints aren’t stored yet"
          body="A single-stock limit, a sector limit, a cash buffer and things never to suggest."
          needs={[
            "An endpoint that stores a user’s limits and exclusions",
            "Recommendations and answers that read those limits",
          ]}
        />
        <NotConnected
          testId="settings-memory-missing"
          title="Memory isn’t available yet"
          body="Preferences remembered from your chats, each one reviewable and forgettable."
          needs={[
            "A store of preferences the Copilot has picked up from chats",
            "Endpoints to list them, forget one, and turn remembering on or off",
          ]}
        />
        <NotConnected
          testId="settings-privacy-missing"
          title="Privacy controls aren’t available yet"
          body="How long conversations are kept, and deleting your account from inside the app."
          needs={[
            "A retention setting for conversation history",
            "A confirmed delete-account flow in this app (the server has DELETE /api/compliance/account; nothing here calls it)",
            "A data-location and statement-retention policy this screen can quote",
          ]}
        />
      </div>

      {wizard.element}
    </Screen>
  );
}
