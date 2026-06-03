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
  status?:   string;
  priority?: string;
  source?:   string;
  label?:    string;
  limit?:    number;
  offset?:   number;
}

export interface IssueUpdate {
  status?:   string;
  priority?: string;
  assignee?: string;
  labels?:   string[];
  comment?:  string;
}

export const workAdapter = {
  async list(filter: IssuesFilter = {}): Promise<{ issues: WorkIssue[]; total: number }> {
    const params = new URLSearchParams();
    if (filter.status)   params.set("status",   filter.status);
    if (filter.priority) params.set("priority", filter.priority);
    if (filter.source)   params.set("source",   filter.source);
    if (filter.label)    params.set("label",    filter.label);
    if (filter.limit)    params.set("limit",    String(filter.limit));
    if (filter.offset)   params.set("offset",   String(filter.offset));

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
};
