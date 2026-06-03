/**
 * Holdings filter state — shared between Composition Explorer, Benchmark donut,
 * Heatmap, and the Holdings table.
 *
 * State is kept in Zustand and mirrored to URL query params so filters survive
 * navigation and can be shared as a link (per UX decisions OQ-1 / Step 10).
 *
 * Usage:
 *   const { filter, setFilter, clearFilter } = useHoldingsFilter();
 *
 *   // In Composition Explorer (segment click):
 *   setFilter({ dimension: 'sector', value: 'Banking' });
 *
 *   // In Holdings table:
 *   const rows = filter ? holdings.filter(...) : holdings;
 *
 * The filter object is intentionally flat so components don't need to know
 * each other's internal state shape.
 */

import { useCallback, useEffect } from 'react';
import { useSearchParams } from 'react-router-dom';
import { create } from 'zustand';

export type HoldingsDimension = 'asset_class' | 'sector' | 'fund' | 'group' | 'amc';

export interface HoldingsFilter {
  dimension: HoldingsDimension;
  value: string;
  /** Human-readable label shown in the filter chip (defaults to value) */
  label?: string;
}

interface HoldingsFilterStore {
  filter: HoldingsFilter | null;
  setFilter: (f: HoldingsFilter | null) => void;
}

const useStore = create<HoldingsFilterStore>((set) => ({
  filter: null,
  setFilter: (f) => set({ filter: f }),
}));

const PARAM_DIM = 'hf_dim';
const PARAM_VAL = 'hf_val';
const PARAM_LBL = 'hf_lbl';

/**
 * Returns filter state + setFilter + clearFilter.
 * Automatically syncs to/from URL query params.
 */
export function useHoldingsFilter() {
  const [searchParams, setSearchParams] = useSearchParams();
  const { filter, setFilter: storeSet } = useStore();

  // On mount: hydrate from URL if present
  useEffect(() => {
    const dim = searchParams.get(PARAM_DIM) as HoldingsDimension | null;
    const val = searchParams.get(PARAM_VAL);
    if (dim && val) {
      storeSet({
        dimension: dim,
        value: val,
        label: searchParams.get(PARAM_LBL) ?? val,
      });
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const setFilter = useCallback(
    (f: HoldingsFilter | null) => {
      storeSet(f);
      setSearchParams(
        (prev) => {
          const next = new URLSearchParams(prev);
          if (f) {
            next.set(PARAM_DIM, f.dimension);
            next.set(PARAM_VAL, f.value);
            if (f.label && f.label !== f.value) next.set(PARAM_LBL, f.label);
            else next.delete(PARAM_LBL);
          } else {
            next.delete(PARAM_DIM);
            next.delete(PARAM_VAL);
            next.delete(PARAM_LBL);
          }
          return next;
        },
        { replace: true },
      );
    },
    [storeSet, setSearchParams],
  );

  const clearFilter = useCallback(() => setFilter(null), [setFilter]);

  return { filter, setFilter, clearFilter };
}
