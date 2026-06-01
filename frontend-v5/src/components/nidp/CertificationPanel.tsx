import { RefreshCw, Loader2, Award, CheckCircle2, XCircle, Clock } from "lucide-react";
import { Card, CardContent, CardLabel } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { http } from "@/services/api/http";
import { useQuery } from "@tanstack/react-query";

interface CertEntry {
  date: string;          // YYYY-MM-DD
  domain: string;
  certified: boolean;
  eligible: boolean;
  blockers?: string[];
}

interface CertData {
  calendar: CertEntry[];
  domains: string[];
}

export function CertificationPanel() {
  const { data, isFetching, refetch, error } = useQuery({
    queryKey: ["nidp", "certification"],
    queryFn: () => http<CertData>({ path: "/api/admin/nidp/certification" }).then((r) => r.data).catch(() => ({ calendar: [], domains: [] })),
    staleTime: 10 * 60_000,
  });

  // Group calendar by domain
  const byDomain = (data?.calendar ?? []).reduce<Record<string, CertEntry[]>>((acc, e) => {
    (acc[e.domain] ??= []).push(e); return acc;
  }, {});

  // Last 30 days of the calendar
  const recentDates = (data?.calendar ?? [])
    .map((e) => e.date)
    .filter((v, i, a) => a.indexOf(v) === i)
    .sort()
    .slice(-30);

  return (
    <Card>
      <CardContent className="p-5">
        <div className="flex items-center justify-between mb-5">
          <div className="flex items-center gap-3">
            <div className="w-10 h-10 rounded-lg bg-accent-soft flex items-center justify-center">
              <Award className="w-5 h-5 text-accent" />
            </div>
            <div>
              <h2 className="text-base font-semibold text-ink">Certification</h2>
              <p className="text-xs text-ink-3">90-day calendar tracker · cert status · eligibility criteria per domain.</p>
            </div>
          </div>
          <Button size="sm" variant="outline" onClick={() => refetch()} disabled={isFetching}>
            {isFetching ? <Loader2 className="w-3.5 h-3.5 animate-spin" /> : <RefreshCw className="w-3.5 h-3.5" />}
          </Button>
        </div>

        {error && <div className="text-sm text-neg bg-[rgb(var(--neg)/0.08)] rounded-lg p-3 mb-4">Failed to load certification data: {String(error)}</div>}

        {Object.entries(byDomain).length > 0 ? (
          <div className="space-y-5">
            {Object.entries(byDomain).map(([domain, entries]) => {
              const latestEntry = entries.sort((a, b) => b.date.localeCompare(a.date))[0];
              return (
                <div key={domain}>
                  <div className="flex items-center justify-between mb-2">
                    <div className="flex items-center gap-2">
                      <span className="text-sm font-medium text-ink">{domain}</span>
                      <Badge tone={latestEntry?.certified ? "good" : latestEntry?.eligible ? "warm" : "neg"}>
                        {latestEntry?.certified ? "Certified" : latestEntry?.eligible ? "Eligible" : "Not certified"}
                      </Badge>
                    </div>
                    {latestEntry?.blockers && latestEntry.blockers.length > 0 && (
                      <div className="text-xs text-neg">{latestEntry.blockers[0]}{latestEntry.blockers.length > 1 ? ` +${latestEntry.blockers.length - 1} more` : ""}</div>
                    )}
                  </div>
                  {/* 30-day strip */}
                  <div className="flex gap-0.5">
                    {recentDates.map((date) => {
                      const e = entries.find((en) => en.date === date);
                      const color = !e ? "bg-surface-2" : e.certified ? "bg-pos" : e.eligible ? "bg-warm" : "bg-neg";
                      const opacity = !e ? "opacity-30" : "opacity-70";
                      return (
                        <div
                          key={date}
                          title={`${date}: ${!e ? "no data" : e.certified ? "certified" : e.eligible ? "eligible" : "not certified"}`}
                          className={`flex-1 h-4 rounded-sm ${color} ${opacity}`}
                        />
                      );
                    })}
                  </div>
                  <div className="flex justify-between text-[10px] text-ink-3 mt-1">
                    <span>{recentDates[0]}</span><span>{recentDates[recentDates.length - 1]}</span>
                  </div>
                </div>
              );
            })}
          </div>
        ) : (
          <div className="text-center text-sm text-ink-3 py-8">
            {isFetching ? "Loading…" : "No certification data at /api/admin/nidp/certification."}
          </div>
        )}
      </CardContent>
    </Card>
  );
}
