/**
 * Strategy Builder API client.
 *
 * Thin axios wrappers — every call carries withCredentials so the
 * session cookie auths against /api/strategy-builder/* on the backend.
 * Errors propagate as-is to the caller (component decides UX).
 */
import axios from "axios";

const BACKEND_URL = process.env.REACT_APP_BACKEND_URL;
const API = `${BACKEND_URL}/api/strategy-builder`;
const cfg = { withCredentials: true };

// ── Templates + validation ──────────────────────────────────────────
export const listTemplates = () =>
  axios.get(`${API}/templates`, cfg).then((r) => r.data);

export const validateSpec = (spec) =>
  axios.post(`${API}/validate`, spec, cfg).then((r) => r.data);

// ── Universes ───────────────────────────────────────────────────────
export const listUniverses = (assetClass) =>
  axios.get(`${API}/universes`, {
    ...cfg,
    params: assetClass ? { asset_class: assetClass } : {},
  }).then((r) => r.data);

export const createUniverse = (body) =>
  axios.post(`${API}/universes`, body, cfg).then((r) => r.data);

// ── Strategies ──────────────────────────────────────────────────────
export const listStrategies = (includeTemplates = false) =>
  axios.get(`${API}/strategies`, {
    ...cfg,
    params: { include_templates: includeTemplates },
  }).then((r) => r.data);

export const getStrategy = (id) =>
  axios.get(`${API}/strategies/${id}`, cfg).then((r) => r.data);

export const createStrategy = (body) =>
  axios.post(`${API}/strategies`, body, cfg).then((r) => r.data);

export const updateStrategy = (id, definition) =>
  axios.patch(`${API}/strategies/${id}`, { definition }, cfg).then((r) => r.data);

export const archiveStrategy = (id) =>
  axios.delete(`${API}/strategies/${id}`, cfg).then((r) => r.data);

// ── Screen ──────────────────────────────────────────────────────────
// Run the entry rules against the latest feature snapshot → ranked
// candidate list. `asOfDate` optional (defaults to latest snapshot).
export const screenStrategy = (definition, asOfDate = null) =>
  axios.post(`${API}/screen`, { definition, as_of_date: asOfDate }, cfg).then((r) => r.data);

// ── Backtest ────────────────────────────────────────────────────────
export const runBacktest = (id, body) =>
  axios.post(`${API}/strategies/${id}/backtest`, body, cfg).then((r) => r.data);

export const getRun = (runId) =>
  axios.get(`${API}/runs/${runId}`, cfg).then((r) => r.data);

// ── Admin ───────────────────────────────────────────────────────────
export const promoteTemplate = (id) =>
  axios.post(`${API}/strategies/${id}/promote`, null, cfg).then((r) => r.data);

export const adminSnapshotFeatures = (targetDate, universe = "nifty500") =>
  axios.post(`${API}/snapshot-features`, null, {
    ...cfg,
    params: { target_date: targetDate, universe },
  }).then((r) => r.data);
