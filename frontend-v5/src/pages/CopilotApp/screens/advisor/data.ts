/**
 * Advisor screens (Client book, Client 360, SIP board) — validated reads for
 * the advisor endpoints no shared hook reads, or that the shared adapter
 * cannot read safely:
 *
 *   GET /api/mfd/profiles/{id}/needs-attention    useClientAttention
 *   GET /api/mfd/profiles/{id}/portfolio-trend    useClientTrend
 *   GET /api/mfd/profiles/{id}/tax-summary        useClientTax
 *   GET /api/mfd/profiles/{id}/notes              useClientNotes
 *   GET /api/portfolio/cas-snapshots?profile_id=  useClientStatements
 *   GET /api/mfd/profiles/{id}/cas-uploads        useClientSharedFiles
 *   GET /api/mfd/profiles/{id}/cas-invites        useClientStatementRequests
 *   GET /api/advisor/sip-board                    useSipQueues
 *   GET /api/advisor/sip-board/summary            useSipSummary
 *   GET /api/mfd/profiles/{id}/holdings/export    downloadClientHoldings
 *   GET /api/mfd/cas-uploads/{file_id}/download   downloadSharedStatement
 *
 * Why not the shared hooks for three of these:
 *   - useNeedsAttention's contract requires a `type` on every item, which the
 *     server never sends (it sends item_id / title / subtitle / severity), so
 *     any answer with an item in it is rejected.
 *   - useSipBoard and useSipBoardSummary turn whatever comes back, even `{}`,
 *     into empty queues and zeros, which a screen would show as "no SIPs".
 *
 * Every fetcher returns a complete typed value or throws
 * ApiError("contract_drift"), so the screen shows its error state. Shapes are
 * the route handlers' own (backend/routes/mfd.py, advisor_v4.py,
 * client_cas_invite.py, cas_snapshots.py, portfolio_export.py).
 *
 * Units: money is RUPEES; percentages are in percent units (12.4 = 12.4%).
 */
import { useQuery } from "@tanstack/react-query";
import { z } from "zod";
import { apiFetch } from "@/services/api/authed-fetch";
import { ApiError } from "@/services/api/errors";
import { http } from "@/services/api/http";

// ── primitives ───────────────────────────────────────────────────────────

const optStr = z.string().nullable().optional();
const optNum = z.number().nullable().optional();

async function read<S extends z.ZodTypeAny>(
  what: string,
  schema: S,
  req: { path: string; query?: Record<string, string | number | boolean | undefined>; signal?: AbortSignal },
): Promise<z.infer<S>> {
  const res = await http(req);
  const parsed = schema.safeParse(res.data);
  if (!parsed.success) throw ApiError.contractDrift(`${what}: ${parsed.error.message}`);
  return parsed.data;
}

const profilePath = (profileId: string, tail: string) => `/api/mfd/profiles/${encodeURIComponent(profileId)}/${tail}`;

/** "risk_diversification" / "DETAILS_CAPTURED" → "Risk diversification" / "Details captured". */
export function humanise(id: string | null | undefined): string {
  const s = (id ?? "").replace(/[_-]+/g, " ").trim().toLowerCase();
  return s ? s.charAt(0).toUpperCase() + s.slice(1) : "";
}

// ── what a holding name is: a fund, a stock, or something else ───────────

export type AssetKind = "fund" | "stock" | "other";

const FUND_TYPES = new Set(["mutual_fund", "mutual fund", "mf", "etf", "fund"]);
const STOCK_TYPES = new Set(["equity", "stock", "stocks", "equities", "share", "shares"]);

/** A scheme name says what it is ("… Fund - Direct Growth", "… Nifty 50 ETF"). */
const FUND_WORDS = /\b(fund|scheme|etf|fof|idcw|growth plan|direct plan|regular plan|direct growth|regular growth)\b/i;

/**
 * Which icon a holding's name gets. The asset type decides when the server
 * sends one; without it, only a name that reads as a scheme is called a fund
 * (a bare name could be a stock, a bond or "Your portfolio").
 */
export function assetKind(assetType: string | null | undefined, name: string): AssetKind {
  const t = (assetType ?? "").trim().toLowerCase();
  if (FUND_TYPES.has(t)) return "fund";
  if (STOCK_TYPES.has(t)) return "stock";
  if (!t && FUND_WORDS.test(name)) return "fund";
  return "other";
}

// ── needs attention ──────────────────────────────────────────────────────

const AttentionItemC = z.object({
  item_id: optStr,
  title: optStr,
  subtitle: optStr,
  source_domain: optStr,
  severity: optStr,
  discuss_status: optStr,
  // the older contract's names, still accepted
  type: optStr,
  priority: optStr,
  message: optStr,
  holding_name: optStr,
}).passthrough();

const AttentionRes = z.union([
  z.array(AttentionItemC),
  z.object({ items: z.array(AttentionItemC) }).passthrough(),
]);

export interface AttentionItem {
  id: string;
  /** What it is about — usually the holding's name. */
  title: string;
  /** Area and reason, as the plan wrote them. */
  detail: string;
  discussed: boolean;
}

function toAttention(raw: z.infer<typeof AttentionRes>): AttentionItem[] {
  const items = Array.isArray(raw) ? raw : raw.items;
  return items.flatMap((it, i) => {
    const title = (it.title || it.holding_name || it.message || humanise(it.type)).trim();
    if (!title) return [];
    // The server writes "<Area> · <reason>" and leaves the separator behind when there is no reason.
    const detail = (it.subtitle ?? (it.holding_name ? it.message ?? "" : "")).replace(/\s*·\s*$/, "").trim();
    return [{ id: it.item_id || `${i}-${title}`, title, detail, discussed: (it.discuss_status ?? "").toUpperCase() === "DISCUSSED" }];
  });
}

export function useClientAttention(profileId: string) {
  return useQuery({
    queryKey: ["advisor", "client", profileId, "attention"],
    queryFn: async ({ signal }) => toAttention(await read("needs-attention", AttentionRes, { path: profilePath(profileId, "needs-attention"), signal })),
    enabled: !!profileId,
  });
}

// ── value and recent purchases ───────────────────────────────────────────

const TrendRes = z.object({
  invested_rs: z.number(),
  current_rs: z.number(),
  absolute_change_rs: z.number(),
  percent_change: z.number().nullable(),
  recent_buys: z.array(z.object({
    name: optStr,
    asset_type: optStr,
    quantity: optNum,
    value_rs: optNum,
    buy_date: optStr,
  }).passthrough()),
}).passthrough();
export type ClientTrend = z.infer<typeof TrendRes>;

export function useClientTrend(profileId: string) {
  return useQuery({
    queryKey: ["advisor", "client", profileId, "trend"],
    queryFn: ({ signal }) => read("portfolio-trend", TrendRes, { path: profilePath(profileId, "portfolio-trend"), signal }),
    enabled: !!profileId,
  });
}

// ── unrealised gains ─────────────────────────────────────────────────────

const TaxRes = z.object({
  total_invested_rs: z.number(),
  total_current_rs: z.number(),
  total_unrealized_rs: z.number(),
  stcg_rs: z.number(),
  ltcg_rs: z.number(),
  undated_gain_rs: z.number(),
  undated_count: optNum,
  est_tax_if_realized_rs: optNum,
  ltcg_exemption_remaining: optNum,
  /** Share of lots that have a purchase date, so can be called short- or long-term. */
  coverage_pct: optNum,
  biggest_positions: z.array(z.object({
    name: optStr,
    asset_type: optStr,
    ticker: optStr,
    gain: optNum,
    bucket: optStr,
    days_held: optNum,
  }).passthrough()).optional(),
  lot_coverage: z.object({ cas_quality: optStr }).passthrough().nullable().optional(),
  /** The rates the estimate used, as the server words them. */
  regime: z.object({ equity_stcg: optStr, equity_ltcg: optStr, debt_post_apr_2023: optStr }).passthrough().nullable().optional(),
  /** The slab rate assumed for debt gains, as a fraction (0.3 = 30%). */
  user_slab_rate: optNum,
}).passthrough();
export type ClientTax = z.infer<typeof TaxRes>;

export function useClientTax(profileId: string) {
  return useQuery({
    queryKey: ["advisor", "client", profileId, "tax"],
    queryFn: ({ signal }) => read("tax-summary", TaxRes, { path: profilePath(profileId, "tax-summary"), signal }),
    enabled: !!profileId,
  });
}

/** How a lot's gain would be taxed, in plain words. */
export function taxBucketLabel(bucket: string | null | undefined): string {
  switch (bucket) {
    case "equity_stcg": return "Short-term · equity";
    case "equity_ltcg": return "Long-term · equity";
    case "debt_slab": return "Taxed at slab rate";
    case "debt_ltcg_legacy": return "Long-term · debt bought before April 2023";
    case "undated": return "No purchase date";
    default: return humanise(bucket) || "—";
  }
}

// ── notes ────────────────────────────────────────────────────────────────

const NotesRes = z.object({
  note: z.string().nullable(),
  sip_amount_rs: z.number().nullable(),
  sip_frequency: z.string().nullable(),
  next_sip_due: z.string().nullable(),
  preferred_channel: z.string().nullable(),
  updated_at: z.string().nullable(),
}).passthrough();

export function useClientNotes(profileId: string) {
  return useQuery({
    queryKey: ["advisor", "client", profileId, "notes"],
    queryFn: ({ signal }) => read("notes", NotesRes, { path: profilePath(profileId, "notes"), signal }),
    enabled: !!profileId,
  });
}

// ── portfolio snapshots on file (one per imported statement, plus daily ones) ──

const StatementsRes = z.object({
  count: z.number().optional(),
  snapshots: z.array(z.object({
    snapshot_date: z.string(),
    total_value: optNum,
    total_invested: optNum,
    return_pct: optNum,
    health_score: optNum,
    grade: optStr,
    holdings_count: optNum,
    trigger: optStr,
    statement_period_start: optStr,
    statement_period_end: optStr,
  }).passthrough()),
}).passthrough();
export type ClientStatement = z.infer<typeof StatementsRes>["snapshots"][number];

export function useClientStatements(profileId: string) {
  return useQuery({
    queryKey: ["advisor", "client", profileId, "statements"],
    queryFn: ({ signal }) => read("cas-snapshots", StatementsRes, { path: "/api/portfolio/cas-snapshots", query: { profile_id: profileId }, signal }),
    enabled: !!profileId,
  });
}

/** How a snapshot came to be, in plain words (values: backend/services/portfolio_snapshot.py). */
export function statementSource(trigger: string | null | undefined): string {
  switch ((trigger ?? "").toLowerCase()) {
    case "cas_upload": return "Statement upload";
    case "eod_cron": return "Daily snapshot";
    case "manual": return "Entered by hand";
    default: return humanise(trigger) || "—";
  }
}

// ── statements the client shared through a request link ──────────────────

const SharedFilesRes = z.object({
  files: z.array(z.object({
    file_id: z.string(),
    filename: optStr,
    source: optStr,
    status: optStr,
    holdings_count: optNum,
    error: optStr,
    stored_at: optStr,
    period_start: optStr,
    period_end: optStr,
    transactions_count: optNum,
    statement_type: optStr,
    is_downloadable: z.boolean().optional(),
  }).passthrough()),
  count: z.number().optional(),
}).passthrough();
export type SharedFile = z.infer<typeof SharedFilesRes>["files"][number];

export function useClientSharedFiles(profileId: string) {
  return useQuery({
    queryKey: ["advisor", "client", profileId, "shared-files"],
    queryFn: ({ signal }) => read("cas-uploads", SharedFilesRes, { path: profilePath(profileId, "cas-uploads"), signal }),
    enabled: !!profileId,
  });
}

/** What kind of statement a shared file turned out to be. */
export function statementTypeLabel(type: string | null | undefined): string {
  switch (type) {
    case "detailed": return "Detailed · with transactions";
    case "partial": return "Partial transaction history";
    case "summary_or_demat": return "Summary · no transactions";
    default: return "";
  }
}

const RequestsRes = z.object({
  invites: z.array(z.object({
    // The token is the secret half of the client's link: it is used as a row
    // key only and is never shown.
    invite_token: z.string(),
    status: optStr,
    created_at: optStr,
    expires_at: optStr,
    completed_at: optStr,
    processed_files: z.array(z.unknown()).nullable().optional(),
  }).passthrough()),
}).passthrough();

export function useClientStatementRequests(profileId: string) {
  return useQuery({
    queryKey: ["advisor", "client", profileId, "statement-requests"],
    queryFn: ({ signal }) => read("cas-invites", RequestsRes, { path: profilePath(profileId, "cas-invites"), signal }),
    enabled: !!profileId,
  });
}

export type RequestTone = "mint" | "amber" | "ink";

/** Where a statement request stands (status values: backend/routes/client_cas_invite.py). */
export function requestStatus(status: string | null | undefined): { label: string; tone: RequestTone } {
  switch ((status ?? "").toUpperCase()) {
    case "PENDING": return { label: "Waiting for the client", tone: "amber" };
    case "DETAILS_CAPTURED": return { label: "Client has opened it", tone: "amber" };
    case "AUTHORIZED": return { label: "Client signed in", tone: "amber" };
    case "COMPLETED": return { label: "Statements received", tone: "mint" };
    case "EXPIRED": return { label: "Expired", tone: "ink" };
    case "REVOKED": return { label: "Cancelled", tone: "ink" };
    default: return { label: humanise(status) || "Unknown", tone: "ink" };
  }
}

// ── SIP board ────────────────────────────────────────────────────────────

const SipRowC = z.object({
  sip_id: optStr,
  profile_id: optStr,
  client_name: optStr,
  fund_name: optStr,
  amount_rs: optNum,
  cadence: optStr,
  state: optStr,
  mandate_expiry_date: optStr,
  last_bounce_reason: optStr,
  last_bounce_date: optStr,
  cycles_missed: optNum,
  next_debit_date: optStr,
  proposed_stepup_pct: optNum,
}).passthrough();
export type SipRow = z.infer<typeof SipRowC>;

export const SIP_QUEUES = ["failed", "expiring", "step_up", "healthy"] as const;
export type SipQueue = (typeof SIP_QUEUES)[number];

const SipBoardRes = z.object({
  /** "YYYY-MM". */
  cycle: z.string(),
  queues: z.object({
    failed: z.array(SipRowC),
    expiring: z.array(SipRowC),
    step_up: z.array(SipRowC),
    healthy: z.array(SipRowC),
  }).passthrough(),
}).passthrough();

export function useSipQueues() {
  return useQuery({
    queryKey: ["advisor", "sip-board", "queues"],
    queryFn: ({ signal }) => read("sip-board", SipBoardRes, { path: "/api/advisor/sip-board", signal }),
  });
}

const SipSummaryRes = z.object({
  cycle: z.string().optional(),
  monthly_inflow_rs: z.number(),
  active_sips_count: z.number(),
  failed_count: z.number(),
  mandate_at_risk_count: z.number(),
}).passthrough();

export function useSipSummary() {
  return useQuery({
    queryKey: ["advisor", "sip-board", "validated-summary"],
    queryFn: ({ signal }) => read("sip-board summary", SipSummaryRes, { path: "/api/advisor/sip-board/summary", signal }),
  });
}

/** "2026-10" → "October 2026"; anything else comes back unchanged. */
export function cycleLabel(cycle: string): string {
  const m = /^(\d{4})-(\d{2})$/.exec(cycle);
  if (!m) return cycle;
  return new Date(+m[1], +m[2] - 1, 1).toLocaleDateString("en-IN", { month: "long", year: "numeric" });
}

// ── downloads ────────────────────────────────────────────────────────────

/** Fetch a file with the signed-in session and hand it to the browser as a download. */
async function download(path: string, fallbackName: string): Promise<void> {
  const res = await apiFetch(path);
  if (!res.ok) {
    let body: unknown;
    try {
      body = await res.json();
    } catch {
      body = undefined; // an error page without a JSON body: the status alone names the failure
    }
    throw ApiError.fromResponse(res, body);
  }
  const blob = await res.blob();
  const name = /filename="?([^";]+)"?/.exec(res.headers.get("content-disposition") ?? "")?.[1] ?? fallbackName;
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = name;
  document.body.appendChild(a);
  a.click();
  a.remove();
  URL.revokeObjectURL(url);
}

export type HoldingsFormat = "xlsx" | "csv";

/** A client's holdings as a spreadsheet. Rejects with a 404 ApiError when the client has none. */
export function downloadClientHoldings(profileId: string, format: HoldingsFormat): Promise<void> {
  return download(`${profilePath(profileId, "holdings/export")}?format=${format}`, `holdings.${format}`);
}

/** The statement PDF a client shared, as they sent it. */
export function downloadSharedStatement(fileId: string, filename: string | null | undefined): Promise<void> {
  return download(`/api/mfd/cas-uploads/${encodeURIComponent(fileId)}/download`, filename || "statement.pdf");
}
