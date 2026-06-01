import { useState } from "react";
import { RefreshCw, Loader2, Sparkles, Plus, X, Check, ChevronDown, ChevronRight } from "lucide-react";
import { Card, CardContent, CardLabel } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { http } from "@/services/api/http";
import { useToastStore } from "@/stores/toast.store";
import { useQuery, useQueryClient } from "@tanstack/react-query";

interface Expectation {
  id: string;
  feed_name: string;
  metric: string;
  operator: string;
  threshold: number;
  severity: "error" | "warn" | "info";
  ai_proposed?: boolean;
  status?: "active" | "pending" | "rejected";
}

const SEVERITY_TONE: Record<string, "neg" | "warm" | "default"> = { error: "neg", warn: "warm", info: "default" };

export function ExpectationsPanel() {
  const push = useToastStore((s) => s.push);
  const qc = useQueryClient();
  const [expanded, setExpanded] = useState<string | null>(null);
  const [generating, setGenerating] = useState<string | null>(null);

  const { data, isFetching, refetch } = useQuery({
    queryKey: ["nidp", "expectations"],
    queryFn: () => http<{ expectations: Expectation[]; feeds: string[] }>({ path: "/api/admin/nidp/expectations" }).then((r) => r.data).catch(() => ({ expectations: [], feeds: [] })),
    staleTime: 5 * 60_000,
  });

  const approve = async (id: string) => {
    try {
      await http({ method: "PATCH", path: `/api/admin/nidp/expectations/${id}`, body: { status: "active" } });
      push({ kind: "success", title: "Expectation approved" });
      qc.invalidateQueries({ queryKey: ["nidp", "expectations"] });
    } catch { push({ kind: "error", title: "Failed to approve" }); }
  };

  const reject = async (id: string) => {
    try {
      await http({ method: "PATCH", path: `/api/admin/nidp/expectations/${id}`, body: { status: "rejected" } });
      push({ kind: "warn", title: "Expectation rejected" });
      qc.invalidateQueries({ queryKey: ["nidp", "expectations"] });
    } catch { push({ kind: "error", title: "Failed to reject" }); }
  };

  const generateForFeed = async (feed: string) => {
    setGenerating(feed);
    try {
      await http({ method: "POST", path: `/api/admin/nidp/expectations/generate`, body: { feed_name: feed } });
      push({ kind: "success", title: `AI expectations generated for ${feed}` });
      qc.invalidateQueries({ queryKey: ["nidp", "expectations"] });
    } catch { push({ kind: "error", title: "Generation failed" }); }
    finally { setGenerating(null); }
  };

  const byFeed = (data?.expectations ?? []).reduce<Record<string, Expectation[]>>((acc, e) => {
    (acc[e.feed_name] ??= []).push(e); return acc;
  }, {});

  const pendingCount = (data?.expectations ?? []).filter((e) => e.ai_proposed && e.status === "pending").length;

  return (
    <Card>
      <CardContent className="p-5">
        <div className="flex items-center justify-between mb-4">
          <div className="flex items-center gap-3">
            <div className="w-10 h-10 rounded-lg bg-accent-soft flex items-center justify-center">
              <Sparkles className="w-5 h-5 text-accent" />
            </div>
            <div>
              <h2 className="text-base font-semibold text-ink">AI Expectations</h2>
              <p className="text-xs text-ink-3">CRUD on quality expectations · review AI-proposed rules · generate per feed.</p>
            </div>
          </div>
          <div className="flex items-center gap-2">
            {pendingCount > 0 && <Badge tone="warm">{pendingCount} pending review</Badge>}
            <Button size="sm" variant="outline" onClick={() => refetch()} disabled={isFetching}>
              {isFetching ? <Loader2 className="w-3.5 h-3.5 animate-spin" /> : <RefreshCw className="w-3.5 h-3.5" />}
            </Button>
          </div>
        </div>

        {/* Generate per feed */}
        {(data?.feeds ?? []).length > 0 && (
          <div className="mb-5">
            <CardLabel className="mb-2">Generate strict expectations</CardLabel>
            <div className="flex flex-wrap gap-2">
              {data!.feeds.map((feed) => (
                <button
                  key={feed}
                  onClick={() => generateForFeed(feed)}
                  disabled={generating === feed}
                  className="flex items-center gap-1.5 text-xs px-3 py-1.5 rounded-full border border-hairline text-ink-2 hover:bg-surface-2 transition-colors disabled:opacity-50"
                >
                  {generating === feed ? <Loader2 className="w-3 h-3 animate-spin" /> : <Sparkles className="w-3 h-3" />}
                  {feed}
                </button>
              ))}
            </div>
          </div>
        )}

        {/* Expectations by feed */}
        <div className="space-y-3">
          {Object.entries(byFeed).map(([feed, exps]) => {
            const isExp = expanded === feed;
            return (
              <div key={feed} className="rounded-lg border border-hairline overflow-hidden">
                <button className="w-full flex items-center gap-2 px-4 py-3 text-left hover:bg-surface-1 transition-colors" onClick={() => setExpanded(isExp ? null : feed)}>
                  {isExp ? <ChevronDown className="w-3.5 h-3.5 text-ink-3 shrink-0" /> : <ChevronRight className="w-3.5 h-3.5 text-ink-3 shrink-0" />}
                  <span className="font-mono text-sm text-ink flex-1">{feed}</span>
                  <span className="text-xs text-ink-3">{exps.length} rule{exps.length !== 1 ? "s" : ""}</span>
                  {exps.filter((e) => e.status === "pending").length > 0 && (
                    <Badge tone="warm">{exps.filter((e) => e.status === "pending").length} pending</Badge>
                  )}
                </button>
                {isExp && (
                  <div className="border-t border-hairline divide-y divide-hairline">
                    {exps.map((e) => (
                      <div key={e.id} className="flex items-center gap-3 px-4 py-2.5 text-xs">
                        <Badge tone={SEVERITY_TONE[e.severity] ?? "default"}>{e.severity}</Badge>
                        <span className="flex-1 text-ink-2 font-mono">{e.metric} {e.operator} {e.threshold}</span>
                        {e.ai_proposed && <Badge tone="accent"><Sparkles className="w-3 h-3" /> AI</Badge>}
                        {e.status === "pending" && (
                          <div className="flex gap-1">
                            <button onClick={() => approve(e.id)} className="h-6 w-6 flex items-center justify-center rounded border border-hairline text-pos hover:bg-[rgb(var(--pos)/0.08)] transition-colors"><Check className="w-3.5 h-3.5" /></button>
                            <button onClick={() => reject(e.id)} className="h-6 w-6 flex items-center justify-center rounded border border-hairline text-neg hover:bg-[rgb(var(--neg)/0.08)] transition-colors"><X className="w-3.5 h-3.5" /></button>
                          </div>
                        )}
                        {e.status !== "pending" && <span className={`text-[10px] font-medium ${e.status === "active" ? "text-pos" : "text-neg"}`}>{e.status}</span>}
                      </div>
                    ))}
                  </div>
                )}
              </div>
            );
          })}
          {!isFetching && Object.keys(byFeed).length === 0 && (
            <div className="text-center text-sm text-ink-3 py-8">No expectations at <code>/api/admin/nidp/expectations</code>.</div>
          )}
        </div>
      </CardContent>
    </Card>
  );
}
