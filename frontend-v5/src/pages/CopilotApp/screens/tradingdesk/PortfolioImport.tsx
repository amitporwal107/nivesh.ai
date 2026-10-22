/**
 * Smart trading desk — Portfolio & risk: import a holdings file with a preview before anything is saved
 * (PRD §8.2, §14.3; backend addition B17). Opened from the Portfolio tab's "Import a portfolio".
 *
 *   POST /api/portfolio/upload/preview               step 1: the file is read and every row validated and flagged —
 *                                                    symbol and ISIN (check digit, mismatch with the NSE list), quantity,
 *                                                    average cost, instrument type, account, currency, import time;
 *                                                    duplicates, mismatched symbols and unsupported instruments are
 *                                                    flagged, never merged. Nothing is saved.   (usePreviewImport)
 *   POST /api/portfolio/upload/preview/{id}/commit   step 2: saves only the rows ticked here     (useCommitImport)
 *
 * Ready rows start ticked, rows to review start unticked, rows the server will not import cannot be ticked. The file
 * type, size, macros and archive expansion are checked on the server before any parser runs.
 */
import { useId, useMemo, useRef, useState, type ReactNode } from "react";
import { Btn, Pill, fmtNum, type Tone } from "../../components/ui";
import { fmtStamp } from "../desk/broker";
import { fmtPrice } from "../trading/parts";
import { useDesk } from "./context";
import { writeProblem } from "./desk-trading";
import { useCommitImport, usePreviewImport, type ImportPreview, type ImportRow, type ImportRowStatus } from "./portfolio-data";
import { TrustLine } from "./trust";

const quiet = { fontSize: 12, lineHeight: 1.55, color: "var(--cp-ink-3)" } as const;
const FILE_TYPES = /\.(csv|xlsx|xls)$/i;

const STATUS: Record<ImportRowStatus, { label: string; investor: string; tone: Tone }> = {
  ready: { label: "Ready", investor: "Looks fine", tone: "mint" },
  review: { label: "Review", investor: "Check this", tone: "amber" },
  rejected: { label: "Not imported", investor: "Can't import", tone: "danger" },
};

function fmtBytes(n: number | null): string {
  if (n == null) return "—";
  return n < 1024 ? `${n} B` : n < 1024 * 1024 ? `${(n / 1024).toFixed(1)} KB` : `${(n / (1024 * 1024)).toFixed(1)} MB`;
}

function RowItem({ r, on, onToggle, investor }: { r: ImportRow; on: boolean; onToggle: () => void; investor: boolean }) {
  const id = useId();
  const st = STATUS[r.status];
  const locked = r.status === "rejected";
  return (
    <li
      data-testid="desk-import-row"
      data-row={r.rowNo}
      data-status={r.status}
      className="flex flex-col"
      style={{ gap: 6, padding: "10px 12px", borderRadius: 10, border: "1px solid var(--cp-line)", background: locked ? "var(--bg-1)" : "var(--bg-2)" }}
    >
      <div className="grid items-start" style={{ gridTemplateColumns: "auto minmax(0,1fr) auto", gap: "4px 10px" }}>
        <input
          id={id}
          type="checkbox"
          data-testid="desk-import-row-include"
          checked={on}
          disabled={locked}
          onChange={onToggle}
          aria-describedby={`${id}-flags`}
          style={{ marginTop: 3 }}
        />
        <label htmlFor={id} className="flex min-w-0 flex-col" style={{ gap: 2, cursor: locked ? "default" : "pointer" }}>
          <span style={{ fontSize: 13, fontWeight: 500, color: "var(--cp-ink)", overflowWrap: "anywhere" }}>
            <span className="cp-num" style={{ color: "var(--cp-ink-3)", fontSize: 11 }}>Row {r.rowNo} · </span>
            {r.name}
          </span>
          <span data-testid="desk-import-row-fields" className="cp-num" style={{ fontSize: 11.5, lineHeight: 1.5, color: "var(--cp-ink-3)", overflowWrap: "anywhere" }}>
            {[
              r.symbol ? `Symbol ${r.symbol}` : "No symbol",
              r.isin ? `ISIN ${r.isin}${r.isinSource === "nse_list" ? " (from the NSE list)" : ""}` : "No ISIN",
              `Exchange ${r.exchange ?? "— not in the file"}`,
              `Qty ${r.quantity != null ? fmtNum(r.quantity, Number.isInteger(r.quantity) ? 0 : 4) : "—"}`,
              `Avg cost ${r.avgCost != null ? fmtPrice(r.avgCost) : "—"}`,
              `Type ${r.instrumentType ? r.instrumentType.replace(/_/g, " ") : "—"}`,
              `Account ${r.accountRef ?? "— none named"}`,
              r.currency ?? "—",
            ].join(" · ")}
          </span>
        </label>
        <span data-testid="desk-import-row-status"><Pill tone={st.tone}>{investor ? st.investor : st.label}</Pill></span>
      </div>
      <ul id={`${id}-flags`} className="m-0 flex flex-col" style={{ gap: 3, padding: "0 0 0 26px", listStyle: "none" }}>
        {r.flags.length === 0 && <li style={{ ...quiet, fontSize: 11.5 }}>No issues found.</li>}
        {r.flags.map((f) => (
          <li key={f.code} data-testid="desk-import-flag" data-code={f.code} data-level={f.level} style={{ fontSize: 11.5, lineHeight: 1.5, color: f.level === "reject" ? "var(--cp-danger)" : f.level === "review" ? "var(--amber)" : "var(--cp-ink-3)" }}>
            <span style={{ fontWeight: 600 }}>{f.level === "reject" ? "Not imported: " : f.level === "review" ? "Check: " : "Note: "}</span>
            {f.text}
          </li>
        ))}
      </ul>
    </li>
  );
}

function PreviewView({ p, onDone, onCancel, investor }: { p: ImportPreview; onDone: (n: number) => void; onCancel: () => void; investor: boolean }) {
  const [chosen, setChosen] = useState<Set<number>>(() => new Set(p.rows.filter((r) => r.include).map((r) => r.rowNo)));
  const [showChecks, setShowChecks] = useState(false);
  const commit = useCommitImport();
  const toggle = (n: number) => setChosen((prev) => {
    const next = new Set(prev);
    if (next.has(n)) next.delete(n); else next.add(n);
    return next;
  });
  const n = chosen.size;
  const done = commit.data;
  return (
    <div data-testid="desk-import-preview-result" className="flex flex-col" style={{ gap: 12 }}>
      <TrustLine
        testId="desk-import-trust"
        source={`Your file · ${p.file.name ?? "upload"}${p.file.brokerName ? ` · read as ${p.file.brokerName}` : ""}`}
        asOf={p.createdAt ? `checked ${fmtStamp(p.createdAt)}` : null}
        maker="rules"
        method="Import checks: symbol, ISIN check digit, quantity, cost, instrument type, duplicates"
      />
      <div className="flex flex-wrap items-baseline" style={{ gap: "4px 14px" }}>
        <span data-testid="desk-import-counts" className="cp-num" style={{ fontSize: 13, color: "var(--cp-ink)" }}>
          {fmtNum(p.counts.rows)} rows · {fmtNum(p.counts.ready)} ready · {fmtNum(p.counts.review)} to review · {fmtNum(p.counts.rejected)} not imported
        </span>
        <span className="cp-mono-note">{p.file.kind?.toUpperCase() ?? "FILE"} · {fmtBytes(p.file.sizeBytes)}{p.file.skippedRows ? ` · ${fmtNum(p.file.skippedRows)} non-holding lines skipped` : ""}</span>
      </div>
      <span data-testid="desk-import-account" style={quiet}>
        {p.accountNote ?? "No account named."} Currency: {p.currency ?? "—"}{p.currencyBasis ? ` (${p.currencyBasis})` : ""}. {p.effectsNote ?? ""}
      </span>
      {!done && (
        <span data-testid="desk-import-nothing-saved" role="status" style={{ fontSize: 12.5, lineHeight: 1.5, padding: "8px 12px", borderRadius: 10, border: "1px solid var(--amber-line)", background: "var(--amber-soft)", color: "var(--cp-ink)" }}>
          Nothing has been saved yet. Tick the rows to import, then confirm. Duplicates and mismatches are not merged: a ticked duplicate is added as its own row.
        </span>
      )}
      <ul className="m-0 flex flex-col" style={{ gap: 6, padding: 0, listStyle: "none" }}>
        {p.rows.map((r) => <RowItem key={r.rowNo} r={r} on={chosen.has(r.rowNo)} onToggle={() => toggle(r.rowNo)} investor={investor} />)}
      </ul>
      <div className="flex flex-col" style={{ gap: 4 }}>
        <button
          type="button"
          data-testid="desk-import-checks-toggle"
          aria-expanded={showChecks}
          onClick={() => setShowChecks(!showChecks)}
          className="self-start"
          style={{ padding: 0, border: 0, background: "none", cursor: "pointer", fontSize: 11.5, color: "var(--mint)" }}
        >
          {showChecks ? "Hide the file checks" : "File checks ›"}
        </button>
        {showChecks && (
          <ul data-testid="desk-import-checks" className="m-0 flex flex-col" style={{ gap: 2, paddingLeft: 16 }}>
            {p.checks.map((c) => <li key={c} style={{ ...quiet, fontSize: 11.5 }}>{c}</li>)}
          </ul>
        )}
      </div>
      {done ? (
        <div data-testid="desk-import-done" role="status" style={{ fontSize: 13, lineHeight: 1.5, padding: "10px 12px", borderRadius: 12, border: "1px solid var(--mint-line)", background: "var(--mint-soft)" }}>
          {fmtNum(done.count)} {done.count === 1 ? "holding" : "holdings"} imported (rows {done.committedRows.join(", ")}).
          {done.leftOutRows.length ? ` Left out: rows ${done.leftOutRows.join(", ")}.` : ""} Your portfolio figures are refreshed.
        </div>
      ) : (
        <div className="flex flex-wrap items-center" style={{ gap: 8 }}>
          <Btn
            variant="primary"
            data-testid="desk-import-commit"
            disabled={n === 0 || commit.isPending}
            onClick={() => commit.mutate({ id: p.id, rows: [...chosen].sort((a, b) => a - b) }, { onSuccess: (r) => onDone(r.count) })}
          >
            {commit.isPending ? "Importing…" : n === 0 ? "No rows ticked" : `Import ${fmtNum(n)} ${n === 1 ? "row" : "rows"}`}
          </Btn>
          <Btn variant="ghost" data-testid="desk-import-cancel" disabled={commit.isPending} onClick={onCancel}>Cancel</Btn>
          {p.expiresAt && <span className="cp-mono-note">Preview kept until {fmtStamp(p.expiresAt)}</span>}
        </div>
      )}
      {commit.isError && <span data-testid="desk-import-commit-error" role="alert" style={{ fontSize: 12.5, color: "var(--cp-danger)" }}>{writeProblem(commit.error)}</span>}
    </div>
  );
}

export function PortfolioImport({ onClose }: { onClose: () => void }) {
  const { persona } = useDesk();
  const investor = persona === "investor";
  const fileRef = useRef<HTMLInputElement>(null);
  const hintId = useId();
  const [file, setFile] = useState<File | null>(null);
  const preview = usePreviewImport();
  const wrongType = !!file && !FILE_TYPES.test(file.name);
  const result = useMemo(() => preview.data ?? null, [preview.data]);
  let body: ReactNode;
  if (result) {
    body = <PreviewView key={result.id} p={result} investor={investor} onDone={() => undefined} onCancel={() => { preview.reset(); setFile(null); }} />;
  } else {
    body = (
      <div className="flex flex-col" style={{ gap: 10 }}>
        <div className="flex flex-wrap items-center" style={{ gap: 10 }}>
          <input
            ref={fileRef}
            type="file"
            accept=".csv,.xlsx,.xls,text/csv,application/vnd.openxmlformats-officedocument.spreadsheetml.sheet,application/vnd.ms-excel"
            hidden
            aria-label="Holdings file: .csv, .xlsx or .xls"
            aria-describedby={hintId}
            data-testid="desk-import-file"
            onChange={(e) => { setFile(e.target.files?.[0] ?? null); preview.reset(); }}
          />
          <Btn data-testid="desk-import-choose" disabled={preview.isPending} onClick={() => fileRef.current?.click()}>
            {file ? "Choose another file" : "Choose a holdings file"}
          </Btn>
          {file ? (
            <span className="flex flex-wrap items-center" style={{ gap: 8, fontSize: 13, minWidth: 0 }}>
              <span data-testid="desk-import-file-name" style={{ overflowWrap: "anywhere" }}>{file.name}</span>
              <span className="cp-mono-note">{fmtBytes(file.size)}</span>
            </span>
          ) : (
            <span className="cp-mono-note">CSV · XLSX · XLS · up to 5 MB</span>
          )}
        </div>
        <span id={hintId} style={quiet}>
          Your broker’s holdings download (Zerodha, Groww, Upstox, Angel One, ICICI Direct, HDFC Securities, Kotak, Dhan, 5paisa,
          MF Central) or any sheet with a name and a quantity column. Nivesh checks every row first and shows you what it found;
          nothing is saved until you confirm. A CAS statement PDF is imported from Broker connections instead.
        </span>
        <div className="flex flex-wrap items-center" style={{ gap: 8 }}>
          <Btn variant="primary" data-testid="desk-import-preview" disabled={!file || wrongType || preview.isPending} onClick={() => file && preview.mutate(file)}>
            {preview.isPending ? "Checking the file…" : "Check the file"}
          </Btn>
          <Btn variant="ghost" data-testid="desk-import-close" onClick={onClose}>Close</Btn>
        </div>
        {wrongType && <span data-testid="desk-import-type" role="alert" style={{ fontSize: 12.5, color: "var(--cp-danger)" }}>Choose a .csv, .xlsx or .xls file.</span>}
        {preview.isError && <span data-testid="desk-import-error" role="alert" style={{ fontSize: 12.5, lineHeight: 1.5, color: "var(--cp-danger)" }}>The file was not read: {writeProblem(preview.error)}</span>}
      </div>
    );
  }
  return <div data-testid="desk-portfolio-import" className="flex min-w-0 flex-col" style={{ gap: 12 }}>{body}</div>;
}
