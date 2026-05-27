/**
 * HTTP client.
 *
 * - `credentials: include` — cookie session (name `session`) auto-attached
 * - AbortController timeout
 * - Correlation ID + observability events on every call
 * - FastAPI `{ detail }` envelope normalisation via ApiError.fromResponse
 * - Optional ETag pass-through for cache-aware endpoints (insights/v3-portfolio)
 * - Bounded retry on transient (network / 5xx / 429) — does NOT retry 4xx
 */
import { apiConfig } from "./config";
import { ApiError } from "./errors";
import { correlationId, getObserver } from "@/lib/observability";
export async function http(req) {
    const id = correlationId();
    const url = buildUrl(req.path, req.query);
    const method = req.method ?? "GET";
    const headers = {
        Accept: "application/json",
        "X-Correlation-Id": id,
        "X-Client-Version": apiConfig.appVersion,
        ...(req.body != null ? { "Content-Type": "application/json" } : {}),
        ...(req.ifNoneMatch ? { "If-None-Match": req.ifNoneMatch } : {}),
        ...(req.headers ?? {}),
    };
    const obs = getObserver();
    const attempts = req.noRetry ? 1 : Math.max(1, apiConfig.retry.attempts + 1);
    let lastErr;
    for (let attempt = 0; attempt < attempts; attempt++) {
        const startedAt = performance.now();
        obs.onRequestStart({ correlationId: id, method, url, startedAt });
        const timeoutCtrl = new AbortController();
        const timeoutMs = req.timeoutMs ?? apiConfig.requestTimeoutMs;
        const timeoutHandle = setTimeout(() => timeoutCtrl.abort(), timeoutMs);
        const signal = req.signal
            ? anyAbortSignal([req.signal, timeoutCtrl.signal])
            : timeoutCtrl.signal;
        try {
            const res = await fetch(url, {
                method,
                headers,
                credentials: "include",
                body: req.body != null ? JSON.stringify(req.body) : undefined,
                signal,
            });
            clearTimeout(timeoutHandle);
            const durationMs = performance.now() - startedAt;
            obs.onRequestEnd({ correlationId: id, method, url, startedAt, durationMs, status: res.status });
            if (res.status === 304) {
                return { status: 304, data: undefined, notModified: true, etag: req.ifNoneMatch, correlationId: id };
            }
            if (!res.ok) {
                const body = await safeJson(res);
                const err = ApiError.fromResponse(res, body, id);
                // retry on 5xx / 429 only if attempts remain
                if (shouldRetry(err) && attempt < attempts - 1) {
                    lastErr = err;
                    await delay(backoff(attempt));
                    continue;
                }
                throw err;
            }
            const etag = res.headers.get("etag") ?? undefined;
            const data = (await safeJson(res));
            return { status: res.status, data, etag, correlationId: id };
        }
        catch (err) {
            clearTimeout(timeoutHandle);
            const durationMs = performance.now() - startedAt;
            obs.onRequestError({ correlationId: id, method, url, startedAt, durationMs, error: err });
            if (err instanceof ApiError) {
                if (shouldRetry(err) && attempt < attempts - 1) {
                    lastErr = err;
                    await delay(backoff(attempt));
                    continue;
                }
                throw err;
            }
            if (isAbort(err)) {
                if (req.signal?.aborted)
                    throw err; // caller cancellation — re-throw
                throw ApiError.timeout(id);
            }
            const wrapped = ApiError.network(err, id);
            if (attempt < attempts - 1) {
                lastErr = wrapped;
                await delay(backoff(attempt));
                continue;
            }
            throw wrapped;
        }
    }
    throw lastErr ?? new ApiError("unknown", "Exhausted retries");
}
function buildUrl(path, query) {
    const u = new URL(path, apiConfig.baseUrl);
    if (query) {
        for (const [k, v] of Object.entries(query)) {
            if (v === undefined || v === null || v === "")
                continue;
            u.searchParams.append(k, String(v));
        }
    }
    return u.toString();
}
async function safeJson(res) {
    const text = await res.text();
    if (!text)
        return undefined;
    try {
        return JSON.parse(text);
    }
    catch {
        return text;
    }
}
function shouldRetry(err) {
    return err.kind === "network" || err.kind === "server" || err.kind === "rate_limit" || err.kind === "timeout";
}
function backoff(attempt) {
    const base = apiConfig.retry.baseDelayMs;
    return base * 2 ** attempt + Math.random() * base;
}
function delay(ms) {
    return new Promise((r) => setTimeout(r, ms));
}
function isAbort(err) {
    return err instanceof DOMException && err.name === "AbortError";
}
function anyAbortSignal(signals) {
    // AbortSignal.any() is Baseline 2024; fall back for older browsers.
    const Any = AbortSignal.any;
    if (Any)
        return Any(signals);
    const ctrl = new AbortController();
    for (const s of signals) {
        if (s.aborted) {
            ctrl.abort(s.reason);
            return ctrl.signal;
        }
        s.addEventListener("abort", () => ctrl.abort(s.reason), { once: true });
    }
    return ctrl.signal;
}
