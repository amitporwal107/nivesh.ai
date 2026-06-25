import { z } from "zod";

export const RcaBlockC = z.object({
  root_cause:      z.string().default(""),
  fix_suggestion:  z.string().default(""),
  confidence:      z.number().default(0),
  source:          z.string().default("unknown"),
  fix_file:        z.string().nullable().optional(),
  fix_description: z.string().nullable().optional(),
});
export type RcaBlock = z.infer<typeof RcaBlockC>;

export const WorkIssueC = z.object({
  issue_id:         z.string(),
  sig:              z.string(),
  title:            z.string(),
  severity:         z.string(),
  priority:         z.enum(["P1", "P2", "P3"]),
  status:           z.enum(["open", "in_progress", "resolved", "wont_fix"]),
  source:           z.string(),
  exception_class:  z.string().default(""),
  endpoint:         z.string().default(""),
  job_name:         z.string().default(""),
  http_status:      z.number().nullable().optional(),
  sample_message:   z.string().default(""),
  sample_traceback: z.string().default(""),
  first_seen:       z.string(),
  last_seen:        z.string(),
  count_24h:        z.number().default(1),
  recurrence_count: z.number().default(1),
  applications:     z.array(z.string()).default([]),
  rca:              RcaBlockC.nullable().optional(),
  labels:           z.array(z.string()).default([]),
  assignee:         z.string().nullable().optional(),
  comments:         z.array(z.object({
    author:     z.string(),
    body:       z.string(),
    created_at: z.string(),
  })).default([]),
  created_at:   z.string(),
  updated_at:   z.string(),
  resolved_at:  z.string().nullable().optional(),
});
export type WorkIssue = z.infer<typeof WorkIssueC>;

export const IssuesListResC = z.object({
  issues: z.array(WorkIssueC),
  total:  z.number(),
  offset: z.number(),
  limit:  z.number(),
});

export const WorkStatsC = z.object({
  total:       z.number(),
  by_status:   z.record(z.number()),
  by_priority: z.record(z.number()),
});
export type WorkStats = z.infer<typeof WorkStatsC>;
