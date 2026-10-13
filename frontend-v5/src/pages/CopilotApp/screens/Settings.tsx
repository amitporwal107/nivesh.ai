/**
 * Settings.
 * Design: frontend-v5/design/nivesh-copilot/NVPages.dc.html (page === "settings").
 *
 * Real: the account (useMe), mode (Copilot prefs), risk profile, goals, the
 * financial snapshot, theme, notification choices, connections (Gmail, CAS
 * statement, broker accounts), saved conversations, consent records, account
 * activity, the data export and session logging (./account/settings-cards).
 * The design's answer depth, constraints and memory have no backend; changing
 * a consent, a retention period and deleting the account are not offered
 * (the privacy block says why). Those are shown as NotConnected.
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
import { needsReconnect, useBrokerAccounts } from "./account/broker-queries";
import { hasStatement, toRead, useDataExport, useGmailSourceStatus, useOnboardingState } from "./account/queries";
import { ActivityCard, DiagnosticsCard, Loaded, NotificationsCard, PrivacyCard, SnapshotCard } from "./account/settings-cards";

type Wizard = ReturnType<typeof useProfileWizard>;

const MODES: Mode[] = ["investor", "trader", "advisor"];

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
              ? [
                  list.map((a) => a.label || a.broker_display || a.broker).filter(Boolean).join(", "),
                  list.some(needsReconnect) ? `${fmtNum(list.filter(needsReconnect).length)} need a new sign-in` : null,
                ].filter(Boolean).join(" · ")
              : "None connected"}
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
      <Row label="Download your data" sub="Your account record, holdings, action plans and consent records in one JSON file. Goals, conversations and the PAN saved for opening statements are not in it." testId="settings-export">
        <Btn data-testid="settings-export-button" disabled={exportQuery.isFetching} onClick={() => void download()}>
          {exportQuery.isFetching ? "Preparing…" : "Download"}
        </Btn>
      </Row>
      {exportQuery.isError && !exportQuery.isFetching && (
        <div style={{ padding: "8px 0" }}>
          <ErrorBlock title="The download didn’t start" error={exportQuery.error} onRetry={() => void download()} />
        </div>
      )}
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
        <SnapshotCard />
        <ConnectionsCard />
        <NotificationsCard />
        <AppearanceCard />
        <PrivacyCard />
        <DataCard />
        <ActivityCard />
        <DiagnosticsCard />
      </div>

      <div className="grid" style={{ gridTemplateColumns: columns, gap: 12, alignItems: "start" }}>
        <NotConnected
          testId="settings-answer-depth-missing"
          title="Answer depth can’t be set yet"
          body="The design lets you choose how answers read: plain words, key numbers, or full depth. Nivesh has nowhere to keep that choice, and the Copilot does not take one."
          needs={[
            "A stored per-user answer-depth setting: GET / PATCH /api/user/preferences keeps notification flags only (routes/user.py)",
            "The Copilot taking it: POST /api/chat/stream reads a message, a session id and an agent name, nothing about depth (routes/chat.py :: stream_chat)",
          ]}
        />
        <NotConnected
          testId="settings-constraints-missing"
          title="Constraints aren’t stored yet"
          body="A single-stock limit, a sector limit, a cash buffer and things never to suggest. Nivesh keeps your risk profile and goals, but no limits of your own."
          needs={[
            "A per-user store for limits and exclusions with read and save endpoints: none exists (the rule thresholds at /api/admin/rules-config and the allocation bands at /api/admin/allocation-bands apply to every user and are admin-only)",
            "Recommendations and Copilot answers reading those limits",
          ]}
        />
        <NotConnected
          testId="settings-memory-missing"
          title="Memory isn’t available yet"
          body="Preferences remembered from your chats, each one reviewable and forgettable. Nivesh keeps your conversations, which you can delete under Privacy, but does not draw preferences out of them."
          needs={[
            "A store of preferences the Copilot has picked up from chats: none exists (chat_sessions and chat_messages hold the transcripts only)",
            "Endpoints to list them, forget one, and turn remembering on or off",
          ]}
        />
        <NotConnected
          testId="settings-privacy-missing"
          title="Some privacy controls aren’t available yet"
          body="Changing a consent choice, choosing how long conversations are kept, and deleting your account from inside the app."
          needs={[
            "Consent changes: POST / DELETE /api/compliance/consents/{purpose} exist, but the notice text they record against is out of date (services/consents.py names one AI provider; the Copilot can use others) and nothing checks a consent before acting, apart from PUT /api/compliance/pan. Fix the notices and enforce them, then offer the switches",
            "Account deletion: DELETE /api/compliance/account removes holdings and action plans and sets is_deleted on the user, but nothing reads is_deleted (sign-in still works) and the profile with the saved PAN and statement password, the Gmail token, goals, conversations and broker accounts are left. It is not offered as “delete my account” until it does that",
            "A retention setting for conversation history (none exists; conversations are kept until deleted)",
          ]}
        />
      </div>

      {wizard.element}
    </Screen>
  );
}
