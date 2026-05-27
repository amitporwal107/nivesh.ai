/**
 * Dashboards v4 adapter.
 *
 * Six composite endpoints share the same envelope; we expose them as one
 * generic adapter parameterised by domain. Until OpenAPI lists these, Zod's
 * `.passthrough()` keeps us forward-compatible — unknown fields pass through
 * untouched, schema mismatches throw contract_drift.
 *
 * Endpoints per Postman v4 collection §B.1.
 */
import { http } from "@/services/api/http";
import { ApiError } from "@/services/api/errors";
import { DashboardEnvelopeC } from "@/services/contracts/dashboard.contract";
export const realDashboardsAdapter = {
    async fetch(domain, params) {
        const res = await http({
            path: `/api/dashboards/${domain}`,
            query: params,
        });
        const parsed = DashboardEnvelopeC.safeParse(res.data);
        if (!parsed.success)
            throw ApiError.contractDrift(`dashboards.${domain}: ${parsed.error.message}`);
        // backend may or may not include etag in body; fall back to header
        return { ...parsed.data, etag: parsed.data.etag ?? res.etag };
    },
};
