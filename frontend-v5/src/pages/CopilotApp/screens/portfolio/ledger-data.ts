/**
 * Portfolio ledger — what is on record behind the holdings, and the one write
 * the ledger makes.
 *
 *   GET /api/portfolio/holdings        useHoldingRecords   where each holding came from, and when
 *   GET /api/portfolio/cas-snapshots   useStatements       one row per imported statement
 *   GET /api/portfolio/transactions    useTransactions     transactions read from statements
 *   GET /api/portfolio/sips            useDetectedSips     SIPs detected in those transactions
 *   PUT /api/portfolio/holdings/{id}   useCorrectHolding   correct a holding's price, date or units
 *
 * The shared useHoldings and usePortfolioSips are not used: the first maps the
 * source of a holding away, and the second validates against a shape the
 * backend does not send (it expects `total_monthly_sip_rs`; the backend sends
 * `monthly_sip_outflow`), so it fails on every real response.
 *
 * As in ./data: a fetcher returns a complete typed value or throws
 * ApiError("contract_drift"). Money is RUPEES, percentages are percent units.
 */
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { portfolioService } from "@/services";
import { http } from "@/services/api/http";
import { ApiError } from "@/services/api/errors";
import { humanise, num, rec, str } from "./data";

// ── where each holding came from (GET /api/portfolio/holdings) ───────────

export interface HoldingRecord {
  /** How the row got here, as the backend tags it: "cas", "openalgo", …; empty when untagged. */
  source: string;
  /** Broker name on a row read from a broker account; empty otherwise. */
  broker: string;
  /** When the row was written (ISO); empty when not recorded. */
  recordedAt: string;
}

/**
 * The tags the backend writes today: "cas" (a statement import), "snapshot_load"
 * (an earlier statement made current again) and "openalgo" (a broker read,
 * which also names the broker). A row added by hand carries no tag, so it has
 * no source to name. Any other tag is shown as it is.
 */
export function sourceLabel(r: HoldingRecord | undefined): string {
  if (!r) return "";
  if (r.broker) return `Broker · ${r.broker}`;
  switch (r.source.toLowerCase()) {
    case "": return "";
    case "cas": return "CAS statement";
    case "snapshot_load": return "Earlier statement";
    case "openalgo": return "Broker account";
    default: return humanise(r.source);
  }
}

export async function fetchHoldingRecords(signal?: AbortSignal): Promise<Record<string, HoldingRecord>> {
  const data = (await http({ path: "/api/portfolio/holdings", signal })).data;
  if (!Array.isArray(data)) throw ApiError.contractDrift("portfolio.holdings: not a list");
  const out: Record<string, HoldingRecord> = {};
  for (const item of data) {
    const r = rec(item);
    const id = str(r?.holding_id);
    if (!r || !id) continue;
    out[id] = { source: str(r.source), broker: str(r.broker), recordedAt: str(r.uploaded_at) || str(r.created_at) };
  }
  return out;
}

/** Keyed by holding id. */
export function useHoldingRecords() {
  return useQuery<Record<string, HoldingRecord>>({
    queryKey: ["portfolio", "holdings", "records"],
    staleTime: 5 * 60_000,
    queryFn: ({ signal }) => fetchHoldingRecords(signal),
  });
}

// ── imported statements (GET /api/portfolio/cas-snapshots) ───────────────

export interface StatementRecord {
  /** Statement date, "YYYY-MM-DD". */
  date: string;
  valueRs: number | null;
  investedRs: number | null;
  /** Gain on invested money as of the statement. */
  returnPct: number | null;
  /** Portfolio health recorded with it, 0–100; null when it was not computed. */
  health: number | null;
  grade: string;
  holdings: number | null;
  /** What wrote the record: "cas_upload", "eod_cron", "manual", … */
  trigger: string;
}

export function triggerLabel(trigger: string): string {
  switch (trigger.toLowerCase()) {
    case "cas_upload": return "Statement import";
    case "eod_cron": return "Daily record";
    case "manual": return "Recorded by hand";
    case "": return "";
    default: return humanise(trigger);
  }
}

/** Newest first, as the backend sends them. */
export async function fetchStatements(signal?: AbortSignal): Promise<StatementRecord[]> {
  const data = rec((await http({ path: "/api/portfolio/cas-snapshots", signal })).data);
  if (!data || !Array.isArray(data.snapshots)) throw ApiError.contractDrift("portfolio.casSnapshots: missing `snapshots`");
  return data.snapshots.flatMap((item: unknown): StatementRecord[] => {
    const r = rec(item);
    const date = str(r?.snapshot_date);
    if (!r || !date) return [];
    return [{
      date,
      valueRs: num(r.total_value),
      investedRs: num(r.total_invested),
      returnPct: num(r.return_pct),
      health: num(r.health_score),
      grade: str(r.grade),
      holdings: num(r.holdings_count),
      trigger: str(r.trigger),
    }];
  });
}

export function useStatements() {
  return useQuery<StatementRecord[]>({
    queryKey: ["portfolio", "cas-snapshots"],
    staleTime: 5 * 60_000,
    queryFn: ({ signal }) => fetchStatements(signal),
  });
}

// ── transactions (GET /api/portfolio/transactions) ───────────────────────

export interface LedgerTxn {
  key: string;
  /** "YYYY-MM-DD". */
  date: string;
  scheme: string;
  folio: string;
  /** PURCHASE, SIP_PURCHASE, REDEMPTION, SWITCH_IN, SWITCH_OUT, DIVIDEND, CHARGE, OTHER. */
  type: string;
  amountRs: number | null;
  units: number | null;
  nav: number | null;
}

export interface Transactions {
  /** Newest first; the backend returns its latest 500. */
  rows: LedgerTxn[];
  /** Purchases and SIP instalments among those rows. */
  investedRs: number | null;
  redeemedRs: number | null;
}

const TXN_LABEL: Record<string, string> = {
  PURCHASE: "Purchase",
  SIP_PURCHASE: "SIP instalment",
  REDEMPTION: "Redemption",
  SWITCH_IN: "Switch in",
  SWITCH_OUT: "Switch out",
  DIVIDEND: "Dividend",
  CHARGE: "Charge or tax",
  OTHER: "Other",
};

export function txnLabel(type: string): string {
  return TXN_LABEL[type] ?? humanise(type);
}

export async function fetchTransactions(signal?: AbortSignal): Promise<Transactions> {
  const data = rec((await http({ path: "/api/portfolio/transactions", signal })).data);
  if (!data || !Array.isArray(data.transactions)) throw ApiError.contractDrift("portfolio.transactions: missing `transactions`");
  const rows = data.transactions.flatMap((item: unknown, i: number): LedgerTxn[] => {
    const r = rec(item);
    const date = str(r?.date);
    if (!r || !date) return [];
    return [{
      key: `${date}-${str(r.isin)}-${str(r.folio)}-${i}`,
      date,
      scheme: str(r.scheme_name),
      folio: str(r.folio),
      type: str(r.type).toUpperCase(),
      amountRs: num(r.amount),
      units: num(r.units),
      nav: num(r.nav),
    }];
  });
  return { rows, investedRs: num(data.total_invested), redeemedRs: num(data.total_redeemed) };
}

export function useTransactions() {
  return useQuery<Transactions>({
    queryKey: ["portfolio", "transactions"],
    staleTime: 5 * 60_000,
    queryFn: ({ signal }) => fetchTransactions(signal),
  });
}

// ── detected SIPs (GET /api/portfolio/sips) ──────────────────────────────

export interface DetectedSip {
  key: string;
  scheme: string;
  folio: string;
  /** "MONTHLY" | "QUARTERLY". */
  cadence: string;
  /** Typical instalment, rupees. */
  amountRs: number | null;
  instalments: number | null;
  firstDate: string;
  lastDate: string;
  totalInvestedRs: number | null;
  /** "ACTIVE" | "PAUSED". */
  status: string;
}

export interface DetectedSips {
  rows: DetectedSip[];
  active: number;
  /** Monthly outflow of the active ones (a quarterly SIP counts a third). */
  monthlyRs: number | null;
}

export async function fetchDetectedSips(signal?: AbortSignal): Promise<DetectedSips> {
  const data = rec((await http({ path: "/api/portfolio/sips", signal })).data);
  if (!data || !Array.isArray(data.sips)) throw ApiError.contractDrift("portfolio.sips: missing `sips`");
  const rows = data.sips.flatMap((item: unknown, i: number): DetectedSip[] => {
    const r = rec(item);
    const scheme = str(r?.scheme_name);
    if (!r || !scheme) return [];
    return [{
      key: `${str(r.isin) || scheme}-${str(r.folio)}-${i}`,
      scheme,
      folio: str(r.folio),
      cadence: str(r.cadence).toUpperCase(),
      amountRs: num(r.amount),
      instalments: num(r.instalment_count),
      firstDate: str(r.first_date),
      lastDate: str(r.last_date),
      totalInvestedRs: num(r.total_invested),
      status: str(r.status).toUpperCase(),
    }];
  });
  return {
    rows,
    active: num(data.active_count) ?? rows.filter((s) => s.status === "ACTIVE").length,
    monthlyRs: num(data.monthly_sip_outflow),
  };
}

export function useDetectedSips() {
  return useQuery<DetectedSips>({
    queryKey: ["portfolio", "sips", "detected"],
    staleTime: 5 * 60_000,
    queryFn: ({ signal }) => fetchDetectedSips(signal),
  });
}

// ── correct a holding (PUT /api/portfolio/holdings/{id}) ─────────────────

/** Only the fields being changed are sent; the backend leaves the rest alone. */
export interface HoldingCorrection {
  holdingId: string;
  /** Average buy price per unit, rupees. */
  buyPrice?: number;
  /** "YYYY-MM-DD". */
  buyDate?: string;
  quantity?: number;
}

export async function correctHolding(c: HoldingCorrection): Promise<void> {
  const body: Record<string, number | string> = {};
  if (c.buyPrice != null) body.buy_price = c.buyPrice;
  if (c.buyDate != null) body.buy_date = c.buyDate;
  if (c.quantity != null) body.quantity = c.quantity;
  if (Object.keys(body).length === 0) throw new Error("Nothing was changed.");
  const res = await http({ method: "PUT", path: `/api/portfolio/holdings/${encodeURIComponent(c.holdingId)}`, body, noRetry: true });
  if (str(rec(res.data)?.holding_id) !== c.holdingId) throw ApiError.contractDrift("portfolio.updateHolding: the saved holding was not returned");
}

const ENRICHED_KEY = ["portfolio", "enriched"] as const;

/**
 * Saves the correction, then reads the holdings again past the backend's
 * five-minute cache (the save does not clear it), so the figures on screen
 * are the corrected ones.
 */
export function useCorrectHolding() {
  const qc = useQueryClient();
  return useMutation<void, unknown, HoldingCorrection>({
    mutationFn: async (c) => {
      await correctHolding(c);
      qc.setQueryData(ENRICHED_KEY, await portfolioService.listHoldingsEnriched(true));
    },
    onSuccess: () => {
      // Everything else worked out from the holdings; the fresh holdings read stays as it is.
      void qc.invalidateQueries({ queryKey: ["portfolio"], predicate: (q) => q.queryKey[1] !== ENRICHED_KEY[1] });
      for (const queryKey of [["composition"], ["plans"], ["insights"]]) void qc.invalidateQueries({ queryKey });
    },
  });
}
