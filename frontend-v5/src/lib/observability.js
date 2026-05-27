class ConsoleObserver {
    onRequestStart({ correlationId, method, url }) {
        if (typeof console !== "undefined") {
            console.debug(`[api ${correlationId.slice(0, 8)}] → ${method} ${url}`);
        }
    }
    onRequestEnd({ correlationId, status, durationMs, method, url }) {
        if (typeof console !== "undefined") {
            console.debug(`[api ${correlationId.slice(0, 8)}] ← ${status} ${method} ${url} (${durationMs.toFixed(0)}ms)`);
        }
    }
    onRequestError({ correlationId, error, durationMs, method, url }) {
        if (typeof console !== "undefined") {
            console.warn(`[api ${correlationId.slice(0, 8)}] ✗ ${method} ${url} (${durationMs.toFixed(0)}ms)`, error);
        }
    }
}
let activeObserver = new ConsoleObserver();
export function setObserver(observer) {
    activeObserver = observer;
}
export function getObserver() {
    return activeObserver;
}
/** RFC-4122 v4-ish (best-effort, not crypto). */
export function correlationId() {
    if (typeof crypto !== "undefined" && "randomUUID" in crypto) {
        return crypto.randomUUID();
    }
    return "xxxxxxxx-xxxx-4xxx-yxxx-xxxxxxxxxxxx".replace(/[xy]/g, (c) => {
        const r = (Math.random() * 16) | 0;
        return (c === "x" ? r : (r & 0x3) | 0x8).toString(16);
    });
}
