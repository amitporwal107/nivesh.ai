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

export const RemediationC = z.object({
  status:      z.string().default("none"),   // none|queued|running|pr_open|failed|verified
  branch:      z.string().nullable().optional(),
  pr_url:      z.string().nullable().optional(),
  run_id:      z.string().nullable().optional(),
  detail:      z.string().nullable().optional(),
  started_at:  z.string().nullable().optional(),
  finished_at: z.string().nullable().optional(),
});
export type Remediation = z.infer<typeof RemediationC>;

export const WORK_STATUSES = ["open", "in_progress", "in_review", "testing_qa", "resolved", "wont_fix"] as const;
export const WORK_CLASSIFICATIONS = ["unclassified", "valid", "business_validation", "tbd"] as const;
export const WORK_ISSUE_TYPES = ["project", "epic", "story", "task"] as const;
export const WORK_PHASES = ["phase-1", "phase-2", "phase-3"] as const;
export const WORK_TRACKS = ["internal", "vendor-gated"] as const;

// Program-tracker sub-shapes (kept lenient to avoid contract drift on old docs).
export const GithubRefC = z.object({
  commit: z.string().nullable().optional(),
  pr_url: z.string().nullable().optional(),
  branch: z.string().nullable().optional(),
}).passthrough();
export type GithubRef = z.infer<typeof GithubRefC>;

export const WorkIssueC = z.object({
  issue_id:         z.string(),
  sig:              z.string(),
  title:            z.string(),
  severity:         z.string(),
  priority:         z.enum(["P1", "P2", "P3"]),
  status:           z.enum(WORK_STATUSES),
  classification:   z.enum(WORK_CLASSIFICATIONS).default("unclassified"),
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
  rca_document:     z.string().nullable().optional(),
  test_document:    z.string().nullable().optional(),
  screenshots:      z.array(z.string()).default([]),
  remediation:      RemediationC.nullable().optional(),
  labels:           z.array(z.string()).default([]),
  assignee:         z.string().nullable().optional(),
  comments:         z.array(z.object({
    author:     z.string(),
    body:       z.string(),
    created_at: z.string(),
  })).default([]),
  // ── program-tracker (project → epics → stories → tasks) — additive, lenient for old docs ──
  issue_type:        z.enum(WORK_ISSUE_TYPES).default("task"),
  project:           z.string().nullable().optional(),
  parent:            z.string().nullable().optional(),
  phase:             z.enum(WORK_PHASES).nullable().optional(),
  track:             z.enum(WORK_TRACKS).nullable().optional(),
  workflow:          z.array(z.string()).default([]),
  estimate:          z.string().nullable().optional(),
  requirements_md:   z.string().nullable().optional(),
  design_md:         z.string().nullable().optional(),
  screens:           z.array(z.any()).default([]),
  implementation_md: z.string().nullable().optional(),
  github:            GithubRefC.nullable().optional(),
  test_doc_md:       z.string().nullable().optional(),
  artifacts:         z.array(z.any()).default([]),
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
