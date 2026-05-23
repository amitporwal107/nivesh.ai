/**
 * V4 API client — single fetch wrapper. Every backend call from V4 routes
 * through this. Components consume V4-shaped data only; per-screen adapters
 * in `./adapters/` reshape raw responses into V4 contracts.
 *
 * Conventions:
 *   - Cookies are sent automatically (credentials: include) for the session cookie.
 *   - Errors are surfaced as thrown ApiError with the parsed envelope when possible.
 *   - Base URL is empty → same-origin. The FE is served from the same host as /api.
 */

export class ApiError extends Error {
  constructor(message, { status, code, detail } = {}) {
    super(message);
    this.name = "ApiError";
    this.status = status;
    this.code = code;
    this.detail = detail;
  }
}

async function parseBody(res) {
  const ct = res.headers.get("content-type") || "";
  if (ct.includes("application/json")) {
    try {
      return await res.json();
    } catch {
      return null;
    }
  }
  try {
    return await res.text();
  } catch {
    return null;
  }
}

async function request(method, path, { body, headers, signal, query } = {}) {
  const qs = query
    ? "?" +
      Object.entries(query)
        .filter(([, v]) => v !== undefined && v !== null && v !== "")
        .map(([k, v]) => encodeURIComponent(k) + "=" + encodeURIComponent(v))
        .join("&")
    : "";
  const url = path + qs;

  const init = {
    method,
    credentials: "include",
    headers: {
      Accept: "application/json",
      ...headers,
    },
    signal,
  };

  if (body !== undefined) {
    if (body instanceof FormData) {
      init.body = body;
    } else {
      init.body = JSON.stringify(body);
      init.headers["Content-Type"] = "application/json";
    }
  }

  const res = await fetch(url, init);
  const parsed = await parseBody(res);

  if (!res.ok) {
    const detail = parsed && typeof parsed === "object" ? parsed.detail || parsed.message : parsed;
    const code = parsed && typeof parsed === "object" ? parsed.code : undefined;
    throw new ApiError(`${method} ${path} → ${res.status}`, {
      status: res.status,
      code,
      detail,
    });
  }

  return parsed;
}

export const api = {
  get: (path, opts) => request("GET", path, opts),
  post: (path, body, opts) => request("POST", path, { ...opts, body }),
  patch: (path, body, opts) => request("PATCH", path, { ...opts, body }),
  put: (path, body, opts) => request("PUT", path, { ...opts, body }),
  del: (path, opts) => request("DELETE", path, opts),
};

export default api;
