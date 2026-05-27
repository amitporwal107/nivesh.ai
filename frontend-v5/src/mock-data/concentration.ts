import type { ConcentrationSnapshot } from "@/types/concentration";

export const mockConcentration: ConcentrationSnapshot = {
  asOf: "2026-05-27",
  topStockPct: 8.0,
  topStockName: "HDFC Bank",
  sectorOverCount: 1,
  herfindahl: 1640,
  sectors: [
    { name: "Financials", pct: 32, capPct: 25, isOverCap: true },
    { name: "Technology", pct: 22, capPct: 25, isOverCap: false },
    { name: "Energy",     pct: 14, capPct: 25, isOverCap: false },
    { name: "Consumer",   pct: 11, capPct: 25, isOverCap: false },
    { name: "Pharma",     pct: 9,  capPct: 25, isOverCap: false },
    { name: "Auto",       pct: 7,  capPct: 25, isOverCap: false },
    { name: "Materials",  pct: 3,  capPct: 25, isOverCap: false },
    { name: "Cash",       pct: 2,  capPct: 25, isOverCap: false },
  ],
};
