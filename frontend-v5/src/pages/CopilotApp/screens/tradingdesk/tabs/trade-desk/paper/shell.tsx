/**
 * Paper Trading v2 — the shell shown above every Paper Trading view (the owner's design of 5 Nov 2026; UI_DESIGN_V2.md §1):
 *
 *   status strip   ● Live · paper · Market open · HH:MM IST · Data fresh · 1.2s (amber over 10 s, danger when the feed is
 *                  down) · Policy vN · right-aligned Kill switch · ACTIVE (mint) / Trading halted (danger)
 *                  — GET /api/v1/paper/overview `status` (api-a.ts usePaperOverview; the same read as 01 Overview)
 *   account card   "Account · Mode": the paper account, its starting capital and the SPT mode pill — GET /api/v1/paper/accounts
 *   mode chooser   the pill opens off / tracking / approval / auto (Auto asks to confirm); PUT …/accounts/{id}/config
 *                  {mode, expected_version}. The only mode control: the old Settings screen is gone.
 *
 * Nothing is invented: a state that could not be read is said with the reason. Paper only; nothing reaches a broker.
 */
import { useState } from "react";
import { fmtINR } from "../../../../../components/ui";
import { useCopilotShell } from "../../../../../lib/shell-context";
import { linkBtn } from "../parts";
import { istClock, useNow } from "../pnl-ui";
import { MODES, MODE_WORDS, sptProblem, usePutConfig, type SptMode } from "../spt-api";
import { btn, btnPrimary } from "../spt-parts";
import { usePaperOverview, type PaperAccount, type PaperStatus } from "./api-a";
import { Eyebrow, NUM, Pill, mono10, type PillTone } from "./ui";
import type { UseQueryResult } from "@tanstack/react-query";

const MODE_TONE: Record<SptMode, PillTone> = { off: "plain", tracking: "indigo", approval: "mint", auto: "amber" };

/** "1.2s", "42s", "4m 05s", "3h 10m". */
export function ageText(s: number): string {
  if (s < 10) return `${s.toFixed(1)}s`;
  if (s < 60) return `${Math.round(s)}s`;
  if (s < 3600) return `${Math.floor(s / 60)}m ${String(Math.round(s % 60)).padStart(2, "0")}s`;
  return `${Math.floor(s / 3600)}h ${String(Math.floor((s % 3600) / 60)).padStart(2, "0")}m`;
}

/** "Policy v7" for a number, the version as sent otherwise. */
export const policyText = (v: string | null) => (v == null ? "Policy —" : /^\d+$/.test(v) ? `Policy v${v}` : `Policy ${v}`);

/** The data-age pill: danger when the feed is down, amber over 10 s, plain when the market is closed, else mint. `age` is
 *  shown in lower case ("1.2s") inside the uppercase pill. */
export function freshness(s: PaperStatus): { text: string; age: string | null; tone: PillTone } {
  if (s.feedState === "down") return { text: "Feed down", age: null, tone: "danger" };
  if (s.feedState === "closed") return { text: "Feed closed", age: s.lastTickAgeS == null ? null : `last tick ${ageText(s.lastTickAgeS)} ago`, tone: "plain" };
  if (s.lastTickAgeS == null) return { text: "Data age unknown", age: null, tone: "amber" };
  if (s.lastTickAgeS > 10) return { text: "Data stale", age: ageText(s.lastTickAgeS), tone: "amber" };
  return { text: "Data fresh", age: ageText(s.lastTickAgeS), tone: "mint" };
}

const lower = { textTransform: "none" as const };

function StatusStrip({ q }: { q: ReturnType<typeof usePaperOverview> }) {
  const now = useNow(15_000);
  const s = q.data?.status ?? null;
  if (q.isPending) return <span data-testid="pv2-status" data-state="loading" style={{ ...mono10, color: "var(--cp-ink-3)" }}>Reading the paper desk's status…</span>;
  if (!s) {
    const why = q.isError ? sptProblem(q.error).message : "the overview answered without a status";
    return (
      <span data-testid="pv2-status" data-state="error" role="status" className="flex flex-wrap items-center" style={{ gap: 8 }}>
        <Pill tone="amber" testId="pv2-status-unknown">Status unknown</Pill>
        <span style={{ fontSize: 12, color: "var(--cp-ink-3)", overflowWrap: "anywhere" }}>The feed, kill switch and policy could not be read ({why}).</span>
        {q.isError && <button type="button" style={linkBtn} onClick={() => q.refetch()}>Retry</button>}
      </span>
    );
  }
  const f = freshness(s);
  const live = s.feedState === "live";
  return (
    <div data-testid="pv2-status" data-state="ok" className="flex min-w-0 flex-wrap items-center" style={{ gap: 8 }}>
      <Pill tone={live ? "mint" : "plain"} dot testId="pv2-status-live">{live ? "Live · paper" : "Paper"}</Pill>
      <Pill tone="plain" testId="pv2-status-session" attrs={{ "data-session": s.session ?? "" }}>
        {s.session === "open" ? "Market open" : s.session === "closed" ? "Market closed" : "Session unknown"} · {istClock(now).slice(0, 5)} IST
      </Pill>
      <Pill tone={f.tone} testId="pv2-status-fresh" attrs={{ "data-feed": s.feedState ?? "" }}>{f.text}{f.age ? <> · <span style={lower}>{f.age}</span></> : null}</Pill>
      <Pill tone="plain" testId="pv2-status-policy">
        {s.policyVersion != null && /^\d+$/.test(s.policyVersion) ? <>Policy <span style={lower}>v{s.policyVersion}</span></> : policyText(s.policyVersion)}
      </Pill>
    </div>
  );
}

function KillSwitch({ s }: { s: PaperStatus | null }) {
  if (!s) return null;
  const k = s.killSwitch;
  const why = k.text ?? k.reason ?? undefined;
  if (k.entriesBlocked === true) return <Pill tone="danger" dot testId="pv2-status-ks" attrs={{ "data-state": k.state ?? "" }} title={why}>Trading halted</Pill>;
  if (k.entriesBlocked === false) return <Pill tone="mint" testId="pv2-status-ks" attrs={{ "data-state": k.state ?? "" }} title={why}>Kill switch · {k.state ?? "ACTIVE"}</Pill>;
  return <Pill tone="amber" testId="pv2-status-ks" attrs={{ "data-state": "unknown" }} title={why}>Kill switch · unknown</Pill>;
}

function AccountCard({ acct, open, onToggle }: { acct: UseQueryResult<PaperAccount>; open: boolean; onToggle: () => void }) {
  const a = acct.data;
  const mode = a?.config?.mode ?? null;
  return (
    <div data-testid="pv2-account" className="flex min-w-0 items-center" style={{ gap: 12, padding: "8px 12px", borderRadius: 12, border: "1px solid var(--cp-line)", background: "var(--bg-1)" }}>
      <div className="flex min-w-0 flex-col" style={{ gap: 2 }}>
        <Eyebrow>Account · Mode</Eyebrow>
        <span style={{ fontSize: 13, color: "var(--cp-ink)", overflowWrap: "anywhere" }}>
          Paper account{" · "}
          <span data-testid="pv2-account-capital" style={{ ...NUM, color: "var(--cp-ink-2)" }} title="Starting capital">
            {acct.isPending ? "…" : acct.isError ? "capital unknown" : fmtINR(a?.startingCapitalRs ?? null, { compact: true })}
          </span>
        </span>
      </div>
      {acct.isError ? (
        <button type="button" data-testid="pv2-account-error" style={linkBtn} onClick={() => acct.refetch()} title={sptProblem(acct.error).message}>Account unreadable · Retry</button>
      ) : (
        <button type="button" data-testid="pv2-mode-pill" data-mode={mode ?? ""} aria-expanded={open} aria-haspopup="dialog" onClick={onToggle} disabled={!a}
          style={{ padding: 0, border: 0, background: "transparent", cursor: a ? "pointer" : "default", font: "inherit" }}>
          <Pill tone={mode ? MODE_TONE[mode] : "plain"} dot>{mode ? `${MODE_WORDS[mode].label} mode` : acct.isPending ? "Mode …" : "Mode unknown"}</Pill>
        </button>
      )}
    </div>
  );
}

function ModeChooser({ a, onClose, onReload }: { a: PaperAccount; onClose: () => void; onReload: () => void }) {
  const put = usePutConfig();
  const [confirmAuto, setConfirmAuto] = useState(false);
  const cfg = a.config;
  const current = cfg?.mode ?? null;
  const send = (m: SptMode) => put.mutate({ accountId: a.accountId, body: { mode: m, ...(cfg?.version != null ? { expected_version: cfg.version } : {}) } });
  const pick = (m: SptMode) => {
    if (m === current || put.isPending) return;
    if (m === "auto") { setConfirmAuto(true); return; }
    setConfirmAuto(false);
    send(m);
  };
  const p = put.isError ? sptProblem(put.error) : null;
  return (
    <div data-testid="pv2-mode-chooser" role="dialog" aria-label="Scanner-to-paper mode" className="flex min-w-0 flex-col"
      style={{ gap: 10, padding: 14, borderRadius: 14, border: "1px solid var(--line-2)", background: "var(--bg-1)" }}>
      <div className="flex flex-wrap items-center justify-between" style={{ gap: 8 }}>
        <Eyebrow>Scanner-to-paper mode</Eyebrow>
        <button type="button" data-testid="pv2-mode-close" style={linkBtn} onClick={onClose}>Close</button>
      </div>
      <div role="group" aria-label="Mode" className="grid" style={{ gridTemplateColumns: "repeat(auto-fit,minmax(min(100%,190px),1fr))", gap: 8 }}>
        {MODES.map((m) => {
          const on = m === current;
          return (
            <button key={m} type="button" data-testid={`pv2-mode-${m}`} aria-pressed={on} disabled={put.isPending} onClick={() => pick(m)} className="flex flex-col text-left"
              style={{ gap: 4, padding: "10px 12px", borderRadius: 12, font: "inherit", cursor: on ? "default" : "pointer", color: "var(--cp-ink)",
                border: `1px solid ${on ? "var(--mint-line)" : "var(--line-2)"}`, background: on ? "var(--mint-soft)" : "var(--bg-2)" }}>
              <span style={{ ...mono10, fontSize: 11, color: on ? "var(--mint)" : "var(--cp-ink)" }}>{MODE_WORDS[m].label}{on ? " · current" : ""}</span>
              <span style={{ fontSize: 12, lineHeight: 1.45, color: "var(--cp-ink-3)" }}>{MODE_WORDS[m].line}</span>
            </button>
          );
        })}
      </div>
      {confirmAuto && (
        <div data-testid="pv2-mode-confirm" role="alertdialog" aria-label="Switch to Auto" className="flex flex-wrap items-center"
          style={{ gap: 8, padding: "10px 12px", borderRadius: 10, border: "1px solid var(--amber-line)", background: "var(--amber-soft)" }}>
          <span style={{ fontSize: 12.5, color: "var(--cp-ink)", flex: "1 1 240px" }}>Switch to Auto? Every proposal the risk engine approves becomes a paper order at once, without asking you.</span>
          <button type="button" data-testid="pv2-mode-confirm-yes" style={btnPrimary} onClick={() => { setConfirmAuto(false); send("auto"); }}>Switch to Auto</button>
          <button type="button" data-testid="pv2-mode-confirm-no" style={btn} onClick={() => setConfirmAuto(false)}>Cancel</button>
        </div>
      )}
      {put.isPending && <span style={{ fontSize: 12, color: "var(--cp-ink-3)" }}>Saving…</span>}
      {put.isSuccess && <span data-testid="pv2-mode-saved" role="status" style={{ fontSize: 12, color: "var(--mint)" }}>Saved: the mode is now {put.data?.mode ? MODE_WORDS[put.data.mode].label : "as sent"}.</span>}
      {p && (
        <div data-testid="pv2-mode-error" data-code={p.code ?? ""} role="alert" className="flex flex-wrap items-center"
          style={{ gap: 8, padding: "8px 12px", borderRadius: 10, border: "1px solid var(--danger-line)", background: "var(--danger-soft)", fontSize: 12.5 }}>
          <span style={{ color: "var(--cp-ink)", overflowWrap: "anywhere", flex: "1 1 240px" }}>
            {p.code === "concurrent_change" || p.status === 409
              ? "The mode changed elsewhere since this page read it. Reload, then choose again."
              : `Not saved: ${p.code ? `${p.code} · ` : ""}${p.message}`}
          </span>
          {(p.code === "concurrent_change" || p.status === 409) && <button type="button" data-testid="pv2-mode-reload" style={btn} onClick={() => { put.reset(); onReload(); }}>Reload</button>}
        </div>
      )}
    </div>
  );
}

/** The strip and the account card above every Paper Trading view. `acct` is the caller's one read of the paper account. */
export function PaperShell({ acct }: { acct: UseQueryResult<PaperAccount> }) {
  const { mobile } = useCopilotShell();
  const q = usePaperOverview();
  const [open, setOpen] = useState(false);
  return (
    <div data-testid="pv2-shell" className="flex min-w-0 flex-col" style={{ gap: 10 }}>
      <div className="flex min-w-0 flex-wrap items-center justify-between" style={{ gap: 10, paddingBottom: mobile ? 8 : 10, borderBottom: "1px solid var(--cp-line)" }}>
        <StatusStrip q={q} />
        <div className="flex min-w-0 flex-wrap items-center" style={{ gap: 10, marginLeft: "auto" }}>
          <KillSwitch s={q.data?.status ?? null} />
          <AccountCard acct={acct} open={open} onToggle={() => setOpen((v) => !v)} />
        </div>
      </div>
      {open && acct.data && <ModeChooser a={acct.data} onClose={() => setOpen(false)} onReload={() => { void acct.refetch(); }} />}
    </div>
  );
}
