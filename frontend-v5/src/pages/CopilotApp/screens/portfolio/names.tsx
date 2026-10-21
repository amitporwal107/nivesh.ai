/**
 * Portfolio screens — the icon that sits beside a named holding: the company
 * icon for a stock, the fund house icon for a mutual fund or an ETF, nothing
 * for anything else (gold bonds, a category such as "corporate bond fund").
 *
 * What a name is comes from, in order:
 *   1. the type the endpoint sent with the row (asset_type);
 *   2. the user's own holdings, matched by name
 *      (GET /api/portfolio/holdings-enriched, the query every screen shares).
 * A name that is neither gets no icon; nothing is guessed from its wording.
 *
 * The tiles themselves are components/EntityIcon.tsx.
 */
import type { ReactNode } from "react";
import { useHoldingsEnriched } from "@/hooks/use-portfolio";
import { FundHouseIcon, StockIcon } from "../../components/EntityIcon";
import { str, type EnrichedHolding } from "./data";

export type EntityKind = "stock" | "fund" | "other";

/** "mutual_fund" | "etf" | "fund" → fund; "equity" | "stock" → stock; other types → other; nothing → null. */
export function kindOf(assetType: string | null | undefined): EntityKind | null {
  const t = (assetType ?? "").trim().toLowerCase().replace(/[\s-]+/g, "_");
  if (!t) return null;
  if (t === "mutual_fund" || t === "etf" || t === "mf" || t === "fund") return "fund";
  if (t === "equity" || t === "stock") return "stock";
  return "other";
}

export interface KnownHolding {
  kind: EntityKind;
  /** Exchange symbol of a stock; empty when the holding has none on record. */
  symbol: string;
}

const nameKey = (name: string): string => name.trim().toLowerCase().replace(/\s+/g, " ");

// One index per holdings array, however many rows ask for it.
const INDEX = new WeakMap<EnrichedHolding[], Map<string, KnownHolding>>();

function indexOf(holdings: EnrichedHolding[]): Map<string, KnownHolding> {
  let index = INDEX.get(holdings);
  if (!index) {
    index = new Map();
    for (const h of holdings) {
      index.set(nameKey(h.name), { kind: kindOf(h.asset_type) ?? "other", symbol: str(h.nse_symbol) });
    }
    INDEX.set(holdings, index);
  }
  return index;
}

/** Finds a name among the user's own holdings; null when it is not one of them (or they have not loaded). */
export function useHoldingLookup(): (name: string) => KnownHolding | null {
  const holdings = useHoldingsEnriched().data?.holdings;
  return (name) => (holdings ? indexOf(holdings).get(nameKey(name)) ?? null : null);
}

interface IconProps {
  name: string;
  /** The type the endpoint sent with this row, when it sent one. */
  assetType?: string | null;
  /** Exchange symbol, when the row carries one. */
  symbol?: string | null;
  size?: number;
  /** In a list: keep the icon's width empty when there is no icon, so the names line up. */
  reserve?: boolean;
}

/** The icon for a named stock or fund; renders nothing for any other name. */
export function HoldingIcon({ name, assetType, symbol, size = 24, reserve }: IconProps) {
  const lookup = useHoldingLookup();
  const known = lookup(name);
  const kind = kindOf(assetType) ?? known?.kind ?? null;
  if (kind === "stock") {
    // A stock with no symbol on record is keyed by its name, so it still gets its own tile.
    return <StockIcon symbol={str(symbol) || known?.symbol || name} name={name} size={size} />;
  }
  if (kind === "fund") return <FundHouseIcon name={name} size={size} />;
  return reserve ? <span aria-hidden="true" style={{ flex: "none", width: size, height: size }} /> : null;
}

/**
 * An icon, then whatever names the row. The name stays the caller's own
 * element, so a test id on it still reads as the bare name.
 */
export function Named({ icon, children }: { icon: ReactNode; children: ReactNode }) {
  return (
    <span className="flex items-center" style={{ gap: 10, minWidth: 0 }}>
      {icon}
      <span style={{ minWidth: 0, flex: "1 1 auto", overflow: "hidden", textOverflow: "ellipsis" }}>{children}</span>
    </span>
  );
}
