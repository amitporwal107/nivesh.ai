import type { ISODate } from "./common";

export interface SectorAllocation {
  name: string;                     // "Financials"
  pct: number;                      // 0..100
  capPct: number;                   // policy cap, e.g. 25
  isOverCap: boolean;
}

export interface ConcentrationSnapshot {
  asOf: ISODate;
  topStockPct: number;              // single largest stock %
  topStockName: string;
  sectorOverCount: number;          // sectors above policy cap
  sectors: SectorAllocation[];
  herfindahl: number;               // HHI index 0..10000
}
