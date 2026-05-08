/**
 * useLiveTape — shared hook returning the live Market Dashboard snapshot.
 *
 * Mounted in TodayStrategyCard + SectorHeatmap so both reflect what's
 * happening on the live NSE tape (intraday) on top of their daily-macro
 * data sources.
 *
 * Refreshes 60s during market hours, 5min after-hours.
 */
import { useEffect, useState, useMemo } from "react";
import axios from "axios";

const API = `${process.env.REACT_APP_BACKEND_URL}/api`;


/** Normalize sector names so daily-macro sectors (e.g. "OIL_GAS", "PSU_BANK")
 * can be matched against live-tape sectors ("Energy", "PSU Bank"). */
const norm = (s) => (s || "").toLowerCase().replace(/[^a-z]/g, "");


/** Best-effort match of macro-tilt sector → live sector. Daily-macro
 * has ~30 sectors (granular: AVIATION, PAINT, TYRES, GEMS), live tape
 * has 12 NSE sectoral indices (broad: Auto, Bank, IT, Pharma). Most
 * fine-grained macro sectors won't match — return null and the UI
 * gracefully omits the live chip. */
const SECTOR_ALIASES = {
  oil_gas:        "energy",
  oilgas:         "energy",
  oil_and_gas:    "energy",
  psu_bank:       "psubank",
  privatebank:    "bank",
  privatebanks:   "bank",
  banking:        "bank",
  pharma:         "pharma",
  pharmaceuticals: "pharma",
  it:             "it",
  itservices:     "it",
  technology:     "it",
  fmcg:           "fmcg",
  consumption:    "fmcg",
  metals:         "metal",
  metal:          "metal",
  steel:          "metal",
  realestate:     "realty",
  realty:         "realty",
  media:          "media",
  finance:        "financialservices",
  finserv:        "financialservices",
  financial:      "financialservices",
  auto:           "auto",
  automobile:     "auto",
  automobiles:    "auto",
  infra:          "infra",
  infrastructure: "infra",
};


export default function useLiveTape() {
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    let cancelled = false;
    const load = async () => {
      try {
        const r = await axios.get(`${API}/positional/market-dashboard`, { withCredentials: true });
        if (!cancelled) {
          setData(r.data);
          setLoading(false);
        }
      } catch {
        if (!cancelled) setLoading(false);
      }
    };
    load();
    const id = setInterval(load, 60_000);
    return () => { cancelled = true; clearInterval(id); };
  }, []);

  // Build a lookup: normalized macro sector name → live sector row
  const sectorByName = useMemo(() => {
    const map = new Map();
    if (!data?.sector_heatmap) return map;
    for (const s of data.sector_heatmap) {
      const k = norm(s.sector);
      if (k) map.set(k, s);
    }
    return map;
  }, [data]);

  /** Lookup a live row for a given daily-macro sector name. Returns null
   * if no reasonable match exists. */
  const lookupLiveSector = (sectorName) => {
    if (!sectorByName.size) return null;
    const k = norm(sectorName);
    if (!k) return null;
    const aliased = SECTOR_ALIASES[k] || k;
    return sectorByName.get(aliased)
        || sectorByName.get(k)
        // partial match — many daily sector names contain a live sector word
        || (() => {
          for (const [liveKey, row] of sectorByName.entries()) {
            if (k.includes(liveKey) || liveKey.includes(k)) return row;
          }
          return null;
        })();
  };

  return {
    loading,
    isLive:        Boolean(data?.is_live),
    fetchedAt:     data?.fetched_at,
    verdict:       data?.deploy_verdict,
    verdictReason: data?.verdict_reason,
    nifty:         data?.nifty,
    vix:           data?.vix,
    breadth:       data?.breadth,
    lookupLiveSector,
  };
}
