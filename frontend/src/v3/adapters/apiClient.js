/*
 * V3 API client — thin axios wrapper that mirrors V2 conventions:
 *   - process.env.REACT_APP_BACKEND_URL as base
 *   - withCredentials: true for session cookie auth
 *   - GET and POST helpers returning parsed JSON
 *   - never throws on 4xx/5xx; returns { data: null, error } so adapters degrade
 *     to placeholder data without crashing the screen.
 *
 * All V3 backend calls go through here so swapping transport (fetch / suspense /
 * react-query) later is a one-file change.
 */
import axios from "axios";

const BACKEND_URL = process.env.REACT_APP_BACKEND_URL || "";
const API_ROOT = `${BACKEND_URL}/api`;

const cfg = { withCredentials: true, timeout: 30000 };

async function safeRequest(promise, fallback = null) {
  try {
    const r = await promise;
    return { data: r.data, error: null };
  } catch (e) {
    // 401 means session expired — return a sentinel so the screen can prompt re-auth without crashing
    const status = e?.response?.status;
    const detail = e?.response?.data?.detail || e?.message || "Request failed";
    return {
      data: fallback,
      error: { status: status ?? 0, message: detail },
    };
  }
}

export const apiGet = (path, params = null) =>
  safeRequest(axios.get(`${API_ROOT}${path}`, { ...cfg, params: params || undefined }));

export const apiPost = (path, body = null) =>
  safeRequest(axios.post(`${API_ROOT}${path}`, body, cfg));

export { API_ROOT, BACKEND_URL };
