export class ApiError extends Error {
    kind;
    status;
    detail;
    fields;
    correlationId;
    constructor(kind, message, opts = {}) {
        super(message);
        this.name = "ApiError";
        this.kind = kind;
        this.status = opts.status;
        this.detail = opts.detail;
        this.fields = opts.fields;
        this.correlationId = opts.correlationId;
        if (opts.cause)
            this.cause = opts.cause;
    }
    static fromResponse(response, body, correlationId) {
        const { status } = response;
        // FastAPI envelope: { detail: string | Array<...> }
        const detail = extractDetail(body);
        const kind = status === 401 ? "auth" :
            status === 403 ? "forbidden" :
                status === 404 ? "not_found" :
                    status === 422 || status === 400 ? "validation" :
                        status === 429 ? "rate_limit" :
                            status >= 500 ? "server" :
                                "unknown";
        return new ApiError(kind, detail ?? `HTTP ${status}`, {
            status,
            detail,
            correlationId,
            fields: extractFields(body),
        });
    }
    static network(cause, correlationId) {
        return new ApiError("network", "Network error", { cause, correlationId });
    }
    static timeout(correlationId) {
        return new ApiError("timeout", "Request timed out", { correlationId });
    }
    static contractDrift(message, cause) {
        return new ApiError("contract_drift", `Response did not match contract: ${message}`, { cause });
    }
}
function extractDetail(body) {
    if (!body || typeof body !== "object")
        return undefined;
    const obj = body;
    if (typeof obj.detail === "string")
        return obj.detail;
    if (Array.isArray(obj.detail)) {
        // FastAPI validation errors are arrays of { msg, loc, type }
        const first = obj.detail[0];
        return first?.msg;
    }
    if (typeof obj.message === "string")
        return obj.message;
    return undefined;
}
function extractFields(body) {
    if (!body || typeof body !== "object")
        return undefined;
    const obj = body;
    if (!Array.isArray(obj.detail))
        return undefined;
    const out = {};
    for (const item of obj.detail) {
        const e = item;
        if (e?.loc && e.msg) {
            const key = e.loc.filter((x) => x !== "body").join(".");
            out[key] = e.msg;
        }
    }
    return Object.keys(out).length ? out : undefined;
}
