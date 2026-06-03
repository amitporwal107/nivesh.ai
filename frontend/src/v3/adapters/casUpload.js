// CAS / portfolio file upload adapter — wraps POST /api/portfolio/upload
// and the subsequent status polling. Returns a controller object the
// onboarding screen drives explicitly (no useAsync — the lifecycle is
// "upload → poll status → done", not "fetch on mount").

import axios from "axios";
import { BACKEND_URL } from "./apiClient";

const API = `${BACKEND_URL}/api`;
const cfg = { withCredentials: true };

/**
 * Upload a portfolio file (CAS PDF, CSV, or Excel). For PDFs, the backend
 * returns a task_id; you then call `pollUploadStatus(taskId)` until it
 * reports completed.
 *
 * Returns: { ok, taskId?, holdings?, count?, message?, error? }
 */
export async function uploadPortfolioFile(file, { password } = {}) {
  if (!file) return { ok: false, error: { message: "No file provided" } };
  const form = new FormData();
  form.append("file", file, file.name);
  const headers = { "Content-Type": "multipart/form-data" };
  if (password) headers["X-Password"] = String(password).toUpperCase();
  try {
    const r = await axios.post(`${API}/portfolio/upload`, form, {
      ...cfg,
      headers,
      timeout: 60000,
    });
    const data = r.data || {};
    if (data.task_id) {
      return { ok: true, taskId: data.task_id, status: data.status || "processing", message: data.message };
    }
    return {
      ok: true,
      holdings: data.holdings || [],
      count: data.count || 0,
      message: data.message || null,
    };
  } catch (e) {
    const status = e?.response?.status || 0;
    // 410 = CAS PDF direct upload deprecated; guide user to Connect SDK.
    const message = status === 410
      ? "PDF upload is no longer supported here. Use the 'Import CAS' button to import via the CAS Connect widget."
      : e?.response?.data?.detail || e?.message || "Upload failed";
    return { ok: false, error: { status, message } };
  }
}

/**
 * Poll /api/portfolio/upload-status/{taskId} until `status === "completed"`
 * or `"failed"`. Calls `onProgress({status, count?, message?})` after each
 * poll so the UI can stream the finding list.
 */
export async function pollUploadStatus(taskId, { intervalMs = 1500, maxMs = 120000, onProgress } = {}) {
  const start = Date.now();
  while (Date.now() - start < maxMs) {
    try {
      const r = await axios.get(`${API}/portfolio/upload-status/${taskId}`, cfg);
      const data = r.data || {};
      onProgress && onProgress(data);
      if (data.status === "completed") {
        return { ok: true, holdings: data.holdings || [], count: data.count || (data.holdings || []).length };
      }
      if (data.status === "failed" || data.status === "error") {
        return { ok: false, error: { message: data.message || "Parsing failed" } };
      }
    } catch (e) {
      // Network blip — keep polling unless it's persistent
      onProgress && onProgress({ status: "polling_error", message: e?.message });
    }
    await new Promise((res) => setTimeout(res, intervalMs));
  }
  return { ok: false, error: { message: "Upload timed out" } };
}
