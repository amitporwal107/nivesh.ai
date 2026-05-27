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
import { ClientProfileC, NeedsAttentionItemC } from "@/services/contracts/advisor.contract";
import { z } from "zod";
const ProfileList = z.array(ClientProfileC);
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
export const realMfdAdapter = {
    async listProfiles() {
        const res = await http({ path: "/api/mfd/profiles" });
        const parsed = ProfileList.safeParse(res.data);
        if (!parsed.success)
            throw ApiError.contractDrift(`mfd.listProfiles: ${parsed.error.message}`);
        return parsed.data;
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
        if (!parsed.success)
            throw ApiError.contractDrift(`mfd.needsAttention: ${parsed.error.message}`);
        return Array.isArray(parsed.data) ? parsed.data : parsed.data.items;
    },
    async callLog(profileId, body) {
        const res = await http({
            method: "POST",
            path: `/api/mfd/profiles/${encodeURIComponent(profileId)}/call-log`,
            body,
        });
        const parsed = CallLogRes.safeParse(res.data);
        if (!parsed.success)
            throw ApiError.contractDrift(`mfd.callLog: ${parsed.error.message}`);
        return parsed.data;
    },
    async sipNudge(profileId, body) {
        const res = await http({
            method: "POST",
            path: `/api/mfd/profiles/${encodeURIComponent(profileId)}/sip-nudge`,
            body,
        });
        const parsed = NudgeRes.safeParse(res.data);
        if (!parsed.success)
            throw ApiError.contractDrift(`mfd.sipNudge: ${parsed.error.message}`);
        return parsed.data;
    },
    async reviewPackGenerate(profileId, body) {
        const res = await http({
            method: "POST",
            path: `/api/mfd/profiles/${encodeURIComponent(profileId)}/review-pack/generate`,
            body: { format: "pdf", ...body },
        });
        const parsed = ReviewPackKickoffRes.safeParse(res.data);
        if (!parsed.success)
            throw ApiError.contractDrift(`mfd.reviewPackGenerate: ${parsed.error.message}`);
        return parsed.data;
    },
    async reviewPackPoll(profileId, taskId) {
        const res = await http({
            path: `/api/mfd/profiles/${encodeURIComponent(profileId)}/review-pack/${encodeURIComponent(taskId)}`,
        });
        const parsed = ReviewPackPollRes.safeParse(res.data);
        if (!parsed.success)
            throw ApiError.contractDrift(`mfd.reviewPackPoll: ${parsed.error.message}`);
        return parsed.data;
    },
};
