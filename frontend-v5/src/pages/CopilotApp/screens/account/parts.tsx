/**
 * Account screens — pieces shared by Get started, Broker connections and
 * Settings: small controls, the CAS statement upload, the broker file upload
 * (.xlsx / .xls / .csv), the Gmail source card and the risk / goal wizard.
 * Broker accounts and broker sign-in are in ./brokers.
 *
 * Statement upload, Gmail import and the wizard reuse what the app already has
 * (useCasUpload, GmailSyncModal, ProfileWizardModal); the broker file goes
 * through useHoldingsFileUpload (./queries). Nothing here speaks to an upload
 * or OAuth endpoint directly.
 */
import { useId, useRef, useState, type ButtonHTMLAttributes, type CSSProperties, type FormEvent, type ReactNode } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { useCasUpload } from "@/hooks/use-cas-upload";
import { useGmailAutoImportToggle, useGmailDisconnect } from "@/hooks/use-gmail";
import { useGoals } from "@/hooks/use-goals";
import { GmailSyncModal } from "@/pages/Dashboard/GmailSyncModal";
import { ProfileWizardModal } from "@/pages/Dashboard/ProfileWizardModal";
import type { RiskCategory, RiskProfile } from "@/hooks/use-risk-profile";
import type { CasUploadResult } from "@/services/adapters/cas-upload.adapter";
import { ApiError } from "@/services/api/errors";
import { BrokerIcon } from "../../components/EntityIcon";
import { Btn, ErrorBlock, LoadingBlock, Pill, errorSentence, fmtDate, fmtNum, relTime } from "../../components/ui";
import { EXPORT_BROKERS, accountKeys, toRead, useAfterImport, useGmailSourceStatus, useHoldingsFileUpload, useOnboardingState, useRiskProfileRead, type RiskProfileView } from "./queries";

export function errorText(e: unknown, fallback = "Something went wrong. Try again."): string {
  return e instanceof Error && typeof e.message === "string" && e.message ? e.message : fallback;
}

export const fieldStyle: CSSProperties = {
  padding: "11px 14px",
  borderRadius: 10,
  border: "1px solid var(--line-2)",
  background: "var(--bg-2)",
  color: "var(--cp-ink)",
  fontFamily: "var(--mono)",
  fontSize: 14,
  minWidth: 0,
};

const SELECTED: CSSProperties = { borderColor: "var(--mint-line)", color: "var(--mint)", background: "var(--mint-soft)" };

// ── small controls ───────────────────────────────────────────────────────

export function InlineError({ children }: { children: ReactNode }) {
  return <span role="alert" style={{ fontSize: 12, lineHeight: 1.5, color: "var(--cp-danger)", overflowWrap: "anywhere" }}>{children}</span>;
}

/** A button that reads as a text link (skip, back, add). */
export function LinkButton({ tone = "quiet", disabled, ...rest }: ButtonHTMLAttributes<HTMLButtonElement> & { tone?: "quiet" | "mint" }) {
  return (
    <button
      type="button"
      {...rest}
      disabled={disabled}
      style={{ fontFamily: "var(--sans)", fontSize: 13, color: tone === "mint" ? "var(--mint)" : "var(--cp-ink-2)", background: "none", border: 0, padding: "4px 0", textAlign: "left", cursor: disabled ? "not-allowed" : "pointer", opacity: disabled ? 0.5 : 1 }}
    />
  );
}

/** Pill-shaped option in a pick-one group. */
export function ToggleChip({ on, ...rest }: ButtonHTMLAttributes<HTMLButtonElement> & { on: boolean }) {
  return <button type="button" {...rest} aria-pressed={on} className="cp-chip" style={on ? SELECTED : undefined} />;
}

/** Card-sized option in a pick-one group. */
export function ChoiceCard({ on, title, body, ...rest }: Omit<ButtonHTMLAttributes<HTMLButtonElement>, "title"> & { on: boolean; title: ReactNode; body: ReactNode }) {
  return (
    <button
      type="button"
      {...rest}
      aria-pressed={on}
      className="flex flex-col text-left"
      style={{ gap: 8, padding: 18, borderRadius: 14, cursor: "pointer", background: "var(--bg-1)", border: `1px solid ${on ? "var(--mint-line)" : "var(--cp-line)"}`, color: "var(--cp-ink)", fontFamily: "var(--sans)" }}
    >
      <span className="flex flex-wrap items-center justify-between" style={{ gap: 8, fontSize: 16, fontWeight: 500 }}>
        {title}
        {on && <span className="cp-mono-note" style={{ color: "var(--mint)" }}>Selected</span>}
      </span>
      <span style={{ fontSize: 13, lineHeight: 1.5, color: "var(--cp-ink-3)" }}>{body}</span>
    </button>
  );
}

export function Switch({ checked, label, disabled, ...rest }: Omit<ButtonHTMLAttributes<HTMLButtonElement>, "role"> & { checked: boolean; label: string }) {
  return (
    <button
      type="button"
      {...rest}
      role="switch"
      aria-checked={checked}
      aria-label={label}
      disabled={disabled}
      style={{ position: "relative", flex: "none", width: 40, height: 24, padding: 0, borderRadius: 999, border: "1px solid var(--line-2)", background: checked ? "var(--mint)" : "var(--bg-3)", cursor: disabled ? "not-allowed" : "pointer", opacity: disabled ? 0.5 : 1 }}
    >
      <span aria-hidden style={{ position: "absolute", top: 2, left: checked ? 18 : 2, width: 18, height: 18, borderRadius: "50%", background: checked ? "var(--bg-1)" : "var(--cp-ink-3)", transition: "left .15s ease" }} />
    </button>
  );
}

/** One line of a settings-style list: label and note at the left, value or controls at the right. */
export function Row({ label, sub, children, testId }: { label: ReactNode; sub?: ReactNode; children?: ReactNode; testId?: string }) {
  return (
    <div data-testid={testId} className="flex flex-wrap items-center justify-between" style={{ gap: "8px 12px", padding: "10px 0", borderBottom: "1px solid var(--cp-line)" }}>
      <div className="flex flex-col" style={{ gap: 2, minWidth: 0, flex: "1 1 180px" }}>
        <span style={{ fontSize: 14 }}>{label}</span>
        {sub != null && <span style={{ fontSize: 12, lineHeight: 1.5, color: "var(--cp-ink-3)", overflowWrap: "anywhere" }}>{sub}</span>}
      </div>
      {children != null && <div className="flex flex-wrap items-center" style={{ gap: 8 }}>{children}</div>}
    </div>
  );
}

function fmtBytes(n: number): string {
  if (n >= 1_048_576) return `${(n / 1_048_576).toFixed(1)} MB`;
  return `${Math.max(1, Math.round(n / 1024))} KB`;
}

/**
 * Whole years from today to a goal's target date. useGoals derives that date
 * as "today + horizon_years", so this gives back the stored horizon.
 */
export function goalHorizonYears(targetDate: string): number | null {
  const year = new Date(targetDate).getFullYear();
  if (!Number.isFinite(year)) return null;
  const years = year - new Date().getFullYear();
  return years > 0 ? years : null;
}

/** "Assessed 20 May 2026", or "" when the profile carries no date. */
export function riskAssessed(p: RiskProfileView): string {
  return p.assessedAt ? `Assessed ${fmtDate(p.assessedAt)}` : "";
}

// ── CAS statement upload ─────────────────────────────────────────────────

/**
 * Upload a CAS PDF (NSDL / CDSL / CAMS / KFintech) through useCasUpload →
 * POST /api/onboarding/upload-cas. The PAN or statement password lives in this
 * component's state only while the form is open and is cleared once the
 * import succeeds.
 */
export function StatementUpload({ panOnFile, onImported }: {
  /** A PAN is already saved, so the password field may be left empty. */
  panOnFile: boolean;
  onImported?: (result: CasUploadResult) => void;
}) {
  const cas = useCasUpload();
  const afterImport = useAfterImport();
  const fileRef = useRef<HTMLInputElement>(null);
  const secretId = useId();
  const hintId = useId();
  const [file, setFile] = useState<File | null>(null);
  const [secret, setSecret] = useState("");
  // Hide the last outcome once the form is changed, so an old error or result
  // is never read as belonging to the new file.
  const [edited, setEdited] = useState(false);

  const canSubmit = !!file && !cas.isUploading && (secret.trim().length > 0 || panOnFile);

  const submit = (e: FormEvent) => {
    e.preventDefault();
    if (!file || !canSubmit) return;
    setEdited(false);
    cas.upload(
      { file, password: secret.trim() || undefined },
      {
        onSuccess: (result) => {
          setSecret("");
          afterImport();
          onImported?.(result);
        },
      },
    );
  };

  const result = !edited && !cas.isUploading ? cas.result : undefined;
  const error = !edited && !cas.isUploading ? cas.error : null;
  // The adapter turns a missing count into 0, so 0 is "nothing imported", not a success.
  const imported = result && Number.isFinite(result.imported_holdings) ? result.imported_holdings : 0;
  const period = result && typeof result.statement_period === "string" ? result.statement_period : "";

  return (
    <form data-testid="cas-upload" onSubmit={submit} className="cp-card flex flex-col" style={{ gap: 14, padding: 18 }}>
      <div className="flex flex-wrap items-center" style={{ gap: 10 }}>
        <input
          ref={fileRef}
          type="file"
          accept="application/pdf,.pdf"
          hidden
          aria-label="CAS statement PDF"
          data-testid="cas-file"
          onChange={(e) => { setFile(e.target.files?.[0] ?? null); setEdited(true); }}
        />
        <Btn data-testid="cas-choose" disabled={cas.isUploading} onClick={() => fileRef.current?.click()}>
          {file ? "Choose another PDF" : "Choose CAS PDF"}
        </Btn>
        {file ? (
          <span className="flex flex-wrap items-center" style={{ gap: 8, fontSize: 13, minWidth: 0 }}>
            <span style={{ fontFamily: "var(--mono)", fontSize: 10, padding: "3px 6px", borderRadius: 4, background: "var(--cp-danger-soft)", color: "var(--cp-danger)" }}>PDF</span>
            <span data-testid="cas-file-name" style={{ overflowWrap: "anywhere" }}>{file.name}</span>
            <span className="cp-mono-note">{fmtBytes(file.size)}</span>
          </span>
        ) : (
          <span className="cp-mono-note">NSDL · CDSL · CAMS · KFintech · PDF up to 25 MB</span>
        )}
      </div>

      <div className="flex flex-col" style={{ gap: 6 }}>
        <label htmlFor={secretId} className="cp-eyebrow">PAN or statement password</label>
        <div className="flex flex-wrap" style={{ gap: 8 }}>
          <input
            id={secretId}
            type="password"
            autoComplete="off"
            spellCheck={false}
            value={secret}
            disabled={cas.isUploading}
            aria-describedby={hintId}
            data-testid="cas-password"
            placeholder={panOnFile ? "Leave empty to use the PAN on file" : "Usually your PAN in capitals"}
            onChange={(e) => { setSecret(e.target.value); setEdited(true); }}
            style={{ ...fieldStyle, flex: "1 1 220px" }}
          />
          <Btn type="submit" variant="primary" data-testid="cas-submit" disabled={!canSubmit}>
            {cas.isUploading ? "Reading statement…" : "Unlock and import"}
          </Btn>
        </div>
        <span id={hintId} style={{ fontSize: 12, lineHeight: 1.5, color: "var(--cp-ink-3)" }}>
          CAS PDFs are locked, usually with your PAN. It is sent with the file to open it and saved on your profile, so later statements open without asking again.
        </span>
      </div>

      {cas.isUploading && <span role="status" className="cp-mono-note cp-running">Opening the PDF and reading holdings</span>}
      {error && <InlineError>{errorText(error, "This statement could not be imported.")}</InlineError>}
      {result && imported > 0 && (
        <div role="status" data-testid="cas-result" style={{ padding: "12px 14px", borderRadius: 12, border: "1px solid var(--mint-line)", background: "var(--mint-soft)", fontSize: 14, lineHeight: 1.5 }}>
          <span className="cp-num" data-testid="cas-imported-count">{fmtNum(imported)}</span> holdings imported
          {period ? <> · statement period <span data-testid="cas-statement-period">{period}</span></> : null}
          . They replace what was on file from earlier statements and plain sheets. Holdings read from a broker are kept.
        </div>
      )}
      {result && imported === 0 && (
        <div role="status" data-testid="cas-result-empty" style={{ padding: "12px 14px", borderRadius: 12, border: "1px solid var(--amber-line)", background: "var(--amber-soft)", fontSize: 14, lineHeight: 1.5 }}>
          The server answered, but reported no holdings imported from this file.
        </div>
      )}
    </form>
  );
}

// ── broker holdings file (.xlsx / .xls / .csv) ───────────────────────────

const FILE_TYPES = /\.(xlsx|xls|csv)$/i;
const EXPORT_NAMES = Object.values(EXPORT_BROKERS);

/**
 * Why a file was not imported. A 400 carries the server's own message, written
 * for the person uploading (which columns it looked for, or that the file could
 * not be opened); every other failure is said in this app's words.
 */
function fileFailure(e: unknown): string {
  const lead = "This file was not imported";
  if (e instanceof ApiError) {
    if (e.status === 400 && e.detail) return `${lead}. ${e.detail}`;
    if (e.status === 410) return `${lead}: a PDF statement is imported under CAS statement, not here.`;
    if (e.status === 413) return `${lead}: it is too large.`;
    if (e.status === 415) return `${lead}: it is not a readable .xlsx, .xls or .csv file.`;
    if (e.status === 422) return `${lead}: the server’s safety check rejected it.`;
  }
  return `${lead}: ${errorSentence(e) || "the request failed"}.`;
}

const noteStyle: CSSProperties = { padding: "12px 14px", borderRadius: 12, fontSize: 14, lineHeight: 1.5 };
const doneStyle: CSSProperties = { ...noteStyle, border: "1px solid var(--mint-line)", background: "var(--mint-soft)" };
const nothingStyle: CSSProperties = { ...noteStyle, border: "1px solid var(--amber-line)", background: "var(--amber-soft)" };

/**
 * Upload the holdings file a broker lets its customers download, or any sheet
 * with a name and a quantity column → POST /api/portfolio/upload
 * (useHoldingsFileUpload). The server saves the rows as it reads them, so the
 * form says what will happen before the file is sent and what the server made
 * of it afterwards.
 */
export function HoldingsFileUpload({ broker, onImported }: {
  /** The broker the user chose this route for; names it in the form. */
  broker?: string | null;
  onImported?: (count: number) => void;
}) {
  const upload = useHoldingsFileUpload();
  const afterImport = useAfterImport();
  const fileRef = useRef<HTMLInputElement>(null);
  const hintId = useId();
  const [file, setFile] = useState<File | null>(null);
  // Hide the last outcome once another file is chosen.
  const [edited, setEdited] = useState(false);

  const wrongType = !!file && !FILE_TYPES.test(file.name);

  const submit = (e: FormEvent) => {
    e.preventDefault();
    if (!file || wrongType || upload.isPending) return;
    setEdited(false);
    upload.mutate(file, {
      onSuccess: (done) => {
        if (!done.ok) return;
        afterImport();
        if (done.value.count > 0) onImported?.(done.value.count);
      },
    });
  };

  const outcome = !edited && !upload.isPending ? upload.data : undefined;
  const read = outcome?.ok ? outcome.value : null;
  // A broker's own export: the server names the broker it recognised.
  const from = read ? read.broker_name ?? (read.broker ? EXPORT_BROKERS[read.broker] ?? null : null) : null;
  const holdings = read ? <><span className="cp-num" data-testid="holdings-file-count">{fmtNum(read.count)}</span> {read.count === 1 ? "holding" : "holdings"}</> : null;

  return (
    <form data-testid="holdings-file-upload" onSubmit={submit} className="cp-card flex flex-col" style={{ gap: 14, padding: 18 }}>
      <div className="flex flex-wrap items-center" style={{ gap: 10 }}>
        <input
          ref={fileRef}
          type="file"
          accept=".xlsx,.xls,.csv,text/csv,application/vnd.openxmlformats-officedocument.spreadsheetml.sheet,application/vnd.ms-excel"
          hidden
          aria-label="Holdings file: .xlsx, .xls or .csv"
          aria-describedby={hintId}
          data-testid="holdings-file"
          onChange={(e) => { setFile(e.target.files?.[0] ?? null); setEdited(true); }}
        />
        <Btn data-testid="holdings-file-choose" disabled={upload.isPending} onClick={() => fileRef.current?.click()}>
          {file ? "Choose another file" : "Choose a holdings file"}
        </Btn>
        {file ? (
          <span className="flex flex-wrap items-center" style={{ gap: 8, fontSize: 13, minWidth: 0 }}>
            <span data-testid="holdings-file-name" style={{ overflowWrap: "anywhere" }}>{file.name}</span>
            <span className="cp-mono-note">{fmtBytes(file.size)}</span>
          </span>
        ) : (
          <span className="cp-mono-note">XLSX · XLS · CSV</span>
        )}
      </div>

      {broker && (
        <span data-testid="holdings-file-for" style={{ fontSize: 14, lineHeight: 1.5 }}>
          Download your holdings from {broker} as an Excel or CSV file, then choose it here.
        </span>
      )}
      <span id={hintId} data-testid="holdings-file-recognised" style={{ fontSize: 12, lineHeight: 1.55, color: "var(--cp-ink-3)" }}>
        Read as downloaded from {EXPORT_NAMES.slice(0, -1).join(", ")} and {EXPORT_NAMES[EXPORT_NAMES.length - 1]}. Any other sheet needs a heading row with a Name and a Quantity column; Symbol or ISIN, Buy price, Current price, Type, Sector and Buy date are read when present.
      </span>
      <span data-testid="holdings-file-warning" style={{ fontSize: 13, lineHeight: 1.55, color: "var(--cp-ink-2)", padding: "10px 12px", borderRadius: 12, border: "1px solid var(--amber-line)", background: "var(--amber-soft)" }}>
        Rows are saved as soon as the file is read; there is no preview. A new file from the same broker replaces that broker’s earlier file. Any other sheet is added to what is on file, so uploading it twice adds its rows twice.
      </span>

      <div>
        <Btn type="submit" variant="primary" data-testid="holdings-file-submit" disabled={!file || wrongType || upload.isPending}>
          {upload.isPending ? "Reading the file…" : "Add these holdings"}
        </Btn>
      </div>

      {wrongType && (
        <span data-testid="holdings-file-type">
          <InlineError>
            This file can’t be read here. Choose an .xlsx, .xls or .csv file.{/\.pdf$/i.test(file.name) ? " A CAS PDF is imported under CAS statement." : ""}
          </InlineError>
        </span>
      )}
      {outcome?.ok === false && <span data-testid="holdings-file-error"><InlineError>{fileFailure(outcome.error)}</InlineError></span>}
      {read && read.count > 0 && from && (
        <div role="status" data-testid="holdings-file-result" data-format={read.format ?? ""} style={doneStyle}>
          {holdings} added from your <span data-testid="holdings-file-broker">{from}</span> file. Any earlier {from} file is replaced.
        </div>
      )}
      {read && read.count > 0 && !from && (
        <div role="status" data-testid="holdings-file-result" data-format={read.format ?? ""} style={doneStyle}>
          {holdings} added without a broker
          {read.format === "unidentified" ? ": Nivesh could not tell which broker this file came from" : read.format === "generic" ? ": the file was read as a plain sheet" : ""}
          . Nothing on file was replaced.
        </div>
      )}
      {read && read.count === 0 && (
        <div role="status" data-testid="holdings-file-result-empty" data-format={read.format ?? ""} style={nothingStyle}>
          {from
            ? <>The file was read as coming from <span data-testid="holdings-file-broker">{from}</span>, but no holdings were added. A holding already read from a connected {from} account is not added again.</>
            : "The server read the file but found no holdings in it."}
        </div>
      )}
    </form>
  );
}

// ── Gmail (CAS emails) ───────────────────────────────────────────────────

/**
 * Gmail as a statement source: real status from GET /api/gmail/status, the
 * existing GmailSyncModal for connect + import, and the existing toggle and
 * disconnect mutations.
 */
export function GmailSource({ onImported }: { onImported?: () => void }) {
  const qc = useQueryClient();
  const status = useGmailSourceStatus();
  const state = useOnboardingState();
  const toggle = useGmailAutoImportToggle();
  const disconnect = useGmailDisconnect();
  const afterImport = useAfterImport();
  const [modalOpen, setModalOpen] = useState(false);
  const [confirming, setConfirming] = useState(false);

  if (status.state === "loading") return <LoadingBlock label="Loading Gmail status" rows={2} />;
  if (status.state === "error") return <ErrorBlock title="Gmail status didn’t load" error={status.error} onRetry={status.retry} />;

  const g = status.data;
  const connected = g.connected;
  const last = g.last_import;

  return (
    <div data-testid="gmail-source" className="cp-card-raised flex flex-col" style={{ gap: 12, padding: "16px 18px" }}>
      <div className="flex flex-wrap items-center" style={{ gap: "10px 14px" }}>
        <BrokerIcon name="Gmail" size={38} />
        <div className="flex flex-col" style={{ flex: "1 1 200px", gap: 2, minWidth: 0 }}>
          <span style={{ fontSize: 15, fontWeight: 500 }}>Gmail · CAS emails</span>
          <span className="cp-mono-note" data-testid="gmail-meta" style={{ overflowWrap: "anywhere" }}>
            {connected
              ? [
                  g.connected_at ? `Connected ${fmtDate(g.connected_at)}` : null,
                  last?.imported_at ? `Last import ${relTime(last.imported_at)}${last.count != null ? ` · ${fmtNum(last.count)} holdings` : ""}` : "No import yet",
                ].filter(Boolean).join(" · ")
              : "Read-only access"}
          </span>
        </div>
        <span data-testid="gmail-status"><Pill tone={connected ? "mint" : "ink"}>{connected ? "Connected" : "Not connected"}</Pill></span>
      </div>

      <span style={{ fontSize: 13, lineHeight: 1.55, color: "var(--cp-ink-2)", maxWidth: 640 }}>
        Nivesh finds your latest CAS email, opens the PDF with your PAN and imports the holdings. Access is read-only, and it searches only for emails with a PDF attachment from NSDL, CDSL, CAMS or KFintech.
      </span>

      {connected && last?.filename && (
        <span style={{ fontSize: 12, color: "var(--cp-ink-3)", overflowWrap: "anywhere" }}>
          Last file: <span data-testid="gmail-last-file">{last.filename}</span>
        </span>
      )}

      {connected && (
        g.auto_import_ready ? (
          <div className="flex flex-wrap items-center justify-between" style={{ gap: "8px 12px", padding: "10px 12px", borderRadius: 12, background: "var(--bg-2)" }}>
            <div className="flex flex-col" style={{ gap: 2, flex: "1 1 200px", minWidth: 0 }}>
              <span style={{ fontSize: 13 }}>Import new statements automatically</span>
              <span style={{ fontSize: 12, color: "var(--cp-ink-3)" }}>
                Checked on the 1st of each month.
                {g.last_auto_import_at ? ` Last run ${fmtDate(g.last_auto_import_at)}.` : ""}
              </span>
            </div>
            <Switch
              data-testid="gmail-auto-import"
              label="Import new statements automatically"
              checked={g.auto_import_enabled}
              disabled={toggle.isPending}
              onClick={() => toggle.mutate(!g.auto_import_enabled)}
            />
          </div>
        ) : (
          <span style={{ fontSize: 12, lineHeight: 1.5, color: "var(--cp-ink-3)" }}>
            Automatic import turns on after your first import, once your PAN is saved.
          </span>
        )
      )}
      {toggle.isError && <InlineError>Couldn’t change automatic import. {errorText(toggle.error, "")}</InlineError>}

      <div className="flex flex-wrap items-center" style={{ gap: 8 }}>
        <Btn variant="primary" data-testid={connected ? "gmail-import" : "gmail-connect"} onClick={() => setModalOpen(true)}>
          {connected ? "Import latest statement" : "Connect Gmail"}
        </Btn>
        {connected && !confirming && (
          <Btn data-testid="gmail-disconnect" disabled={disconnect.isPending} onClick={() => setConfirming(true)}>Disconnect</Btn>
        )}
        {connected && confirming && (
          <>
            <span style={{ fontSize: 13, color: "var(--cp-ink-2)" }}>Disconnect Gmail? Automatic imports stop.</span>
            <Btn
              data-testid="gmail-disconnect-confirm"
              disabled={disconnect.isPending}
              onClick={() => disconnect.mutate(undefined, { onSettled: () => setConfirming(false) })}
              style={{ color: "var(--cp-danger)", borderColor: "var(--danger-line)" }}
            >
              {disconnect.isPending ? "Disconnecting…" : "Yes, disconnect"}
            </Btn>
            <Btn variant="ghost" disabled={disconnect.isPending} onClick={() => setConfirming(false)}>Keep</Btn>
          </>
        )}
      </div>
      {disconnect.isError && <InlineError>Couldn’t disconnect Gmail. {errorText(disconnect.error, "")}</InlineError>}

      <GmailSyncModal
        open={modalOpen}
        onClose={() => { setModalOpen(false); void qc.invalidateQueries({ queryKey: ["gmail", "status"] }); }}
        gmailConnected={connected}
        panOnFile={state.data?.pan_on_file ?? false}
        onImported={() => { afterImport(); onImported?.(); }}
      />
    </div>
  );
}

// ── risk profile + goal wizard ───────────────────────────────────────────

/**
 * The existing ProfileWizardModal, opened on one step at a time: the risk
 * assessment (POST /api/user/risk-profile) or "add a goal" (POST /api/goals).
 * Returns the risk-profile read and the goals query it depends on, so a screen
 * reads each once.
 */
export function useProfileWizard() {
  const qc = useQueryClient();
  const risk = toRead(useRiskProfileRead());
  const goals = useGoals();
  const [step, setStep] = useState<0 | 1 | null>(null);
  const profile = risk.state === "ready" ? risk.data : null;
  // The questionnaire pre-fills from an id → answer map. Profiles written by the
  // chat risk flow have none, so for those it opens blank.
  const prefill: RiskProfile | null = profile?.answers && profile.score != null
    ? { category: profile.category as RiskCategory, score: profile.score, answers: profile.answers }
    : null;

  const element = (
    <ProfileWizardModal
      open={step !== null}
      startStep={step ?? 0}
      lastStep={step ?? 0}
      completeness={{ hasRiskProfile: !!profile, hasGoal: (goals.data?.goals.length ?? 0) > 0, hasSnapshot: false }}
      existingProfile={prefill}
      onClose={() => setStep(null)}
      onComplete={() => {
        setStep(null);
        const keys: ReadonlyArray<readonly string[]> = [["user", "risk-profile"], ["goals"], ["plans"], ["onboarding", "state"], accountKeys.onboardingState];
        for (const queryKey of keys) void qc.invalidateQueries({ queryKey });
      }}
    />
  );

  return { risk, goals, openRisk: () => setStep(0), openGoal: () => setStep(1), element };
}
