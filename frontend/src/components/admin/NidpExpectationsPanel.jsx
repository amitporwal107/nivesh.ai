import React, { useEffect, useMemo, useState } from "react";
import axios from "axios";
import {
  ShieldCheck, FileSearch, ChevronDown, ChevronRight,
  Loader2, AlertTriangle, BookOpen,
} from "lucide-react";

const API = process.env.REACT_APP_BACKEND_URL;

/**
 * Read-only documentation of every Great-Expectations suite that the
 * NIDP quality_gate runs. Lists each feed's expectations with column
 * + kwargs so MFD/data-engineering teams can see exactly what's being
 * checked nightly, without having to read code.
 */
export default function NidpExpectationsPanel() {
  const [data, setData]       = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError]     = useState(null);
  const [filter, setFilter]   = useState("");
  const [expanded, setExpanded] = useState({});

  useEffect(() => {
    let cancelled = false;
    (async () => {
      setLoading(true);
      setError(null);
      try {
        const r = await axios.get(
          `${API}/api/admin/nidp/quality/expectations`,
          { withCredentials: true },
        );
        if (!cancelled) setData(r.data);
      } catch (e) {
        if (!cancelled) setError(e?.response?.data?.detail || e.message);
      } finally {
        if (!cancelled) setLoading(false);
      }
    })();
    return () => { cancelled = true; };
  }, []);

  const feeds = useMemo(() => {
    if (!data?.feeds) return [];
    const q = filter.trim().toLowerCase();
    return Object.entries(data.feeds)
      .map(([name, s]) => ({ name, ...s }))
      .filter(f => !q
        || f.name.toLowerCase().includes(q)
        || f.suite_name.toLowerCase().includes(q)
        || (f.expectations || []).some(e =>
          (e.type || "").toLowerCase().includes(q) ||
          (e.column || "").toLowerCase().includes(q)
        ))
      .sort((a, b) => a.name.localeCompare(b.name));
  }, [data, filter]);

  const toggle = (feedName) =>
    setExpanded(s => ({ ...s, [feedName]: !s[feedName] }));

  const expandAll = () => {
    const all = {}; feeds.forEach(f => { all[f.name] = true; });
    setExpanded(all);
  };
  const collapseAll = () => setExpanded({});

  return (
    <section
      data-testid="nidp-expectations-panel"
      className="rounded-2xl border border-slate-100 dark:border-slate-700 bg-white dark:bg-slate-800 p-5"
    >
      <div className="flex items-start justify-between gap-4 mb-4">
        <div>
          <h3 className="flex items-center gap-2 text-base font-semibold text-slate-900 dark:text-white">
            <BookOpen className="w-4 h-4 text-indigo-600" />
            Great-Expectations Suites
            {data && (
              <span className="text-slate-400 font-normal text-sm">
                · {data.feeds_total} feeds · {data.expectations_total} expectations
              </span>
            )}
          </h3>
          <p className="text-xs text-slate-500 dark:text-slate-400 mt-1 max-w-2xl">
            Every per-feed expectation that <code>quality_gate</code> runs nightly. Failures land in
            <code className="mx-1">nidp.validation_findings</code>
            and feed the accuracy + completeness dimensions of the overall quality score.
            Source: <code>{data?.spec_source || "—"}</code>.
          </p>
        </div>
        <div className="flex items-center gap-2 shrink-0">
          <input
            type="search"
            value={filter}
            onChange={e => setFilter(e.target.value)}
            placeholder="filter feed / column / rule"
            data-testid="nidp-expectations-filter"
            className="rounded-md border border-slate-200 dark:border-slate-700 bg-white dark:bg-slate-900 text-slate-700 dark:text-slate-200 text-xs px-2.5 py-1.5 w-56"
          />
          <button
            onClick={expandAll}
            className="text-xs text-slate-500 hover:text-slate-800 dark:hover:text-slate-200 px-2 py-1.5"
          >
            Expand all
          </button>
          <button
            onClick={collapseAll}
            className="text-xs text-slate-500 hover:text-slate-800 dark:hover:text-slate-200 px-2 py-1.5"
          >
            Collapse
          </button>
        </div>
      </div>

      {loading && (
        <div className="flex items-center gap-2 text-xs text-slate-500 py-12 justify-center">
          <Loader2 className="w-4 h-4 animate-spin" /> Loading suites…
        </div>
      )}

      {error && (
        <div className="flex items-start gap-2 p-3 rounded text-xs text-rose-700 bg-rose-50 dark:bg-rose-900/20 dark:text-rose-300">
          <AlertTriangle className="w-4 h-4 shrink-0 mt-0.5" />
          <div>{String(error)}</div>
        </div>
      )}

      {!loading && !error && (
        <div className="grid grid-cols-1 lg:grid-cols-2 gap-3">
          {feeds.map(f => (
            <div
              key={f.name}
              data-testid={`nidp-expectations-feed-${f.name}`}
              className="rounded-lg border border-slate-100 dark:border-slate-700 bg-slate-50 dark:bg-slate-900/40"
            >
              <button
                onClick={() => toggle(f.name)}
                className="w-full text-left px-3 py-2 flex items-center justify-between hover:bg-slate-100 dark:hover:bg-slate-800/60"
              >
                <span className="flex items-center gap-2 min-w-0">
                  {expanded[f.name]
                    ? <ChevronDown  className="w-3 h-3 shrink-0 text-slate-400" />
                    : <ChevronRight className="w-3 h-3 shrink-0 text-slate-400" />}
                  <ShieldCheck className="w-3.5 h-3.5 text-emerald-600 shrink-0" />
                  <span className="font-mono text-xs text-slate-800 dark:text-slate-100 truncate">
                    {f.name}
                  </span>
                  <span className="text-[10px] uppercase tracking-wide text-slate-400 ml-2 shrink-0">
                    {f.suite_name}
                  </span>
                </span>
                <span className="text-[11px] text-slate-500 dark:text-slate-400 shrink-0">
                  {f.expectations.length} rule{f.expectations.length === 1 ? "" : "s"}
                </span>
              </button>

              {expanded[f.name] && (
                <div className="px-3 pb-3 space-y-1.5">
                  {f.expectations.map((e, idx) => (
                    <div
                      key={idx}
                      className="rounded px-2 py-1.5 bg-white dark:bg-slate-800 border border-slate-100 dark:border-slate-700"
                    >
                      <div className="flex items-baseline gap-2 flex-wrap">
                        <span className="font-mono text-[11px] text-indigo-700 dark:text-indigo-300">
                          {e.type}
                        </span>
                        {e.column && (
                          <span className="font-mono text-[11px] text-slate-500 dark:text-slate-400">
                            on <code>{e.column}</code>
                          </span>
                        )}
                        {!e.column && e.columns && (
                          <span className="font-mono text-[11px] text-slate-500 dark:text-slate-400">
                            on <code>{Array.isArray(e.columns) ? e.columns.join(", ") : e.columns}</code>
                          </span>
                        )}
                      </div>
                      {e.kwargs && Object.keys(e.kwargs).length > 0 && (
                        <div className="mt-1 text-[10.5px] font-mono text-slate-500 dark:text-slate-400 break-all">
                          {Object.entries(e.kwargs)
                            .filter(([k]) => k !== "column" && k !== "columns")
                            .map(([k, v]) =>
                              <span key={k} className="mr-2">
                                <span className="text-slate-400">{k}=</span>
                                <span className="text-slate-700 dark:text-slate-200">
                                  {typeof v === "object" ? JSON.stringify(v) : String(v)}
                                </span>
                              </span>
                            )}
                        </div>
                      )}
                    </div>
                  ))}
                </div>
              )}
            </div>
          ))}

          {feeds.length === 0 && (
            <div className="col-span-full text-xs text-slate-500 italic px-3 py-6">
              No feeds match <code>{filter}</code>.
            </div>
          )}
        </div>
      )}
    </section>
  );
}
