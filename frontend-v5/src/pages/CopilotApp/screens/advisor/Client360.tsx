/**
 * Client 360 — one client, read before you open their portfolio.
 *
 * The shell's own build of the original v5 Client 360 (pages/Client360), on
 * the same client book and the same derivations (pages/AdvisorDashboard/derive),
 * so the health score, top issue and review age match the original page and
 * the Client book. It differs from the original in three ways:
 *   - the client is chosen by the address (?client=<profile id>), so the
 *     Client book and the SIP board can link straight to one client;
 *   - opening the client stays inside the shell;
 *   - a request that fails says so (the original printed "Nothing flagged").
 *
 * Data:
 *   who, scores, top issue, summary   GET /api/mfd/profiles                          (useAdvisorBook)
 *   needs attention                   GET /api/mfd/profiles/{id}/needs-attention
 *   value, recent purchases           GET /api/mfd/profiles/{id}/portfolio-trend
 *   unrealised gains                  GET /api/mfd/profiles/{id}/tax-summary
 *   portfolio history                 GET /api/portfolio/cas-snapshots?profile_id=
 *   statements from the client        GET /api/mfd/profiles/{id}/cas-invites, /cas-uploads
 *   notes                             GET /api/mfd/profiles/{id}/notes
 *   download holdings                 GET /api/mfd/profiles/{id}/holdings/export
 *
 * Read only. Saving a note, requesting a statement, logging a call and the
 * review pack are not wired; the NotConnected block at the end says why.
 */
import { useMemo, useState, type CSSProperties, type ReactNode } from "react";
import { useSearchParams } from "react-router-dom";
import { useAdvisorBook } from "@/hooks/use-advisor";
import { decorateProfile, fmtDaysSince, healthTone, type AdvisorProfile } from "@/pages/AdvisorDashboard/derive";
import { ApiError } from "@/services/api/errors";
import { MfdWorkspaceC } from "@/services/contracts/advisor.contract";
import {
  AskChips, Btn, DataTable, EmptyBlock, Footnote, LoadingBlock, NotConnected, Pill, Screen, ScreenHeader, Section, Tiles,
  TONE_COLOR, errorSentence, fmtDate, fmtINR, fmtNum, fmtPct, relTime, signTone,
  type Column, type TileItem, type Tone,
} from "../../components/ui";
import { useCopilotShell } from "../../lib/shell-context";
import { LoadFailed } from "../internal/shared";
import {
  downloadClientHoldings, downloadSharedStatement, humanise, requestStatus, statementSource, statementTypeLabel, taxBucketLabel,
  useClientAttention, useClientNotes, useClientSharedFiles, useClientStatementRequests, useClientStatements, useClientTax, useClientTrend,
  type ClientStatement, type ClientTax, type ClientTrend, type HoldingsFormat, type SharedFile,
} from "./data";
import { AdvisorOnly, AssetName, BOOK_TONE, NotAnAdvisor, QuerySection, Quiet, useAdvisorSession, type AdvisorSession } from "./parts";

const HISTORY_PREVIEW = 6;

const SELECT_STYLE: CSSProperties = {
  minWidth: 0, maxWidth: "100%", background: "var(--bg-2)", color: "var(--cp-ink)", border: "1px solid var(--line-2)",
  borderRadius: 8, padding: "8px 10px", fontFamily: "var(--sans)", fontSize: 13,
};

/** Wealth tier from assets — the same thresholds as the original Client 360. */
function wealthTier(aum: number | null | undefined): { label: string; means: string } | null {
  if (aum == null) return null;
  if (aum >= 5e7) return { label: "UHNI", means: "Assets of ₹5 Cr or more" };
  if (aum >= 2e7) return { label: "HNI", means: "Assets of ₹2 Cr or more" };
  if (aum >= 5e6) return { label: "Affluent", means: "Assets of ₹50 L or more" };
  return null;
}

/** Risk score: higher is riskier. Bands as on the original Client 360. */
function riskTone(risk: number | null | undefined): Tone {
  if (risk == null) return "ink";
  return risk >= 60 ? "danger" : risk >= 40 ? "amber" : "mint";
}

function score(v: number | null | undefined): string {
  return v == null ? "—" : String(Math.round(v));
}

// ── small layout pieces ──────────────────────────────────────────────────

interface Stat {
  k: string;
  v: ReactNode;
  s?: ReactNode;
  tone?: Tone;
}

/** Label / figure / one line, without the card a Tiles row draws — for use inside a card. */
function Stats({ items }: { items: Stat[] }) {
  return (
    <div className="grid" style={{ gridTemplateColumns: "repeat(auto-fit,minmax(140px,1fr))", gap: "14px 18px" }}>
      {items.map((m) => (
        <div key={m.k} className="flex min-w-0 flex-col" style={{ gap: 4 }}>
          <span className="cp-eyebrow">{m.k}</span>
          <span className="cp-num" style={{ fontSize: 20, color: TONE_COLOR[m.tone ?? "ink"] }}>{m.v}</span>
          {m.s != null && <span style={{ fontSize: 12, lineHeight: 1.45, color: "var(--cp-ink-3)" }}>{m.s}</span>}
        </div>
      ))}
    </div>
  );
}

function Signed({ value, children }: { value: number | null | undefined; children: ReactNode }) {
  return <span style={{ color: value == null || value === 0 ? undefined : TONE_COLOR[signTone(value)] }}>{children}</span>;
}

function SubHead({ children }: { children: ReactNode }) {
  return <div className="cp-eyebrow" style={{ padding: "12px 16px 0" }}>{children}</div>;
}

// ── header: who, and what you can do ─────────────────────────────────────

function ExportHoldings({ profileId }: { profileId: string }) {
  const [busy, setBusy] = useState<HoldingsFormat | null>(null);
  const [failed, setFailed] = useState<string | null>(null);

  const run = async (format: HoldingsFormat) => {
    setBusy(format);
    setFailed(null);
    try {
      await downloadClientHoldings(profileId, format);
    } catch (e) {
      setFailed(e instanceof ApiError && e.kind === "not_found"
        ? "This client has no holdings to download."
        : `The download failed${errorSentence(e) ? ` — ${errorSentence(e)}` : ""}.`);
    } finally {
      setBusy(null);
    }
  };

  return (
    <>
      <Btn data-testid="client360-export-xlsx" disabled={busy != null} onClick={() => void run("xlsx")}>
        {busy === "xlsx" ? "Preparing…" : "Download holdings · Excel"}
      </Btn>
      <Btn data-testid="client360-export-csv" variant="ghost" disabled={busy != null} onClick={() => void run("csv")}>
        {busy === "csv" ? "Preparing…" : "CSV"}
      </Btn>
      {failed && <span role="alert" data-testid="client360-export-error" style={{ flex: "1 1 100%", fontSize: 12, color: "var(--cp-danger)" }}>{failed}</span>}
    </>
  );
}

function ClientPicker({ people, value, onChange }: { people: AdvisorProfile[]; value: string; onChange: (profileId: string) => void }) {
  return (
    <label className="flex min-w-0 items-center" style={{ gap: 8, fontSize: 13, color: "var(--cp-ink-2)" }}>
      Client
      <select data-testid="client360-picker" value={value} onChange={(e) => onChange(e.target.value)} style={SELECT_STYLE}>
        {value === "" && <option value="" disabled>Choose a client</option>}
        {people.map((p) => (
          <option key={p.profile_id} value={p.profile_id}>{p.name}{p.type === "SELF" ? " (you)" : ""}</option>
        ))}
      </select>
    </label>
  );
}

// ── the blocks ───────────────────────────────────────────────────────────

function Standing({ p }: { p: AdvisorProfile }) {
  const reasons = p.priority?.reasons ?? [];
  const summary = (p.ai_summary ?? "").trim();
  return (
    <Section title="Where they stand" note="From the same scores as your client book">
      <div className="flex flex-col items-start" style={{ gap: 12 }}>
        {p._issue && <span data-testid="client360-issue"><Pill tone={BOOK_TONE[p._issue.tone]}>{p._issue.label}</Pill></span>}
        {summary && (
          <p data-testid="client360-summary" className="m-0 cp-pretty" style={{ fontSize: 14, lineHeight: 1.6, color: "var(--cp-ink-2)", overflowWrap: "anywhere" }}>{summary}</p>
        )}
        {reasons.length > 0 && (
          <ul className="m-0 flex flex-col" style={{ gap: 4, paddingLeft: 18, listStyle: "disc", fontSize: 13, lineHeight: 1.5, color: "var(--cp-ink-2)" }}>
            {reasons.map((r, i) => <li key={`${i}-${r}`} data-testid="client360-reason">{r}</li>)}
          </ul>
        )}
        {!summary && reasons.length === 0 && <Quiet>No summary has been written for this client yet.</Quiet>}
        {(p.tags?.length ?? 0) > 0 && (
          <span className="flex flex-wrap" style={{ gap: 6 }}>
            {(p.tags ?? []).map((t) => <Pill key={t}>{t}</Pill>)}
          </span>
        )}
      </div>
    </Section>
  );
}

function Attention({ profileId }: { profileId: string }) {
  const q = useClientAttention(profileId);
  return (
    <QuerySection testId="client360-attention" title="Needs attention" note="Critical items on their action plan" what="This client’s open items" query={q}>
      {(items) => items.length === 0 ? (
        <Quiet testId="client360-attention-empty">Nothing on this client’s action plan is marked critical right now.</Quiet>
      ) : (
        <div className="flex flex-col" style={{ gap: 12 }}>
          {items.map((it) => (
            <div key={it.id} data-testid="client360-attention-row" className="flex flex-wrap items-center justify-between" style={{ gap: "6px 12px", fontSize: 13 }}>
              <span className="min-w-0" style={{ flex: "1 1 220px" }}>
                <AssetName name={it.title} sub={it.detail || undefined} />
              </span>
              <Pill tone={it.discussed ? "mint" : "amber"}>{it.discussed ? "Discussed" : "To discuss"}</Pill>
            </div>
          ))}
        </div>
      )}
    </QuerySection>
  );
}

type Buy = ClientTrend["recent_buys"][number];

const BUY_COLUMNS: Array<Column<Buy>> = [
  {
    key: "name", header: "Holding", width: "minmax(0,2fr)",
    render: (b) => <AssetName testId="client360-buy-name" name={(b.name ?? "").trim() || "Unnamed holding"} assetType={b.asset_type} />,
  },
  { key: "date", header: "Bought on", width: "110px", render: (b) => fmtDate(b.buy_date) },
  { key: "units", header: "Units", width: "90px", align: "right", num: true, render: (b) => fmtNum(b.quantity, 3) },
  { key: "value", header: "Value", width: "100px", align: "right", num: true, render: (b) => fmtINR(b.value_rs, { compact: true }) },
];

function Value({ profileId }: { profileId: string }) {
  const q = useClientTrend(profileId);
  return (
    <QuerySection testId="client360-value" flush title="Value" note="Holdings on file at latest prices" what="This client’s portfolio value" query={q}>
      {(t) => t.invested_rs === 0 && t.current_rs === 0 && t.recent_buys.length === 0 ? (
        <div style={{ padding: 16 }}><Quiet testId="client360-value-empty">No holdings are on file for this client.</Quiet></div>
      ) : (
        <>
          <div style={{ padding: 16 }}>
            <Stats items={[
              { k: "Invested", v: <span data-testid="client360-invested">{fmtINR(t.invested_rs, { compact: true })}</span> },
              { k: "Value now", v: <span data-testid="client360-current">{fmtINR(t.current_rs, { compact: true })}</span> },
              {
                k: "Change",
                v: <span data-testid="client360-change">{fmtINR(t.absolute_change_rs, { compact: true, signed: true })}</span>,
                s: t.percent_change == null ? "No cost on file to compare with" : `${fmtPct(t.percent_change, { signed: true })} on the amount invested`,
                tone: signTone(t.absolute_change_rs),
              },
            ]} />
          </div>
          <div style={{ borderTop: "1px solid var(--cp-line)" }}>
            <SubHead>Most recent purchases</SubHead>
            {t.recent_buys.length === 0 ? (
              <div style={{ padding: "10px 16px 16px" }}><Quiet testId="client360-buys-empty">No purchase dates are on file, so recent purchases can’t be listed.</Quiet></div>
            ) : (
              <DataTable columns={BUY_COLUMNS} rows={t.recent_buys} rowKey={(b, i) => `${i}-${b.name ?? ""}`} minWidth={520} />
            )}
          </div>
        </>
      )}
    </QuerySection>
  );
}

type Position = NonNullable<ClientTax["biggest_positions"]>[number];

const POSITION_COLUMNS: Array<Column<Position>> = [
  {
    key: "name", header: "Holding", width: "minmax(0,2fr)",
    render: (r) => <AssetName testId="client360-position-name" name={(r.name ?? "").trim() || "Unnamed holding"} assetType={r.asset_type} ticker={r.ticker} />,
  },
  {
    key: "gain", header: "Unrealised gain", width: "130px", align: "right", num: true,
    render: (r) => <Signed value={r.gain}>{fmtINR(r.gain, { compact: true, signed: true })}</Signed>,
  },
  { key: "bucket", header: "How it would be taxed", width: "minmax(0,1.4fr)", render: (r) => taxBucketLabel(r.bucket) },
];

/** What the estimate assumed, in the server's own words. */
function taxBasis(t: ClientTax): string {
  const parts = [
    t.regime?.equity_stcg ? `equity short-term ${t.regime.equity_stcg}` : null,
    t.regime?.equity_ltcg ? `equity long-term ${t.regime.equity_ltcg}` : null,
    t.user_slab_rate != null ? `debt at an assumed ${fmtPct(t.user_slab_rate * 100, { digits: 0 })} slab` : null,
  ].filter(Boolean);
  return parts.length ? `Rates used: ${parts.join(" · ")}. ` : "";
}

function Gains({ profileId }: { profileId: string }) {
  const q = useClientTax(profileId);
  return (
    <QuerySection testId="client360-tax" flush title="Unrealised gains" note="An estimate · not tax advice" what="This client’s unrealised gains" query={q}>
      {(t) => {
        if (t.total_invested_rs === 0 && t.total_current_rs === 0) {
          return <div style={{ padding: 16 }}><Quiet testId="client360-tax-empty">No holdings are on file for this client.</Quiet></div>;
        }
        // Lots with a purchase date can be called short- or long-term; without one, no tax can be estimated.
        const dated = (t.coverage_pct ?? 0) > 0;
        const quality = t.lot_coverage?.cas_quality;
        const positions = t.biggest_positions ?? [];
        const stats: Stat[] = [
          { k: "Unrealised gain", v: <span data-testid="client360-unrealised">{fmtINR(t.total_unrealized_rs, { compact: true, signed: true })}</span>, tone: signTone(t.total_unrealized_rs) },
          { k: "Short-term", v: <span data-testid="client360-stcg">{dated ? fmtINR(t.stcg_rs, { compact: true, signed: true }) : "—"}</span>, s: "Gain on lots held under the long-term limit" },
          { k: "Long-term", v: <span data-testid="client360-ltcg">{dated ? fmtINR(t.ltcg_rs, { compact: true, signed: true }) : "—"}</span>, s: "Gain on lots held past it" },
        ];
        if ((t.undated_count ?? 0) > 0) {
          stats.push({ k: "No purchase date", v: <span data-testid="client360-undated">{fmtINR(t.undated_gain_rs, { compact: true, signed: true })}</span>, s: `${fmtNum(t.undated_count)} ${t.undated_count === 1 ? "lot" : "lots"} that can’t be placed yet` });
        }
        stats.push({
          k: "Tax if all were sold today",
          v: <span data-testid="client360-est-tax">{dated ? fmtINR(t.est_tax_if_realized_rs, { compact: true }) : "—"}</span>,
          s: dated ? "On the lots that have a purchase date" : "Needs purchase dates",
        });
        return (
          <>
            <div className="flex flex-col" style={{ gap: 14, padding: 16 }}>
              <Stats items={stats} />
              {(quality === "no_data" || quality === "partial") && (
                <span data-testid="client360-tax-coverage" style={{ fontSize: 13, lineHeight: 1.55, color: "var(--cp-ink-2)", padding: "10px 12px", borderRadius: 10, border: "1px solid var(--amber-line)", background: "var(--amber-soft)" }}>
                  {quality === "no_data"
                    ? "The statement on file has no transaction history, so gains can’t be split into short- and long-term."
                    : "The statement on file covers only part of this client’s transaction history, so some gains can’t be split into short- and long-term."}
                  {" "}A detailed statement covering the whole holding period would fill this in.
                </span>
              )}
            </div>
            {positions.length > 0 && (
              <div style={{ borderTop: "1px solid var(--cp-line)" }}>
                <SubHead>Largest unrealised gains</SubHead>
                <DataTable columns={POSITION_COLUMNS} rows={positions} rowKey={(r, i) => `${i}-${r.name ?? ""}`} minWidth={560} />
              </div>
            )}
            <div style={{ padding: "12px 16px" }}>
              <Footnote>{taxBasis(t)}An estimate from the holdings on file, before any exemption the client has already used elsewhere.</Footnote>
            </div>
          </>
        );
      }}
    </QuerySection>
  );
}

const HISTORY_COLUMNS: Array<Column<ClientStatement>> = [
  { key: "date", header: "As of", width: "110px", render: (s) => <span data-testid="client360-history-date" style={{ color: "var(--cp-ink)" }}>{fmtDate(s.snapshot_date)}</span> },
  { key: "source", header: "From", width: "minmax(0,1.2fr)", render: (s) => statementSource(s.trigger) },
  { key: "holdings", header: "Holdings", width: "80px", align: "right", num: true, render: (s) => fmtNum(s.holdings_count) },
  { key: "value", header: "Value", width: "100px", align: "right", num: true, render: (s) => fmtINR(s.total_value, { compact: true }) },
  { key: "return", header: "Return", width: "80px", align: "right", num: true, render: (s) => <Signed value={s.return_pct}>{fmtPct(s.return_pct, { signed: true })}</Signed> },
  { key: "health", header: "Health", width: "80px", align: "right", num: true, render: (s) => (s.health_score == null ? "—" : `${Math.round(s.health_score)}${s.grade ? ` · ${s.grade}` : ""}`) },
];

function History({ profileId }: { profileId: string }) {
  const q = useClientStatements(profileId);
  const [all, setAll] = useState(false);
  return (
    <QuerySection testId="client360-history" flush title="Portfolio history" note="Snapshots saved for this client" what="This client’s portfolio history" query={q}>
      {(d) => d.snapshots.length === 0 ? (
        <div style={{ padding: 16 }}><Quiet testId="client360-history-empty">No snapshot of this client’s portfolio is on file yet. One is saved each time a statement is imported.</Quiet></div>
      ) : (
        <>
          <DataTable columns={HISTORY_COLUMNS} rows={all ? d.snapshots : d.snapshots.slice(0, HISTORY_PREVIEW)} rowKey={(s, i) => `${s.snapshot_date}-${i}`} minWidth={600} />
          {d.snapshots.length > HISTORY_PREVIEW && (
            <div style={{ padding: "12px 16px" }}>
              <button type="button" className="cp-chip" aria-expanded={all} onClick={() => setAll((v) => !v)}>
                {all ? `Show the latest ${HISTORY_PREVIEW}` : `Show all ${d.snapshots.length}`}
              </button>
            </div>
          )}
        </>
      )}
    </QuerySection>
  );
}

function Requests({ profileId }: { profileId: string }) {
  const q = useClientStatementRequests(profileId);
  return (
    <QuerySection testId="client360-requests" title="Statement requests" note="Links sent to the client" what="This client’s statement requests" query={q}>
      {(d) => d.invites.length === 0 ? (
        <Quiet testId="client360-requests-empty">No statement has been requested from this client.</Quiet>
      ) : (
        <div className="flex flex-col" style={{ gap: 12 }}>
          {d.invites.map((inv) => {
            const st = requestStatus(inv.status);
            const files = inv.processed_files?.length ?? 0;
            return (
              <div key={inv.invite_token} data-testid="client360-request-row" className="flex flex-wrap items-center justify-between" style={{ gap: "6px 12px", fontSize: 13 }}>
                <span className="flex min-w-0 flex-col" style={{ gap: 2 }}>
                  <span style={{ color: "var(--cp-ink)" }}>Requested {fmtDate(inv.created_at)}</span>
                  <span style={{ fontSize: 12, color: "var(--cp-ink-3)" }}>
                    {[inv.expires_at ? `Link valid until ${fmtDate(inv.expires_at)}` : null, files > 0 ? `${fmtNum(files)} ${files === 1 ? "file" : "files"} received` : null].filter(Boolean).join(" · ") || "No files received"}
                  </span>
                </span>
                <Pill tone={st.tone}>{st.label}</Pill>
              </div>
            );
          })}
        </div>
      )}
    </QuerySection>
  );
}

function SharedRow({ f }: { f: SharedFile }) {
  const [busy, setBusy] = useState(false);
  const [failed, setFailed] = useState(false);
  const open = async () => {
    setBusy(true);
    setFailed(false);
    try {
      await downloadSharedStatement(f.file_id, f.filename);
    } catch {
      setFailed(true); // said beside the button; the file list itself is unaffected
    } finally {
      setBusy(false);
    }
  };
  const period = f.period_start && f.period_end ? `${fmtDate(f.period_start)} to ${fmtDate(f.period_end)}` : null;
  const facts = [
    f.stored_at ? `Received ${fmtDate(f.stored_at)}` : null,
    period,
    statementTypeLabel(f.statement_type) || null,
    f.holdings_count ? `${fmtNum(f.holdings_count)} holdings read` : null,
  ].filter(Boolean).join(" · ");
  const status = (f.status ?? "").toLowerCase();
  return (
    <div data-testid="client360-shared-row" className="flex flex-wrap items-center justify-between" style={{ gap: "6px 12px", fontSize: 13 }}>
      <span className="flex min-w-0 flex-col" style={{ flex: "1 1 220px", gap: 2 }}>
        <span style={{ color: "var(--cp-ink)", overflowWrap: "anywhere" }}>{f.filename || "Statement"}</span>
        {facts && <span style={{ fontSize: 12, color: "var(--cp-ink-3)" }}>{facts}</span>}
        {f.error && <span style={{ fontSize: 12, color: "var(--cp-danger)", overflowWrap: "anywhere" }}>Could not be read: {f.error}</span>}
        {failed && <span role="alert" style={{ fontSize: 12, color: "var(--cp-danger)" }}>The file didn’t open. Try again.</span>}
      </span>
      <span className="flex items-center" style={{ gap: 8 }}>
        {status && <Pill tone={f.error ? "danger" : "ink"}>{humanise(status)}</Pill>}
        {f.is_downloadable && (
          <Btn variant="ghost" disabled={busy} aria-label={`Open ${f.filename || "statement"}`} onClick={() => void open()}>{busy ? "Opening…" : "Open"}</Btn>
        )}
      </span>
    </div>
  );
}

function Shared({ profileId }: { profileId: string }) {
  const q = useClientSharedFiles(profileId);
  return (
    <QuerySection testId="client360-shared" title="Statements they shared" note="Files received through a request link" what="The statements this client shared" query={q}>
      {(d) => d.files.length === 0 ? (
        <Quiet testId="client360-shared-empty">This client has not shared a statement through a request link.</Quiet>
      ) : (
        <div className="flex flex-col" style={{ gap: 12 }}>
          {d.files.map((f) => <SharedRow key={f.file_id} f={f} />)}
        </div>
      )}
    </QuerySection>
  );
}

function Notes({ profileId }: { profileId: string }) {
  const q = useClientNotes(profileId);
  return (
    <QuerySection testId="client360-notes" title="Notes" note="Saved for this client" what="This client’s notes" query={q}>
      {(n) => {
        const facts = [
          n.sip_amount_rs != null ? `SIP ${fmtINR(n.sip_amount_rs)}${n.sip_frequency ? ` · ${humanise(n.sip_frequency).toLowerCase()}` : ""}` : null,
          n.next_sip_due ? `Next SIP due ${fmtDate(n.next_sip_due)}` : null,
          n.preferred_channel ? `Prefers ${humanise(n.preferred_channel).toLowerCase()}` : null,
        ].filter(Boolean);
        const note = (n.note ?? "").trim();
        if (!note && facts.length === 0) return <Quiet testId="client360-notes-empty">No note is saved for this client.</Quiet>;
        return (
          <div className="flex flex-col" style={{ gap: 10 }}>
            {note && <p data-testid="client360-note" className="m-0" style={{ fontSize: 14, lineHeight: 1.6, color: "var(--cp-ink-2)", whiteSpace: "pre-wrap", overflowWrap: "anywhere" }}>{note}</p>}
            {facts.length > 0 && <span data-testid="client360-note-facts" style={{ fontSize: 13, color: "var(--cp-ink-2)" }}>{facts.join(" · ")}</span>}
            {n.updated_at && relTime(n.updated_at) && <Footnote>Updated {relTime(n.updated_at)}</Footnote>}
          </div>
        );
      }}
    </QuerySection>
  );
}

// ── one client ───────────────────────────────────────────────────────────

function Detail({ p, session }: { p: AdvisorProfile; session: AdvisorSession }) {
  const isSelf = p.type === "SELF";
  const opening = session.openingId != null;
  const reviewed = p.last_reviewed_at ? fmtDaysSince(p.last_reviewed_at) : null;
  const holdingsValued = (p.portfolio_value_rs ?? 0) > 0;

  const tiles: TileItem[] = [
    { k: "Health", v: <span data-testid="client360-health">{p._health ?? "—"}</span>, s: p._health == null ? "Not scored yet" : "Out of 100 · quality and risk together", tone: p._health == null ? "ink" : BOOK_TONE[healthTone(p._health)] },
    { k: "Quality", v: <span data-testid="client360-quality">{score(p.portfolio_score)}</span>, s: "Portfolio quality, out of 100", tone: p.portfolio_score == null ? "ink" : BOOK_TONE[healthTone(p.portfolio_score)] },
    { k: "Risk", v: <span data-testid="client360-risk">{score(p.risk_score)}</span>, s: "Out of 100 · higher means more risk", tone: riskTone(p.risk_score) },
    { k: "Assets", v: <span data-testid="client360-aum">{fmtINR(p._aum, { compact: true })}</span>, s: holdingsValued ? "Value of the holdings on file" : p._aum != null ? "The AUM you entered" : "No holdings on file" },
  ];

  return (
    <>
      <div className="flex flex-wrap items-center" style={{ gap: 8 }}>
        <Btn data-testid="client360-open" variant="primary" disabled={opening} onClick={() => session.openClient(p)}>
          {session.openingId === p.profile_id ? "Opening…" : isSelf ? "Open your portfolio in Copilot" : "Open in Copilot"}
        </Btn>
        <Btn data-testid="client360-open-plan" disabled={opening} onClick={() => session.openClient(p, "page/plan")}>{isSelf ? "Open your action plan" : "Open their action plan"}</Btn>
        <ExportHoldings profileId={p.profile_id} />
      </div>

      <Tiles items={tiles} />

      <div className="grid" style={{ gridTemplateColumns: "repeat(auto-fit,minmax(min(100%,320px),1fr))", gap: 12, alignItems: "start" }}>
        <Standing p={p} />
        <Attention profileId={p.profile_id} />
      </div>

      {!isSelf && (
        <AskChips
          title="Ask about this client"
          items={[{ label: `Draft a review for ${p.name}`, query: `Draft a portfolio review for my client ${p.name}: what changed, the top issue and the recommended next step.` }]}
        />
      )}

      <Value profileId={p.profile_id} />
      <Gains profileId={p.profile_id} />
      <History profileId={p.profile_id} />

      <div className="grid" style={{ gridTemplateColumns: "repeat(auto-fit,minmax(min(100%,320px),1fr))", gap: 12, alignItems: "start" }}>
        <Requests profileId={p.profile_id} />
        <Shared profileId={p.profile_id} />
      </div>

      <Notes profileId={p.profile_id} />

      <NotConnected
        testId="client360-actions-not-connected"
        title="Notes, statement requests, call logs and review packs can’t be started from here yet"
        body="This screen reads what is already on file for the client. Writing a note, sending the client a link to share their statement, logging a call and preparing a review pack are not available in the Copilot yet."
        needs={[
          "Save a note: PUT /api/mfd/profiles/{id}/notes exists and replaces every field, so a form must send all five back",
          "Request a statement: POST /api/mfd/profiles/{id}/cas-invite exists; the page the client opens (/cas-connect/<token>) is only in the older web app, not in v5",
          "Log a call: POST /api/mfd/profiles/{id}/call-log stores the call, but no endpoint reads call logs back",
          "Review pack: POST /api/mfd/profiles/{id}/review-pack/generate only stores a queued task; nothing produces the document",
        ]}
      />

      <Footnote>
        {reviewed ? `Last reviewed ${reviewed}` : "Not reviewed yet"} · scores refresh in the background once they are an hour old · opening a client sends their profile with every request, and the server checks it belongs to your workspace
      </Footnote>
    </>
  );
}

function Client360({ session }: { session: AdvisorSession }) {
  const { go } = useCopilotShell();
  const book = useAdvisorBook();
  const [params, setParams] = useSearchParams();
  const wanted = params.get("client") ?? "";

  /** Clients in the book's own order (highest priority first), then the advisor's own profile. */
  const people = useMemo<AdvisorProfile[]>(() => {
    const all = (book.data?.profiles ?? []).map(decorateProfile);
    return [...all.filter((p) => p.type !== "SELF"), ...all.filter((p) => p.type === "SELF")];
  }, [book.data]);

  const header = (title: ReactNode, pills?: ReactNode, sub?: ReactNode) => (
    <ScreenHeader eyebrow="Advisor · Client 360" pills={pills} title={title} sub={sub} />
  );

  if (book.isPending) {
    return <>{header("Client 360")}<LoadingBlock label="Loading your client book" rows={5} /></>;
  }
  if (book.isError) {
    return (
      <>
        {header("Client 360")}
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
  const wsType = parsedWs.success ? parsedWs.data.type : undefined;
  if (wsType && String(wsType).toUpperCase() !== "ADVISORY") return <NotAnAdvisor />;

  if (people.length === 0) {
    return (
      <>
        {header("Client 360")}
        <div data-testid="client360-empty">
          <EmptyBlock
            title="No clients in your book yet"
            body="Add a client in the advisor workspace. Once their holdings are in, their scores, value and statements appear here."
            action={<Btn onClick={() => go("advisor/workspace")}>Add a client in the advisor workspace ›</Btn>}
          />
        </div>
      </>
    );
  }

  const choose = (profileId: string) => setParams({ client: profileId }, { replace: true });
  // No client named in the address: the first in the book, as on the original page.
  const chosen = wanted ? people.find((p) => p.profile_id === wanted) ?? null : people[0];

  if (!chosen) {
    return (
      <>
        {header("Client 360")}
        <div data-testid="client360-unknown-client">
          <EmptyBlock
            title="That client is not in your book"
            body="The link names a client this account does not manage. They may have been removed, or the link belongs to another workspace."
            action={<ClientPicker people={people} value="" onChange={choose} />}
          />
        </div>
      </>
    );
  }

  const tier = wealthTier(chosen._aum);
  const reviewed = chosen.last_reviewed_at ? fmtDaysSince(chosen.last_reviewed_at) : null;
  return (
    <>
      {header(
        <span data-testid="client360-name">{chosen.name}</span>,
        <>
          {chosen.type === "SELF" && <Pill tone="indigo">Your own portfolio</Pill>}
          {tier && <Pill tone="mint" title={tier.means}>{tier.label}</Pill>}
        </>,
        <>{fmtINR(chosen._aum, { compact: true })} in assets · {reviewed ? `reviewed ${reviewed}` : "not reviewed yet"}. Read where this client stands, then open them in the Copilot to work on their plan.</>,
      )}
      {people.length > 1 && <ClientPicker people={people} value={chosen.profile_id} onChange={choose} />}
      <Detail key={chosen.profile_id} p={chosen} session={session} />
    </>
  );
}

export default function Client360Screen() {
  const session = useAdvisorSession();
  return (
    <Screen testId="screen-advisor-client-360" width={1000}>
      <AdvisorOnly session={session}>
        <Client360 session={session} />
      </AdvisorOnly>
    </Screen>
  );
}
