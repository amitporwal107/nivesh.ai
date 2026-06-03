import { useState } from "react";
import { RefreshCw, Loader2, Sparkles, ChevronDown, ChevronRight } from "lucide-react";
import { Card, CardContent, CardLabel } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { http } from "@/services/api/http";
import { NidpError } from "./NidpError";
import { useQuery } from "@tanstack/react-query";

interface Expectation {
  type: string;
  column: string | null;
  columns: string[] | null;
  kwargs: Record<string, unknown>;
}
interface FeedExpectations {
  feed: string;
  suite_name: string;
  expectations: Expectation[];
}
interface ExpectationsData {
  feeds_total: number;
  expectations_total: number;
  feeds: Record<string, FeedExpectations>;
  doc_url?: string;
  spec_source?: string;
}

function shortType(type: string): string {
  return type.replace("expect_", "").replace(/_/g, " ");
}

export function ExpectationsPanel() {
  const [expanded, setExpanded] = useState<string | null>(null);
  const [search, setSearch] = useState("");

  const { data, isFetching, refetch, error } = useQuery({
    queryKey: ["nidp", "expectations"],
    queryFn: () => http<ExpectationsData>({ path: "/api/admin/nidp/quality/expectations", timeoutMs: 20_000 }).then((r) => r.data),
    staleTime: 10 * 60_000,
  });

  const feeds = Object.entries(data?.feeds ?? {}).filter(([name]) =>
    !search || name.toLowerCase().includes(search.toLowerCase())
  );

  return (
    <Card>
      <CardContent className="p-5">
        <div className="flex items-center justify-between mb-4">
          <div className="flex items-center gap-3">
            <div className="w-10 h-10 rounded-lg bg-accent-soft flex items-center justify-center">
              <Sparkles className="w-5 h-5 text-accent" />
            </div>
            <div>
              <h2 className="text-base font-semibold text-ink">Quality Expectations</h2>
              <p className="text-xs text-ink-3">
                {data ? `${data.feeds_total} feeds · ${data.expectations_total} expectations` : "Business rules applied per ingester run"}
              </p>
            </div>
          </div>
          <Button size="sm" variant="outline" onClick={() => refetch()} disabled={isFetching}>
            {isFetching ? <Loader2 className="w-3.5 h-3.5 animate-spin" /> : <RefreshCw className="w-3.5 h-3.5" />}
          </Button>
        </div>

        {error && <div className="mb-4"><NidpError err={error} /></div>}

        {/* Search */}
        {feeds.length > 5 && (
          <input
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            placeholder="Filter feeds…"
            className="w-full mb-3 rounded-md border border-hairline-2 bg-surface-1 px-3 py-1.5 text-sm text-ink placeholder:text-ink-3 focus:outline-none focus:ring-1 focus:ring-accent"
          />
        )}

        <div className="space-y-1">
          {feeds.map(([feedName, feedData]) => {
            const isExp = expanded === feedName;
            return (
              <div key={feedName} className="rounded-lg border border-hairline overflow-hidden">
                <button
                  className="w-full flex items-center gap-2 px-3 py-2.5 text-left hover:bg-surface-1 transition-colors"
                  onClick={() => setExpanded(isExp ? null : feedName)}
                >
                  {isExp ? <ChevronDown className="w-3.5 h-3.5 text-ink-3 shrink-0" /> : <ChevronRight className="w-3.5 h-3.5 text-ink-3 shrink-0" />}
                  <span className="font-mono text-sm text-ink flex-1">{feedName}</span>
                  <Badge tone="default">{feedData.expectations.length} rules</Badge>
                  <span className="text-[10px] text-ink-3 hidden sm:inline">{feedData.suite_name}</span>
                </button>

                {isExp && (
                  <div className="border-t border-hairline divide-y divide-hairline max-h-72 overflow-y-auto">
                    {feedData.expectations.map((exp, i) => {
                      const colLabel = exp.column
                        ? exp.column
                        : exp.columns?.join(", ") ?? "table";
                      return (
                        <div key={i} className="flex items-center gap-3 px-4 py-2 text-xs">
                          <code className="text-accent font-mono text-[10px] shrink-0 min-w-0 max-w-[200px] truncate">{shortType(exp.type)}</code>
                          <span className="text-ink-3 truncate flex-1">on <strong className="text-ink-2">{colLabel}</strong></span>
                          {Object.entries(exp.kwargs)
                            .filter(([k]) => !["column", "columns"].includes(k))
                            .slice(0, 2)
                            .map(([k, v]) => (
                              <span key={k} className="text-[10px] text-ink-3 shrink-0 hidden md:inline">
                                {k}={JSON.stringify(v).slice(0, 20)}
                              </span>
                            ))}
                        </div>
                      );
                    })}
                  </div>
                )}
              </div>
            );
          })}
          {!isFetching && feeds.length === 0 && !error && (
            <div className="text-center text-sm text-ink-3 py-8">No expectations data returned.</div>
          )}
        </div>

        {data?.doc_url && (
          <div className="mt-4 text-xs text-ink-3">
            Spec: <a href={data.doc_url} target="_blank" rel="noreferrer" className="text-accent hover:underline">{data.spec_source ?? data.doc_url}</a>
          </div>
        )}
      </CardContent>
    </Card>
  );
}
