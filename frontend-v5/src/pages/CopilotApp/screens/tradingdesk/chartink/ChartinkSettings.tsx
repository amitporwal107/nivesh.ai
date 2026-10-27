/**
 * More · Chartink scans (?tab=more&view=chartink) - use the user's own Chartink scans as opportunity sources.
 *
 * Connect a public Chartink dashboard by its address (checked here first, then by the route, whose 422 problems are
 * shown as they come), see its scans with what each can do, switch scans on or off, say which way each one leans,
 * refresh now (the route allows one refresh per 10 minutes) and disconnect (removes the saved dashboard and its results).
 *
 * Chartink has no official API: the backend reads the public dashboard and runs the scans through Chartink's own
 * page, a few times a day at most. The scans' clauses never reach this screen. A scan that needs the user's private
 * Chartink indicators cannot run on the public endpoint and says so. Results are the user's own rules, not validated signals.
 * Nothing here places an order.
 */
import { useEffect, useId, useRef, useState, type CSSProperties } from "react";
import { Btn, EmptyBlock, ErrorBlock, LoadingBlock, Pill, Section, fmtNum } from "../../../components/ui";
import { ApiError } from "@/services/api/errors";
import { INPUT_STYLE } from "../../trading/parts";
import { stampIst } from "../overview-data";
import { useDesk } from "../context";
import { DIRECTION_LABEL } from "../strategy/plan-form";
import { ChartinkTrust, CHARTINK_SOURCE_LABEL, Switch } from "./ChartinkParts";
import { ChartinkPicks } from "./ChartinkPicks";
import { DIRECTIONS, failureText as failureLine, type ChartinkHits, type ChartinkRefresh, type ChartinkScan, type ChartinkSourceDoc, type ScanDirection } from "./chartink-contract";
import {
  checkDashboardUrl, connectProblems, cooldownSeconds, useChartinkHits, useChartinkRefresh, useChartinkSource, useConnectChartink,
  useDisconnectChartink, useUpdateChartinkScan,
} from "./chartink-data";

const noteStyle: CSSProperties = { fontSize: 12, lineHeight: 1.5, color: "var(--cp-ink-3)" };
const th: CSSProperties = { textAlign: "left", padding: "8px 10px", whiteSpace: "nowrap", borderBottom: "1px solid var(--cp-line)" };
const td: CSSProperties = { padding: "10px", verticalAlign: "top", borderBottom: "1px solid var(--cp-line)", fontSize: 12.5 };
const selectStyle: CSSProperties = { height: 30, maxWidth: "100%", padding: "0 8px", borderRadius: 8, border: "1px solid var(--line-2)", background: "var(--bg-2)", color: "var(--cp-ink)", fontFamily: "var(--sans)", fontSize: 12 };

export const CHARTINK_NO_API_NOTE =
  "Chartink has no official API. Nivesh reads your public dashboard and runs your scans through Chartink’s own page, at most a few times a day. Results are not validated signals.";
export const STATS_REASON = "Market statistics, not a stock list";

/** Words for a failed call to the routes, naming Chartink when the route says it could not be reached. */
function failureText(e: unknown, what: string): string {
  if (e instanceof ApiError) {
    if (e.kind === "auth") return `${what}: you are signed out. Sign in again.`;
    if (e.kind === "forbidden") return `${what}: this account does not have access to the Chartink scans.`;
    if (e.kind === "network" || e.kind === "timeout") return `${what}: the request did not reach Nivesh. Check the connection and try again.`;
    if (e.kind === "contract_drift") return `${what}: the answer was not in the expected form, so nothing is shown.`;
    if (e.kind === "server") return `${what}: Chartink could not be reached just now${e.detail ? ` (${e.detail})` : ""}. Nothing was changed. Try again later.`;
    if (e.detail) return `${what}: ${e.detail}`;
  }
  return `${what}: it failed.`;
}

/** `asSection`: hosted below the Screener on Market Desk (the desk redesign of 2026-10-27), so its title is a level-2 heading. */
export default function ChartinkSettings({ asSection = false }: { asSection?: boolean } = {}) {
  const { persona } = useDesk();
  const Title = asSection ? "h2" : "h1";
  const plain = persona === "investor";
  const src = useChartinkSource();
  const hitsQ = useChartinkHits();
  const doc = src.data ?? null;
  return (
    <div data-testid="chartink-settings" data-persona={persona} className="flex min-w-0 flex-col" style={{ gap: 18 }}>
      <header className="flex flex-col" style={{ gap: 8 }}>
        <span className="flex flex-wrap items-center" style={{ gap: 8 }}>
          <span className="cp-eyebrow">Market Desk · Screener</span>
          <span className="cp-pill" data-tone="indigo">Your own scans</span>
        </span>
        <Title className="cp-display m-0" data-testid="chartink-title" style={{ fontSize: 34, lineHeight: 1.1, letterSpacing: "-0.02em" }}>
          {plain ? <>Add your <em>Chartink</em> ideas to the desk</> : <>Chartink <em>scans</em></>}
        </Title>
        <p className="m-0" style={{ fontSize: 13.5, lineHeight: 1.55, color: "var(--cp-ink-2)" }}>
          {plain ? "Your Chartink scans can sit beside the AI scanner’s ideas on the Overview, the AI Scanner and the Strategy Builder." : "Use your Chartink scans as opportunity sources next to the AI scanner on the Overview, the AI Scanner and the Strategy Builder."}
        </p>
        <p data-testid="chartink-no-api" role="note" className="m-0" style={noteStyle}>{CHARTINK_NO_API_NOTE}</p>
      </header>

      <ConnectForm doc={doc} />

      {src.isPending && <LoadingBlock label="Loading your Chartink dashboard" rows={3} />}
      {src.isError && (
        <div data-testid="chartink-error"><ErrorBlock title="Your Chartink dashboard didn’t load" error={src.error} onRetry={() => src.refetch()} /></div>
      )}
      {src.isSuccess && doc == null && (
        <div data-testid="chartink-not-connected">
          <EmptyBlock title="No Chartink dashboard connected" body="Paste the address of your public Chartink dashboard above and press Connect. Nothing is read from Chartink until you do." />
        </div>
      )}
      {doc && <Connected doc={doc} hitsQ={hitsQ} plain={plain} />}
    </div>
  );
}

// ── connect ──────────────────────────────────────────────────────────────

function ConnectForm({ doc }: { doc: ChartinkSourceDoc | null }) {
  const id = useId();
  const connect = useConnectChartink();
  const [url, setUrl] = useState("");
  const [clientProblem, setClientProblem] = useState<string | null>(null);
  const serverProblems = connect.isError ? connectProblems(connect.error) : [];
  const failure = connect.isError && serverProblems.length === 0 ? failureText(connect.error, "The dashboard was not connected") : null;
  const submit = () => {
    const p = checkDashboardUrl(url);
    setClientProblem(p);
    if (p) return;
    connect.mutate(url.trim(), { onSuccess: () => setUrl("") });
  };
  const problems = clientProblem ? [clientProblem] : serverProblems;
  return (
    <Section title={doc ? "Change dashboard" : "Connect your dashboard"} note="A public dashboard address, https://chartink.com/dashboard/<number>">
      <form data-testid="chartink-connect" className="flex min-w-0 flex-col" style={{ gap: 10 }} onSubmit={(e) => { e.preventDefault(); submit(); }}>
        <label htmlFor={`${id}-url`} className="cp-eyebrow" style={{ fontSize: 9 }}>Chartink dashboard address</label>
        <div className="flex flex-wrap items-center" style={{ gap: "8px 12px" }}>
          <input id={`${id}-url`} data-testid="chartink-url" value={url} inputMode="url" autoComplete="off" spellCheck={false} placeholder="https://chartink.com/dashboard/123456"
            aria-invalid={problems.length > 0 || undefined} aria-describedby={problems.length ? `${id}-err` : undefined}
            onChange={(e) => { setUrl(e.target.value); setClientProblem(null); }} style={{ ...INPUT_STYLE, flex: "1 1 280px", width: "auto" }} />
          <Btn variant="primary" type="submit" data-testid="chartink-connect-btn" disabled={connect.isPending} aria-busy={connect.isPending}>
            {connect.isPending ? "Connecting…" : doc ? "Change dashboard" : "Connect"}
          </Btn>
        </div>
        {problems.length > 0 && (
          <ul id={`${id}-err`} data-testid="chartink-connect-problems" className="m-0 flex flex-col" style={{ gap: 4, paddingLeft: 18 }}>
            {problems.map((p) => <li key={p} role="alert" style={{ fontSize: 12.5, color: "var(--cp-danger)" }}>{p}</li>)}
          </ul>
        )}
        {failure && <p role="alert" data-testid="chartink-connect-failure" className="m-0" style={{ fontSize: 12.5, color: "var(--cp-danger)" }}>{failure}</p>}
      </form>
    </Section>
  );
}

// ── the connected dashboard ──────────────────────────────────────────────

function Connected({ doc, hitsQ, plain }: { doc: ChartinkSourceDoc; hitsQ: ReturnType<typeof useChartinkHits>; plain: boolean }) {
  const hits = hitsQ.data ?? null;
  const enabled = doc.scans.filter((s) => s.enabled && s.supported && s.kind === "stock_scan").length;
  return (
    <>
      <Section title={doc.title ?? "Your Chartink dashboard"} note={`${doc.scans.length} ${doc.scans.length === 1 ? "scan" : "scans"} · ${enabled} on`}>
        <div className="flex min-w-0 flex-col" style={{ gap: 12 }}>
          <p data-testid="chartink-dashboard" className="m-0" style={{ ...noteStyle, overflowWrap: "anywhere" }}>
            {doc.url} · dashboard read {stampIst(doc.fetched_at) ?? "—"}
          </p>
          <Actions retryAfter={doc.refresh.retry_after_s} />
        </div>
      </Section>
      <ChartinkPicks variant="full" testId="ck-picks" />
      <ScanTable doc={doc} plain={plain} />
      <HitsStatus hits={hits} hitsQ={hitsQ} enabled={enabled} />
      <div className="flex flex-col" style={{ gap: 4 }}>
        {hits ? <ChartinkTrust hits={hits} testId="chartink-trust" /> : <span className="cp-mono-note" data-testid="chartink-trust">{CHARTINK_SOURCE_LABEL} · not validated</span>}
      </div>
    </>
  );
}

function Actions({ retryAfter }: { retryAfter: number | null }) {
  const refresh = useChartinkRefresh();
  const disconnect = useDisconnectChartink();
  const [confirm, setConfirm] = useState(false);
  const dialog = useRef<HTMLDivElement>(null);
  useEffect(() => { if (confirm) dialog.current?.querySelector<HTMLButtonElement>("button")?.focus(); }, [confirm]);
  const wait = refresh.isError ? cooldownSeconds(refresh.error) : null;
  const refreshFailure = refresh.isError && wait == null ? failureText(refresh.error, "The refresh failed") : null;
  return (
    <div className="flex min-w-0 flex-col" style={{ gap: 10 }}>
      <div className="flex flex-wrap items-center" style={{ gap: "8px 12px" }}>
        <Btn data-testid="chartink-refresh" onClick={() => refresh.mutate()} disabled={refresh.isPending} aria-busy={refresh.isPending}>{refresh.isPending ? "Refreshing…" : "Refresh now"}</Btn>
        <Btn variant="ghost" data-testid="chartink-disconnect" onClick={() => setConfirm(true)} disabled={confirm || disconnect.isPending}>Disconnect</Btn>
        <span style={noteStyle}>Runs your enabled scans through Chartink’s page. Allowed once every 10 minutes.</span>
        {retryAfter != null && retryAfter > 0 && !refresh.isError && (
          <span data-testid="chartink-next-refresh" style={{ fontSize: 12, color: "var(--amber)" }}>A refresh ran recently: the next is allowed in {Math.max(1, Math.ceil(retryAfter / 60))} {Math.ceil(retryAfter / 60) <= 1 ? "minute" : "minutes"}.</span>
        )}
      </div>
      <div role="status" aria-live="polite" data-testid="chartink-refresh-live" className="flex flex-col" style={{ gap: 4 }}>
        {refresh.isPending && <span style={noteStyle}>Running your scans…</span>}
        {wait != null && (
          <span data-testid="chartink-cooldown" style={{ fontSize: 12.5, color: "var(--amber)" }}>
            Chartink was refreshed a moment ago. Try again in {Math.max(1, Math.ceil(wait / 60))} {Math.max(1, Math.ceil(wait / 60)) === 1 ? "minute" : "minutes"}.
          </span>
        )}
        {refreshFailure && <span data-testid="chartink-refresh-failure" role="alert" style={{ fontSize: 12.5, color: "var(--cp-danger)" }}>{refreshFailure}</span>}
        {refresh.isSuccess && <RefreshResult r={refresh.data} />}
      </div>
      {confirm && (
        <div ref={dialog} role="alertdialog" aria-labelledby="ck-disc-t" aria-describedby="ck-disc-d" data-testid="chartink-disconnect-confirm" className="cp-card flex flex-col" style={{ gap: 10, padding: 14 }}>
          <strong id="ck-disc-t" style={{ fontSize: 14, fontWeight: 500 }}>Disconnect Chartink?</strong>
          <span id="ck-disc-d" style={{ fontSize: 13, color: "var(--cp-ink-2)" }}>This removes the saved dashboard and its results. Your Chartink account is not touched, and you can connect again at any time.</span>
          <span className="flex flex-wrap" style={{ gap: 10 }}>
            <Btn variant="primary" data-testid="chartink-disconnect-yes" disabled={disconnect.isPending} onClick={() => disconnect.mutate(undefined, { onSuccess: () => setConfirm(false) })}>{disconnect.isPending ? "Removing…" : "Remove it"}</Btn>
            <Btn variant="ghost" data-testid="chartink-disconnect-no" onClick={() => setConfirm(false)}>Keep it</Btn>
          </span>
          {disconnect.isError && <span role="alert" data-testid="chartink-disconnect-failure" style={{ fontSize: 12.5, color: "var(--cp-danger)" }}>{failureText(disconnect.error, "Disconnecting failed")}</span>}
        </div>
      )}
    </div>
  );
}

function RefreshResult({ r }: { r: ChartinkRefresh }) {
  const bad = r.scans.filter((s) => !s.ok).length;
  return (
    <div data-testid="chartink-refresh-result" className="flex flex-col" style={{ gap: 3 }}>
      <span style={{ fontSize: 12.5 }}>
        Refreshed {stampIst(r.ran_at) ?? "just now"}: {r.scans.length - bad} of {r.scans.length} {r.scans.length === 1 ? "scan" : "scans"} ran{bad ? `, ${bad} failed` : ""}.
      </span>
      {r.degraded && <span data-testid="chartink-degraded" role="note" style={{ fontSize: 12.5, color: "var(--amber)" }}>{r.degraded}</span>}
      <ul className="m-0 flex flex-col" style={{ gap: 2, paddingLeft: 18 }}>
        {r.scans.map((s) => (
          <li key={s.id} data-testid="chartink-refresh-scan" data-ok={s.ok} style={{ fontSize: 12.5, color: s.ok ? "var(--cp-ink-2)" : "var(--cp-danger)" }}>
            {s.name}: {s.ok ? `${s.hits == null ? "—" : fmtNum(s.hits)} ${s.hits === 1 ? "hit" : "hits"}${s.seconds != null ? ` in ${fmtNum(s.seconds, 1)} s` : ""}` : `failed${s.error ? ` (${s.error})` : ""}`}
          </li>
        ))}
      </ul>
    </div>
  );
}

// ── the scans ────────────────────────────────────────────────────────────

function ScanTable({ doc, plain }: { doc: ChartinkSourceDoc; plain: boolean }) {
  const update = useUpdateChartinkScan();
  const [busy, setBusy] = useState<string | null>(null);
  const patch = (id: string, body: { enabled?: boolean; direction?: ScanDirection }) => {
    setBusy(id);
    update.mutate({ id, ...body }, { onSettled: () => setBusy(null) });
  };
  const heads = ["Scan", "Kind", "Can run", "Enabled", plain ? "Leans" : "Direction", "Last fetch", "Hits"];
  return (
    <Section title="Your scans" note="Switch a scan on to use its hits as opportunities">
      <div className="flex min-w-0 flex-col" style={{ gap: 8 }}>
        {update.isError && <p role="alert" data-testid="chartink-update-failure" className="m-0" style={{ fontSize: 12.5, color: "var(--cp-danger)" }}>{failureText(update.error, "The change was not saved")}</p>}
        {doc.scans.length === 0 ? (
          <p data-testid="chartink-no-scans" className="m-0" style={noteStyle}>This dashboard has no scans.</p>
        ) : (
          <div tabIndex={0} role="region" aria-label="Your Chartink scans (scrolls sideways inside this box)" className="cp-scroll" style={{ overflowX: "auto", maxWidth: "100%" }}>
            <table data-testid="chartink-scans" style={{ borderCollapse: "collapse", width: "100%", minWidth: 860 }}>
              <caption className="sr-only">Chartink scans on your dashboard: what each can do, whether it is on, which way it leans, and its last result</caption>
              <thead><tr className="cp-mono-note">{heads.map((h) => <th key={h} scope="col" style={th}>{h}</th>)}</tr></thead>
              <tbody>
                {doc.scans.map((s) => <ScanRow key={s.id} s={s} plain={plain} pending={busy === s.id} onPatch={(b) => patch(s.id, b)} />)}
              </tbody>
            </table>
          </div>
        )}
      </div>
    </Section>
  );
}

function ScanRow({ s, plain, pending, onPatch }: {
  s: ChartinkScan; plain: boolean; pending: boolean; onPatch: (b: { enabled?: boolean; direction?: ScanDirection }) => void;
}) {
  const stats = s.kind === "market_stats";
  const blocked = stats ? STATS_REASON : !s.supported ? s.unsupported_reason ?? "This scan cannot run on the public endpoint." : null;
  const locked = blocked != null;
  const run = s.last_run;
  return (
    <tr data-testid={`ck-scan-${s.id}`} data-supported={s.supported} data-kind={s.kind} data-enabled={s.enabled}>
      <th scope="row" style={{ ...td, textAlign: "left", fontWeight: 400, minWidth: 220 }}>
        <span className="flex flex-col" style={{ gap: 3 }}>
          <span data-testid="ck-scan-name" style={{ fontSize: 13, fontWeight: 500 }}>{s.name}</span>
          {s.description && <span data-testid="ck-scan-desc" style={noteStyle}>{s.description}</span>}
          {s.uses_intraday_candles && (
            <span data-testid="ck-scan-intraday" title="This scan reads intraday candles, so its hits depend on the time of the fetch and are not end-of-day figures"><Pill tone="amber">Intraday candles</Pill></span>
          )}
        </span>
      </th>
      <td style={td} data-testid="ck-scan-kind">{stats ? "Market statistics" : "Stock scan"}</td>
      <td style={{ ...td, minWidth: 190 }} data-testid="ck-scan-supported">
        {blocked ? <span data-testid="ck-scan-reason"><span aria-hidden>✕ </span>No: {blocked}</span> : <span><span aria-hidden>✓ </span>Yes</span>}
      </td>
      <td style={td}>
        <Switch testId="ck-scan-enabled" label={`Use ${s.name} as an opportunity source`} on={locked ? false : s.enabled} disabled={locked || pending} onChange={(v) => onPatch({ enabled: v })} />
      </td>
      <td style={td}>
        <select aria-label={`Direction of ${s.name}`} data-testid="ck-scan-direction" value={s.direction} disabled={locked || pending} onChange={(e) => onPatch({ direction: e.target.value as ScanDirection })} style={selectStyle}>
          {DIRECTIONS.map((d) => <option key={d} value={d}>{DIRECTION_LABEL[d][plain ? "plain" : "trader"]}</option>)}
        </select>
      </td>
      <td style={td} data-testid="ck-scan-fetched">
        {locked ? "—" : run == null ? "Not fetched yet" : run.ok === false ? <span style={{ color: "var(--cp-danger)" }}>Failed{run.error ? `: ${run.error}` : ""}</span> : (stampIst(run.at) ?? "—")}
      </td>
      <td className="cp-num" style={td} data-testid="ck-scan-hits">{locked || !run || run.ok === false || run.hits == null ? "—" : fmtNum(run.hits)}</td>
    </tr>
  );
}

function HitsStatus({ hits, hitsQ, enabled }: { hits: ChartinkHits | null; hitsQ: ReturnType<typeof useChartinkHits>; enabled: number }) {
  if (hitsQ.isError) {
    return <div data-testid="chartink-hits-error"><ErrorBlock title="The latest hits didn’t load" error={hitsQ.error} onRetry={() => hitsQ.refetch()} /></div>;
  }
  if (!hits) return hitsQ.isFetching ? <LoadingBlock label="Loading the latest hits" rows={2} /> : null;
  const failed = hits.scans.filter((s) => !s.ok);
  const unknown = hits.unknown_symbols;
  const notInAi = hits.symbols.filter((s) => s.in_ai_scanner === false).length;
  const alsoAi = hits.symbols.filter((s) => s.in_ai_scanner === true).length;
  const unsure = hits.symbols.some((s) => s.in_ai_scanner == null);
  return (
    <div className="flex min-w-0 flex-col" style={{ gap: 8 }}>
      {hits.stale_note && <p role="note" data-testid="chartink-stale" className="m-0" style={{ fontSize: 12.5, color: "var(--amber)" }}>{hits.stale_note}</p>}
      {failed.length > 0 && (
        <p role="note" data-testid="chartink-partial" className="m-0" style={{ fontSize: 12.5, color: "var(--amber)" }}>
          {failed.length} of {hits.scans.length} {hits.scans.length === 1 ? "scan" : "scans"} failed on the last fetch: {failed.map((f) => `${f.name}${f.error ? ` (${f.error})` : ""}`).join("; ")}. The others are used.
        </p>
      )}
      {hits.source_failures.length > 0 && (
        <p role="note" data-testid="chartink-source-failures" className="m-0" style={{ fontSize: 12.5, color: "var(--amber)" }}>
          Source problems: {hits.source_failures.map(failureLine).join("; ")}
        </p>
      )}
      {hits.symbols.length === 0 && failed.length < hits.scans.length ? (
        <p data-testid="chartink-no-hits" className="m-0" style={noteStyle}>
          {hits.empty_reason ?? (enabled === 0 ? "No scan is switched on, so there are no hits." : "No hits: none of your enabled scans listed a stock on the latest fetch.")}
        </p>
      ) : (
        <p data-testid="chartink-hit-summary" className="m-0" style={noteStyle}>
          {fmtNum(hits.symbols.length)} {hits.symbols.length === 1 ? "stock" : "stocks"} across your enabled scans; {unsure ? "the AI scanner could not be read, so the overlap is not known." : `${fmtNum(alsoAi)} also in the AI scan, ${fmtNum(notInAi)} not.`}
        </p>
      )}
      {unknown.length > 0 && (
        <details data-testid="chartink-unknown" style={{ fontSize: 12.5, color: "var(--cp-ink-2)" }}>
          <summary data-testid="chartink-unknown-toggle" style={{ cursor: "pointer" }}>Not shown as stocks ({fmtNum(unknown.length)})</summary>
          <ul className="m-0 flex flex-col" style={{ gap: 4, paddingLeft: 18, paddingTop: 6 }}>
            {unknown.map((u) => (
              <li key={u.symbol} data-testid="chartink-unknown-row">
                <span className="cp-num">{u.symbol}</span>: {u.note ?? "Not in the NSE stock symbol master."}
                {u.scans.length > 0 && <span style={noteStyle}> On {u.scans.map((x) => x.name).join(", ")}.</span>}
                {u.suggestions.length > 0 && <span> Did you mean {u.suggestions.map((x) => x.symbol).join(", ")}?</span>}
              </li>
            ))}
          </ul>
        </details>
      )}
    </div>
  );
}
