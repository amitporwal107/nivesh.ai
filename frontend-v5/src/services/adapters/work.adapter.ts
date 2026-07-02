import { http } from "@/services/api/http";
import { ApiError } from "@/services/api/errors";
import {
  IssuesListResC,
  WorkStatsC,
  WorkIssueC,
  type WorkIssue,
  type WorkStats,
} from "@/services/contracts/work.contract";

export interface IssuesFilter {
  status?:     string;
  priority?:   string;
  source?:     string;
  label?:      string;
  issue_type?: string;   // epic | story | task
  phase?:      string;   // phase-1 | phase-2 | phase-3
  parent?:     string;   // parent issue_id
  track?:      string;   // internal | vendor-gated
  limit?:      number;
  offset?:     number;
}

export interface IssueUpdate {
  status?:         string;
  classification?: string;
  priority?:       string;
  assignee?:       string;
  labels?:         string[];
  comment?:        string;
  // ── program-tracker grooming fields ──
  title?:             string;
  issue_type?:        string;
  parent?:            string;
  phase?:             string;
  track?:             string;
  workflow?:          string[];
  estimate?:          string;
  requirements_md?:   string;
  design_md?:         string;
  screens?:           { name?: string; url?: string }[];
  implementation_md?: string;
  github?:            { commit?: string; pr_url?: string; branch?: string };
  test_doc_md?:       string;
  artifacts?:         { kind?: string; url?: string }[];
}

export const workAdapter = {
  async list(filter: IssuesFilter = {}): Promise<{ issues: WorkIssue[]; total: number }> {
    const params = new URLSearchParams();
    if (filter.status)     params.set("status",     filter.status);
    if (filter.priority)   params.set("priority",   filter.priority);
    if (filter.source)     params.set("source",     filter.source);
    if (filter.label)      params.set("label",      filter.label);
    if (filter.issue_type) params.set("issue_type", filter.issue_type);
    if (filter.phase)      params.set("phase",      filter.phase);
    if (filter.parent)     params.set("parent",     filter.parent);
    if (filter.track)      params.set("track",      filter.track);
    if (filter.limit)      params.set("limit",      String(filter.limit));
    if (filter.offset)     params.set("offset",     String(filter.offset));

    const qs = params.toString();
    const res = await http({ path: `/api/work/issues${qs ? `?${qs}` : ""}` });
    const parsed = IssuesListResC.safeParse(res.data);
    if (!parsed.success) throw ApiError.contractDrift(`work.list: ${parsed.error.message}`);
    return { issues: parsed.data.issues, total: parsed.data.total };
  },

  async get(issueId: string): Promise<WorkIssue> {
    const res = await http({ path: `/api/work/issues/${encodeURIComponent(issueId)}` });
    const parsed = WorkIssueC.safeParse(res.data);
    if (!parsed.success) throw ApiError.contractDrift(`work.get: ${parsed.error.message}`);
    return parsed.data;
  },

  async update(issueId: string, body: IssueUpdate): Promise<WorkIssue> {
    const res = await http({
      path:   `/api/work/issues/${encodeURIComponent(issueId)}`,
      method: "PATCH",
      body,
    });
    const parsed = WorkIssueC.safeParse(res.data);
    if (!parsed.success) throw ApiError.contractDrift(`work.update: ${parsed.error.message}`);
    return parsed.data;
  },

  async stats(): Promise<WorkStats> {
    const res = await http({ path: "/api/work/stats" });
    const parsed = WorkStatsC.safeParse(res.data);
    if (!parsed.success) throw ApiError.contractDrift(`work.stats: ${parsed.error.message}`);
    return parsed.data;
  },

  /** Triage flag: valid | business_validation | tbd | unclassified. */
  async classify(issueId: string, classification: string): Promise<WorkIssue> {
    return this.update(issueId, { classification });
  },

  /** Spawn the PR-only auto-fix agent (issue must be classified "valid"). */
  async triggerFix(issueId: string): Promise<{ issue_id: string; remediation: { status: string } }> {
    const res = await http({
      path:   `/api/work/issues/${encodeURIComponent(issueId)}/fix`,
      method: "POST",
      noRetry: true,
    });
    return res.data as { issue_id: string; remediation: { status: string } };
  },
};

/** Report client-side (browser) errors so they're filed as work issues.
 *  Used by lib/session-log while session logging is on. Best-effort. */
export async function reportClientErrors(
  entries: { message: string; correlation_id?: string }[],
): Promise<void> {
  await http({
    path:   "/api/work/issues/from-client-errors",
    method: "POST",
    body:   { entries },
    noRetry: true,
  });
}
