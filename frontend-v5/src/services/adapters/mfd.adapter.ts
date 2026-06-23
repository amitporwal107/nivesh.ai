/**
 * MFD adapter — per-client workspace + v4 client-360 extensions.
 *
 *   GET    /api/mfd/profiles                         (list)
 *   POST   /api/mfd/profiles
 *   GET    /api/mfd/profiles/{id}
 *   PATCH  /api/mfd/profiles/{id}
 *   DELETE /api/mfd/profiles/{id}
 *   POST   /api/mfd/profiles/{id}/activate           (impersonate)
 *   POST   /api/mfd/profiles/deactivate
 *   GET    /api/mfd/profiles/{id}/needs-attention    (v4 §B.3)
 *   POST   /api/mfd/profiles/{id}/call-log           (v4 §B.5)
 *   POST   /api/mfd/profiles/{id}/sip-nudge          (v4 §B.9)
 *   POST   /api/mfd/profiles/{id}/review-pack/generate (v4 §B.4 — async)
 *   GET    /api/mfd/profiles/{id}/review-pack/{task_id}  (v4 §B.4 — poll)
 */
import { http } from "@/services/api/http";
import { ApiError } from "@/services/api/errors";
import { NeedsAttentionItemC, ProfilesListRes } from "@/services/contracts/advisor.contract";
import { z } from "zod";

export type CallOutcome = "callback_requested" | "discussed_rebalance" | "no_answer" | "left_voicemail";
export type ReviewPackSection = "portfolio" | "goals" | "risk" | "performance" | "health" | "domains" | "needs_attention" | "plan";
export type SipNudgeTemplate = "BOUNCE_INSUFFICIENT_BALANCE" | "BOUNCE_MANDATE_LIMIT" | "BOUNCE_ACCOUNT_CLOSED" | "MANDATE_EXPIRY" | "STEPUP_DUE";
export type ReviewPackStatus = "QUEUED" | "PROCESSING" | "COMPLETED" | "FAILED";

export interface MfdAdapter {
  listProfiles(): Promise<import("@/services/contracts/advisor.contract").ClientProfileC[]>;
  activateProfile(profileId: string): Promise<{ ok: true }>;
  deactivateProfile(): Promise<{ ok: true }>;
  needsAttention(profileId: string): Promise<unknown[]>;
  callLog(profileId: string, body: { notes: string; outcome: CallOutcome; next_followup_date?: string }): Promise<{ call_log_id: string; occurred_at: string }>;
  sipNudge(profileId: string, body: { fund_name: string; proposed_amount?: number; template?: SipNudgeTemplate }): Promise<{ nudge_id: string; queued_at: string }>;
  reviewPackGenerate(profileId: string, body: { format?: "pdf"; sections: ReviewPackSection[] }): Promise<{ task_id: string; status: ReviewPackStatus; estimated_seconds?: number }>;
  reviewPackPoll(profileId: string, taskId: string): Promise<{ task_id: string; status: ReviewPackStatus; download_url?: string }>;
}

const NeedsAttentionRes = z.union([
  z.array(NeedsAttentionItemC),
  z.object({ items: z.array(NeedsAttentionItemC) }).passthrough(),
]);
const CallLogRes = z.object({ call_log_id: z.string(), occurred_at: z.string() }).passthrough();
const NudgeRes = z.object({ nudge_id: z.string(), queued_at: z.string() }).passthrough();
const ReviewPackKickoffRes = z.object({
  task_id: z.string(),
  status: z.enum(["QUEUED", "PROCESSING", "COMPLETED", "FAILED"]),
  estimated_seconds: z.number().optional(),
}).passthrough();
const ReviewPackPollRes = z.object({
  task_id: z.string(),
  status: z.enum(["QUEUED", "PROCESSING", "COMPLETED", "FAILED"]),
  download_url: z.string().optional(),
}).passthrough();

export const realMfdAdapter: MfdAdapter = {
  async listProfiles() {
    const res = await http({ path: "/api/mfd/profiles" });
    const parsed = ProfilesListRes.safeParse(res.data);
    if (!parsed.success) throw ApiError.contractDrift(`mfd.listProfiles: ${parsed.error.message}`);
    return parsed.data.profiles;
  },
  async activateProfile(profileId) {
    await http({ method: "POST", path: `/api/mfd/profiles/${encodeURIComponent(profileId)}/activate` });
    return { ok: true };
  },
  async deactivateProfile() {
    await http({ method: "POST", path: "/api/mfd/profiles/deactivate" });
    return { ok: true };
  },
  async needsAttention(profileId) {
    const res = await http({ path: `/api/mfd/profiles/${encodeURIComponent(profileId)}/needs-attention` });
    const parsed = NeedsAttentionRes.safeParse(res.data);
    if (!parsed.success) throw ApiError.contractDrift(`mfd.needsAttention: ${parsed.error.message}`);
    return Array.isArray(parsed.data) ? parsed.data : parsed.data.items;
  },
  async callLog(profileId, body) {
    const res = await http({
      method: "POST",
      path: `/api/mfd/profiles/${encodeURIComponent(profileId)}/call-log`,
      body,
    });
    const parsed = CallLogRes.safeParse(res.data);
    if (!parsed.success) throw ApiError.contractDrift(`mfd.callLog: ${parsed.error.message}`);
    return parsed.data;
  },
  async sipNudge(profileId, body) {
    const res = await http({
      method: "POST",
      path: `/api/mfd/profiles/${encodeURIComponent(profileId)}/sip-nudge`,
      body,
    });
    const parsed = NudgeRes.safeParse(res.data);
    if (!parsed.success) throw ApiError.contractDrift(`mfd.sipNudge: ${parsed.error.message}`);
    return parsed.data;
  },
  async reviewPackGenerate(profileId, body) {
    const res = await http({
      method: "POST",
      path: `/api/mfd/profiles/${encodeURIComponent(profileId)}/review-pack/generate`,
      body: { format: "pdf", ...body },
    });
    const parsed = ReviewPackKickoffRes.safeParse(res.data);
    if (!parsed.success) throw ApiError.contractDrift(`mfd.reviewPackGenerate: ${parsed.error.message}`);
    return parsed.data;
  },
  async reviewPackPoll(profileId, taskId) {
    const res = await http({
      path: `/api/mfd/profiles/${encodeURIComponent(profileId)}/review-pack/${encodeURIComponent(taskId)}`,
    });
    const parsed = ReviewPackPollRes.safeParse(res.data);
    if (!parsed.success) throw ApiError.contractDrift(`mfd.reviewPackPoll: ${parsed.error.message}`);
    return parsed.data;
  },
};
