/**
 * FLOW LEDGER auto-fill service.
 *
 *   GET /api/flows/ledger/company/{symbol}  → LedgerFill
 *   GET /api/flows/ledger/sector/{sector}   → LedgerFill
 *   GET /api/flows/ledger/sectors           → SectorOption[]
 *
 * The API returns the tracker's INPUT FIELDS, not a verdict. The scoring — quarter
 * weights, the consistency bonus, the composite renormalised over filled streams —
 * stays in the page, as the single implementation. A server-computed score would be
 * a second one to drift against.
 *
 * A stream NIDP cannot source arrives with `filled: false` and a sentence saying
 * why. Those must be surfaced, never defaulted: the tracker excludes unfilled
 * streams and renormalises, so a fabricated neutral would dilute the real ones.
 */
import { http } from "@/services/api/http";

/** Mirrors the tracker's own field names so a fill can be applied directly. */
export interface LedgerInputs {
  fiiQ?: string[];
  diiQ?: string[];
  deal?: string;
  repeatSeller?: boolean;
  delivBase?: string;
  delivDown?: string;
  mf?: string;
  fo?: string;
  ftDir?: string;
  ftN?: string;
  auc?: string;
  idx?: string;
  breadth?: string;
  rs?: string;
}

export interface LedgerStream {
  tag: string;
  weight: number;
  title: string;
  filled: boolean;
  evidence: string | null;
  unavailable_reason: string | null;
  source_dataset: string | null;
}

export interface LedgerFill {
  mode: "company" | "sector";
  name: string;
  index_used?: string | null;
  as_of?: string | null;
  inputs: LedgerInputs;
  streams: LedgerStream[];
  filled_weight: number;
  total_weight: number;
}

export interface SectorOption {
  sector: string;
  symbols: number;
  index_used: string | null;
  relative_strength_available: boolean;
}

export async function fetchCompanyLedger(symbol: string): Promise<LedgerFill> {
  const res = await http<LedgerFill>({
    path: `/api/flows/ledger/company/${encodeURIComponent(symbol.trim().toUpperCase())}`,
    timeoutMs: 30_000,
  });
  return res.data;
}

export async function fetchSectorLedger(sector: string): Promise<LedgerFill> {
  const res = await http<LedgerFill>({
    path: `/api/flows/ledger/sector/${encodeURIComponent(sector.trim())}`,
    timeoutMs: 30_000,
  });
  return res.data;
}

export async function fetchLedgerSectors(): Promise<SectorOption[]> {
  const res = await http<{ sectors: SectorOption[] }>({
    path: "/api/flows/ledger/sectors",
    timeoutMs: 30_000,
  });
  return res.data?.sectors ?? [];
}
