/**
 * Settings — cards fed by endpoints the original Settings page used or that
 * had no screen at all:
 *
 *   Notifications        GET / PATCH /api/user/preferences
 *   Financial snapshot   GET /api/goals/snapshot · PUT through useSnapshotUpsert
 *   Privacy              GET /api/compliance/consents (recorded choices, read-only)
 *                        GET /api/chat/sessions (useChatSessions) · DELETE /api/chat/clear
 *   Account activity     GET /api/compliance/audit
 *   Diagnostics          useSessionLogging (POST /api/session-logs/enable | disable)
 */
import { useId, useState, type FormEvent, type ReactNode } from "react";
import { Link } from "react-router-dom";
import { useChatSessions } from "@/hooks/use-chat";
import { useSnapshotUpsert } from "@/hooks/use-goals";
import { useSessionLogging } from "@/hooks/use-session-logs";
import { Btn, EmptyBlock, ErrorBlock, LoadingBlock, Pill, Section, errorSentence, fmtDate, fmtNum, humaniseTag, relTime, type Tone } from "../../components/ui";
import { InlineError, Row, Switch, fieldStyle } from "./parts";
import {
  snapshotBody,
  toRead,
  useAuditTrail,
  useClearConversations,
  useConsents,
  useFinancialSnapshot,
  useNotificationPrefs,
  useSaveNotificationPrefs,
  type AuditRow,
  type Consent,
  type FinancialSnapshot,
  type Read,
} from "./queries";

/** Loading and error for one source inside a card; the rows themselves once it has validated data. */
export function Loaded<T>({ read, what, children }: { read: Read<T>; what: string; children: (data: T) => ReactNode }) {
  if (read.state === "loading") return <div style={{ padding: "8px 0" }}><LoadingBlock label={`Loading ${what}`} rows={1} /></div>;
  if (read.state === "error") return <div style={{ padding: "8px 0" }}><ErrorBlock title={`${what} didn’t load`} error={read.error} onRetry={read.retry} /></div>;
  return <>{children(read.data)}</>;
}

const why = (e: unknown) => errorSentence(e) || "the request failed";

// ── notifications ────────────────────────────────────────────────────────

export function NotificationsCard() {
  const prefs = useNotificationPrefs();
  const save = useSaveNotificationPrefs();
  return (
    <Section title="Notifications">
      <Loaded read={toRead(prefs)} what="Notification choices">
        {(n) => (
          <>
            <Row label="Push notifications" testId="settings-notify-push">
              <Switch data-testid="settings-notify-push-switch" label="Push notifications" checked={n.push} disabled={save.isPending} onClick={() => save.mutate({ push: !n.push })} />
            </Row>
            <Row label="Email" testId="settings-notify-email">
              <Switch data-testid="settings-notify-email-switch" label="Email notifications" checked={n.email} disabled={save.isPending} onClick={() => save.mutate({ email: !n.email })} />
            </Row>
          </>
        )}
      </Loaded>
      {!save.isPending && save.data?.ok === false && (
        <div data-testid="settings-notify-error" style={{ paddingTop: 8 }}>
          <InlineError>That choice wasn’t saved ({why(save.data.error)}). It is unchanged.</InlineError>
        </div>
      )}
      <p className="m-0" data-testid="settings-notify-note" style={{ paddingTop: 12, fontSize: 12, lineHeight: 1.55, color: "var(--cp-ink-3)" }}>
        Nivesh saves these choices. It does not send push or email notifications yet, so they have no effect today.
      </p>
    </Section>
  );
}

// ── financial snapshot ───────────────────────────────────────────────────

const numOrNull = (s: string): number | null => (s.trim() === "" ? null : Number(s));
const str = (n: number | null | undefined) => (n == null ? "" : String(n));

type SnapshotSave = ReturnType<typeof useSnapshotUpsert>;

function SnapshotForm({ current, save }: { current: FinancialSnapshot | null; save: SnapshotSave }) {
  const ids = { age: useId(), dep: useId(), inc: useId(), exp: useId() };
  const [age, setAge] = useState(str(current?.age));
  const [dependents, setDependents] = useState(str(current?.dependents ?? 0));
  const [income, setIncome] = useState(str(current?.monthly_income_rs));
  const [expenses, setExpenses] = useState(str(current?.monthly_expenses_rs));
  const [problem, setProblem] = useState<string | null>(null);
  // "Saved" is hidden again as soon as a field changes.
  const [edited, setEdited] = useState(false);

  const edit = (set: (v: string) => void) => (v: string) => { set(v); setEdited(true); setProblem(null); };

  const submit = (e: FormEvent) => {
    e.preventDefault();
    const a = numOrNull(age);
    const d = numOrNull(dependents) ?? 0;
    const inc = numOrNull(income);
    const exp = numOrNull(expenses);
    if (a != null && (!Number.isInteger(a) || a < 18 || a > 100)) return setProblem("Age must be a whole number between 18 and 100.");
    if (!Number.isInteger(d) || d < 0 || d > 20) return setProblem("Dependents must be a whole number from 0 to 20.");
    if ((inc != null && !(inc >= 0)) || (exp != null && !(exp >= 0))) return setProblem("Income and expenses must be amounts in rupees, zero or more.");
    setProblem(null);
    setEdited(false);
    save.mutate(snapshotBody(current, { age: a, dependents: d, monthly_income_rs: inc, monthly_expenses_rs: exp }));
  };

  const field = (id: string, label: string, value: string, set: (v: string) => void, testId: string, hint: string) => (
    <div className="flex flex-col" style={{ gap: 6, minWidth: 0 }}>
      <label htmlFor={id} className="cp-eyebrow">{label}</label>
      <input id={id} type="number" inputMode="numeric" min={0} value={value} placeholder={hint} disabled={save.isPending} data-testid={testId} onChange={(e) => edit(set)(e.target.value)} style={{ ...fieldStyle, width: "100%" }} />
    </div>
  );

  return (
    <form data-testid="settings-snapshot" onSubmit={submit} className="flex flex-col" style={{ gap: 12 }}>
      <div className="grid" style={{ gridTemplateColumns: "repeat(auto-fit,minmax(min(100%,150px),1fr))", gap: 10 }}>
        {field(ids.age, "Age", age, setAge, "settings-snapshot-age", "Not given")}
        {field(ids.dep, "Dependents", dependents, setDependents, "settings-snapshot-dependents", "0")}
        {field(ids.inc, "Monthly income (₹)", income, setIncome, "settings-snapshot-income", "Not given")}
        {field(ids.exp, "Monthly expenses (₹)", expenses, setExpenses, "settings-snapshot-expenses", "Not given")}
      </div>
      <div className="flex flex-wrap items-center" style={{ gap: 10 }}>
        <Btn type="submit" data-testid="settings-snapshot-save" disabled={save.isPending || !edited}>{save.isPending ? "Saving…" : "Save"}</Btn>
        {save.isSuccess && !edited && <span role="status" data-testid="settings-snapshot-saved" style={{ fontSize: 13, color: "var(--mint)" }}>Saved</span>}
        {current?.updated_at && <span className="cp-mono-note">Last saved {fmtDate(current.updated_at)}</span>}
      </div>
      {problem && <InlineError>{problem}</InlineError>}
      {save.isError && !edited && (
        <span data-testid="settings-snapshot-error"><InlineError>These details weren’t saved ({why(save.error)}).</InlineError></span>
      )}
    </form>
  );
}

export function SnapshotCard() {
  const q = useFinancialSnapshot();
  // Held here so "Saved" and a failure outlive the form's remount after a save.
  const save = useSnapshotUpsert();
  return (
    <Section title="About you">
      <p className="m-0" style={{ paddingBottom: 12, fontSize: 13, lineHeight: 1.55, color: "var(--cp-ink-2)" }}>
        Optional. The Copilot uses your income and expenses when you ask about saving and goals.
      </p>
      <Loaded read={toRead(q)} what="Your details">
        {/* Remount when the stored row changes so the fields show what was saved. */}
        {(snap) => <SnapshotForm key={snap?.updated_at ?? "none"} current={snap} save={save} />}
      </Loaded>
    </Section>
  );
}

// ── privacy: recorded consent choices, conversations ─────────────────────

function consentState(c: Consent): { label: string; tone: Tone; when: string | null } {
  if (c.status === "granted") return { label: "Agreed", tone: "mint", when: c.granted_at };
  if (c.status === "withdrawn") return { label: "Withdrawn", tone: "amber", when: c.withdrawn_at };
  return { label: "No choice recorded", tone: "ink", when: null };
}

function ConversationsRow() {
  const sessions = useChatSessions();
  const clear = useClearConversations();
  const [confirming, setConfirming] = useState(false);

  return (
    <>
      <Loaded read={toRead(sessions)} what="Saved conversations">
        {(list) => (
          <Row
            testId="settings-conversations"
            label="Conversations with the Copilot"
            sub={
              list.length === 0
                ? "None saved."
                // The list endpoint returns the 50 most recent, so 50 means "at least 50".
                : <><span className="cp-num" data-testid="settings-conversations-count">{list.length >= 50 ? "50 or more" : fmtNum(list.length)}</span> saved. They are kept until you delete them.</>
            }
          >
            {!confirming ? (
              <Btn data-testid="settings-conversations-clear" disabled={list.length === 0 || clear.isPending} onClick={() => setConfirming(true)}>Delete all</Btn>
            ) : (
              <>
                <Btn
                  data-testid="settings-conversations-clear-confirm"
                  disabled={clear.isPending}
                  onClick={() => clear.mutate(undefined, { onSettled: () => setConfirming(false) })}
                  style={{ color: "var(--cp-danger)", borderColor: "var(--danger-line)" }}
                >
                  {clear.isPending ? "Deleting…" : "Yes, delete all"}
                </Btn>
                <Btn variant="ghost" disabled={clear.isPending} onClick={() => setConfirming(false)}>Keep</Btn>
              </>
            )}
          </Row>
        )}
      </Loaded>
      {confirming && <p className="m-0" style={{ paddingTop: 6, fontSize: 12, color: "var(--cp-ink-3)" }}>This deletes every saved conversation and cannot be undone.</p>}
      {!clear.isPending && clear.data?.ok === false && (
        <div data-testid="settings-conversations-error" style={{ paddingTop: 8 }}>
          <InlineError>Your conversations weren’t deleted ({why(clear.data.error)}).</InlineError>
        </div>
      )}
      {!clear.isPending && clear.data?.ok === true && <p role="status" data-testid="settings-conversations-cleared" className="m-0" style={{ paddingTop: 8, fontSize: 13, color: "var(--mint)" }}>All saved conversations were deleted.</p>}
    </>
  );
}

export function PrivacyCard() {
  const consents = useConsents();
  return (
    <Section title="Privacy">
      <ConversationsRow />
      <div className="flex flex-col" style={{ gap: 2, paddingTop: 14 }}>
        <span className="cp-eyebrow">Consent choices on record</span>
        <Loaded read={toRead(consents)} what="Consent records">
          {(list) =>
            list.length === 0 ? (
              <div data-testid="settings-consents-empty" style={{ paddingTop: 8 }}><EmptyBlock title="No consent purposes listed" /></div>
            ) : (
              <>
                {list.map((c) => {
                  const s = consentState(c);
                  return (
                    <Row
                      key={c.purpose}
                      testId="settings-consent"
                      label={<span data-testid="settings-consent-title">{c.title}</span>}
                      sub={[c.required ? "Required" : "Optional", s.when ? fmtDate(s.when) : null].filter(Boolean).join(" · ")}
                    >
                      <span data-testid="settings-consent-status"><Pill tone={s.tone}>{s.label}</Pill></span>
                    </Row>
                  );
                })}
              </>
            )
          }
        </Loaded>
      </div>
    </Section>
  );
}

// ── account activity ─────────────────────────────────────────────────────

const ACTIVITY: Record<string, string> = {
  login: "Signed in",
  logout: "Signed out",
  login_failed: "Sign-in failed",
  cas_upload: "Statement uploaded",
  cas_parse_failed: "Statement could not be read",
  portfolio_refresh: "Portfolio refreshed",
  pan_view: "Saved PAN viewed",
  pan_update: "PAN saved",
  pan_delete: "PAN removed",
  consent_grant: "Consent given",
  consent_withdraw: "Consent withdrawn",
  data_export: "Data downloaded",
  data_delete: "Data deleted",
  broker_connect: "Broker connected",
  broker_sync: "Broker account read",
  broker_disconnect: "Broker disconnected",
};

const OUTCOME: Record<string, string> = { denied: "Refused", error: "Failed" };

function ActivityRow({ row }: { row: AuditRow }) {
  const failed = row.outcome !== "success";
  return (
    <Row
      testId="settings-activity-row"
      label={<span data-testid="settings-activity-what">{ACTIVITY[row.action] ?? humaniseTag(row.action)}</span>}
      sub={<span title={fmtDate(row.ts)}>{relTime(row.ts) || fmtDate(row.ts)}</span>}
    >
      {failed && <Pill tone="danger">{OUTCOME[row.outcome] ?? humaniseTag(row.outcome)}</Pill>}
    </Row>
  );
}

const ACTIVITY_SHOWN = 8;

export function ActivityCard() {
  const audit = useAuditTrail();
  return (
    <Section title="Account activity" note="Most recent first">
      <Loaded read={toRead(audit)} what="Account activity">
        {(rows) =>
          rows.length === 0 ? (
            <div data-testid="settings-activity-empty"><EmptyBlock title="Nothing recorded yet" body="Sign-ins, data downloads and broker reads are listed here once they happen." /></div>
          ) : (
            <>
              {rows.slice(0, ACTIVITY_SHOWN).map((r) => <ActivityRow key={r.audit_id} row={r} />)}
              {rows.length > ACTIVITY_SHOWN && (
                <p className="m-0 cp-mono-note" style={{ paddingTop: 10 }}>
                  Showing {ACTIVITY_SHOWN} of the last <span data-testid="settings-activity-count">{fmtNum(rows.length)}</span> recorded
                </p>
              )}
            </>
          )
        }
      </Loaded>
    </Section>
  );
}

// ── diagnostics ──────────────────────────────────────────────────────────

export function DiagnosticsCard() {
  const logging = useSessionLogging();
  return (
    <Section title="Diagnostics">
      <Row
        testId="settings-logging"
        label="Record this session’s logs"
        sub={logging.enabled ? "Recording what this browser and the server log for your session." : "Off. Nothing is recorded until you switch this on."}
      >
        <Switch
          data-testid="settings-logging-switch"
          label="Record this session’s logs"
          checked={logging.enabled}
          disabled={logging.busy}
          onClick={() => void (logging.enabled ? logging.disable() : logging.enable())}
        />
      </Row>
      {logging.error && <div style={{ paddingTop: 8 }}><InlineError>{logging.error}</InlineError></div>}
      <div style={{ paddingTop: 12 }}>
        <Link to="/settings/logs" data-testid="settings-logs-link" style={{ fontSize: 13, color: "var(--mint)" }}>View logs ›</Link>
      </div>
    </Section>
  );
}
