/**
 * Research — QA validation exercise (/research/qa).
 *
 * An in-app, fill-in version of the two onboarding docs:
 *   • docs/onboarding/research-tab-overview.md               → the "Overview" tab
 *   • docs/onboarding/intern-research-app-validation-exercise.md → the "Checklist" tab
 *
 * It is a self-contained, login-gated page (rendered OUTSIDE AppLayout, like
 * /research). An intern ticks the UI checks, records what the app shows vs. what
 * the ORIGINAL BSE/NSE filing shows, logs bugs, and exports the whole thing as a
 * Markdown report to hand in.
 *
 * Honesty: nothing here talks to the backend. All answers live in the intern's
 * own browser (localStorage) and are exported on demand — there is no server
 * persistence, so the page makes no claim to save or submit anything.
 */
import { useState, useEffect, useCallback, useMemo } from "react";
import { Link } from "react-router-dom";
import {
  ClipboardCheck, ArrowLeft, Copy, Download, RotateCcw,
  Check, X, Plus, Trash2, BookOpen, ListChecks,
} from "lucide-react";
import "./qa.css";

const STORAGE_KEY = "nv-research-qa-v1";

/* ── content model (mirrors the exercise doc) ─────────────────────────────── */

const SETUP: { id: string; label: string; hint: string; text?: string }[] = [
  { id: "S1", label: "Got the staging URL + a login", hint: "Ask your mentor for the staging host and a test account / magic-link." },
  { id: "S2", label: "Opened the Research tab", hint: "Log in, go to /v5/research (or the Research tab in the mobile bottom nav, after Tips)." },
  { id: "S3", label: "Feed + All-filings are visible", hint: "You should see 'Read for you today' cards and an All-filings list." },
  { id: "S4", label: "Copied the session_token cookie", hint: "Devtools → Application → Cookies → session_token. Needed for the API checks." },
  { id: "S5", label: "Bookmarked BSE + NSE announcement pages", hint: "BSE: bseindia.com → Corporate Announcements. NSE: nseindia.com → Corporate Filings → Announcements." },
  { id: "S6", label: "Picked a test portfolio (for the badge)", hint: "Ask which test account has holdings; list the held companies.", text: "Held companies" },
];

const UI: { id: string; feature: string; testid: string; expected: string }[] = [
  { id: "U1", feature: "Research tab loads", testid: "—", expected: "Feed + All-filings render, no error/blank screen." },
  { id: "U2", feature: "'Read for you today'", testid: "today-toggle, signal-card", expected: "Today shows only today's filings; latest shows recent; up to 3 cards." },
  { id: "U3", feature: "Click-to-drawer", testid: "signal-drawer", expected: "Clicking a card opens a slide-over drawer with the filing detail." },
  { id: "U4", feature: "Portfolio-held badge", testid: "portfolio-badge", expected: "'IN YOUR PORTFOLIO' pill shows for a held company (card + drawer)." },
  { id: "U5", feature: "Company search scopes feed", testid: "filings-search", expected: "Feed narrows to the company; a scope chip appears; 'Read for you' hides." },
  { id: "U6", feature: "Clear scope", testid: "clear-company", expected: "Clearing the chip returns the full 'Read for you' view." },
  { id: "U7", feature: "Thematic starters", testid: "thematic-starter", expected: "A chip runs an Ask; Curated/History/Favorites tabs switch content." },
  { id: "U8", feature: "Ask bar (copilot)", testid: "ask-input, ask-submit", expected: "Answer renders with clickable source chips." },
  { id: "U9", feature: "All-filings sort", testid: "sort-material, sort-latest", expected: "MATERIAL = high-impact first; LATEST = newest first." },
  { id: "U10", feature: "Filing AI-insight panel", testid: "toggle-insight, insight-panel", expected: "Panel shows summary + sections + page citations." },
  { id: "U11", feature: "Documents library", testid: "doc-download", expected: "Download opens the original filing PDF." },
  { id: "U12", feature: "Alerts screen", testid: "alerts-screen", expected: "Preference saves. Delivery is intentionally OFF — a notice says so (expected)." },
];

const FILING_FIELDS: { id: string; label: string; kind: "compare" | "match" }[] = [
  { id: "company", label: "Company name", kind: "compare" },
  { id: "ticker", label: "Ticker / scrip", kind: "compare" },
  { id: "filedDate", label: "Filed date / time", kind: "compare" },
  { id: "docType", label: "Doc type / subject", kind: "compare" },
  { id: "summaryFaithful", label: "AI summary is faithful (no invented facts)", kind: "match" },
  { id: "metricInPdf", label: "'Headline metric' is actually stated in the PDF", kind: "match" },
  { id: "pageCite", label: "Page citation points to the right page", kind: "match" },
  { id: "portfolioBadge", label: "Portfolio-held badge is correct", kind: "match" },
];
const FILINGS = [1, 2, 3, 4, 5];

const API: { id: string; endpoint: string; check: string }[] = [
  { id: "A1", endpoint: "GET /api/filings/signals?today_only=true", check: "Same ≤3 companies/dates as the Read-for-you cards (U2/U3)." },
  { id: "A2", endpoint: "GET /api/filings/feed", check: "Row count / companies match the All-filings list." },
  { id: "A3", endpoint: "GET /api/filings/companies/search?q=<NAME>", check: "Returns the company you scoped to in U5." },
  { id: "A4", endpoint: "GET /api/filings/<ANNOUNCEMENT_ID>/insights", check: "Summary/metric/source_url match the drawer; source_url = the exchange PDF." },
  { id: "A5", endpoint: "GET /api/filings/portfolio-held", check: "Held names/symbols explain every portfolio-badge you saw (U4)." },
];

type Bug = { where: string; expected: string; actual: string; evidence: string; severity: string };
type State = { answers: Record<string, string>; bugs: Bug[] };

const EMPTY: State = { answers: {}, bugs: [] };

function load(): State {
  try {
    const raw = localStorage.getItem(STORAGE_KEY);
    if (!raw) return EMPTY;
    const p = JSON.parse(raw);
    return { answers: p.answers || {}, bugs: Array.isArray(p.bugs) ? p.bugs : [] };
  } catch {
    return EMPTY;
  }
}

/* ── small controls ───────────────────────────────────────────────────────── */

function PassFail({ value, onChange, testid }: { value?: string; onChange: (v: string) => void; testid?: string }) {
  return (
    <div className="qa-pf" data-testid={testid}>
      <button type="button" className={`qa-pf-btn pass ${value === "P" ? "on" : ""}`}
              onClick={() => onChange(value === "P" ? "" : "P")} aria-pressed={value === "P"}>PASS</button>
      <button type="button" className={`qa-pf-btn fail ${value === "F" ? "on" : ""}`}
              onClick={() => onChange(value === "F" ? "" : "F")} aria-pressed={value === "F"}>FAIL</button>
    </div>
  );
}

function MatchToggle({ value, onChange }: { value?: string; onChange: (v: string) => void }) {
  return (
    <div className="qa-match">
      <button type="button" className={`qa-m-btn yes ${value === "y" ? "on" : ""}`}
              onClick={() => onChange(value === "y" ? "" : "y")} aria-label="matches" title="matches source"><Check size={14} /></button>
      <button type="button" className={`qa-m-btn no ${value === "n" ? "on" : ""}`}
              onClick={() => onChange(value === "n" ? "" : "n")} aria-label="mismatch" title="does not match source"><X size={14} /></button>
    </div>
  );
}

/* ── page ─────────────────────────────────────────────────────────────────── */

export default function ResearchQAPage() {
  const [tab, setTab] = useState<"overview" | "checklist">("overview");
  const [state, setState] = useState<State>(() => load());
  const [copied, setCopied] = useState(false);

  useEffect(() => {
    try { localStorage.setItem(STORAGE_KEY, JSON.stringify(state)); } catch { /* quota / private mode — non-fatal */ }
  }, [state]);

  const set = useCallback((key: string, val: string) => {
    setState((s) => ({ ...s, answers: { ...s.answers, [key]: val } }));
  }, []);
  const a = state.answers;

  const addBug = () => setState((s) => ({ ...s, bugs: [...s.bugs, { where: "", expected: "", actual: "", evidence: "", severity: "Minor" }] }));
  const setBug = (i: number, k: keyof Bug, v: string) =>
    setState((s) => ({ ...s, bugs: s.bugs.map((b, j) => (j === i ? { ...b, [k]: v } : b)) }));
  const delBug = (i: number) => setState((s) => ({ ...s, bugs: s.bugs.filter((_, j) => j !== i) }));

  const reset = () => {
    if (window.confirm("Clear all your answers on this device? This cannot be undone.")) setState(EMPTY);
  };

  /* tallies (derived, not stored) */
  const tally = useMemo(() => {
    const uiPass = UI.filter((u) => a[u.id] === "P").length;
    const uiFail = UI.filter((u) => a[u.id] === "F").length;
    const apiPass = API.filter((x) => a[x.id] === "P").length;
    const apiFail = API.filter((x) => a[x.id] === "F").length;
    const filingPass = FILINGS.filter((n) => a[`F${n}_verdict`] === "P").length;
    const filingFail = FILINGS.filter((n) => a[`F${n}_verdict`] === "F").length;
    return { uiPass, uiFail, apiPass, apiFail, filingPass, filingFail };
  }, [a]);

  const toMarkdown = useCallback((): string => {
    const L: string[] = [];
    const box = (v?: string, on = "P") => (v === on ? "[x]" : "[ ]");
    L.push("# Research app — QA validation report", "");
    L.push(`- Intern: ${a.internName || "____"}   Mentor: ${a.mentorName || "____"}   Date: ${a.date || "____"}`, "");
    L.push("## 1. Setup");
    for (const s of SETUP) L.push(`- ${a[s.id] === "1" ? "[x]" : "[ ]"} ${s.id} ${s.label}${s.text && a[`${s.id}_text`] ? ` — ${a[`${s.id}_text`]}` : ""}`);
    L.push("", "## 2. UI checklist", "| # | Feature | Result | Notes |", "|---|---|---|---|");
    for (const u of UI) L.push(`| ${u.id} | ${u.feature} | ${a[u.id] || "—"} | ${(a[`${u.id}_note`] || "").replace(/\|/g, "/")} |`);
    L.push("", "## 3. Data / source-of-truth (per filing)");
    for (const n of FILINGS) {
      const any = FILING_FIELDS.some((f) => a[`F${n}_${f.id}${f.kind === "compare" ? "_app" : ""}`]) || a[`F${n}_verdict`];
      if (!any) continue;
      L.push(`### Filing #${n} — verdict: ${a[`F${n}_verdict`] || "—"}`);
      L.push("| Field | App shows | Source shows | Match |", "|---|---|---|---|");
      for (const f of FILING_FIELDS) {
        if (f.kind === "compare") {
          L.push(`| ${f.label} | ${(a[`F${n}_${f.id}_app`] || "").replace(/\|/g, "/")} | ${(a[`F${n}_${f.id}_src`] || "").replace(/\|/g, "/")} |  |`);
        } else {
          L.push(`| ${f.label} |  |  | ${a[`F${n}_${f.id}`] === "y" ? "✓" : a[`F${n}_${f.id}`] === "n" ? "✗" : "—"} |`);
        }
      }
      if (a[`F${n}_source`]) L.push(`- Source link: ${a[`F${n}_source`]}`);
      L.push("");
    }
    L.push("## 4. API / DB spot-check", "| # | Endpoint | Result | Notes |", "|---|---|---|---|");
    for (const x of API) L.push(`| ${x.id} | \`${x.endpoint}\` | ${a[x.id] || "—"} | ${(a[`${x.id}_note`] || "").replace(/\|/g, "/")} |`);
    L.push("", "## 5. Bug log", "| # | Where | Expected | Actual | Evidence | Severity |", "|---|---|---|---|---|---|");
    state.bugs.forEach((b, i) =>
      L.push(`| B${i + 1} | ${b.where} | ${b.expected} | ${b.actual} | ${b.evidence} | ${b.severity} |`.replace(/\n/g, " ")));
    L.push("", "## 6. Verdict",
      `- UI: ${tally.uiPass}/${UI.length} PASS   Data: ${tally.filingPass}/${FILINGS.length} filings   API: ${tally.apiPass}/${API.length}`,
      `- Overall: ${a.overall || "—"}`, "", "### Summary", a.summary || "");
    void box; // (box helper kept for readability; setup uses inline form above)
    return L.join("\n");
  }, [a, state.bugs, tally]);

  const copyReport = async () => {
    const md = toMarkdown();
    try {
      await navigator.clipboard.writeText(md);
      setCopied(true);
      window.setTimeout(() => setCopied(false), 1800);
    } catch {
      // clipboard blocked — fall back to a download so the intern never loses work
      downloadReport();
    }
  };
  const downloadReport = () => {
    const blob = new Blob([toMarkdown()], { type: "text/markdown" });
    const url = URL.createObjectURL(blob);
    const el = document.createElement("a");
    el.href = url; el.download = "research-qa-report.md";
    document.body.appendChild(el); el.click(); el.remove();
    URL.revokeObjectURL(url);
  };

  return (
    <div className="qa-screen research-screen" data-testid="qa-page">
      {/* header */}
      <header className="qa-head">
        <Link to="/research" className="qa-back" data-testid="qa-back"><ArrowLeft size={16} /> Research</Link>
        <span className="nv-serif qa-title"><ClipboardCheck size={18} /> QA validation exercise</span>
        <span style={{ flex: 1 }} />
        <div className="qa-actions">
          <button type="button" className="qa-btn" onClick={copyReport} data-testid="qa-copy">
            <Copy size={14} /> {copied ? "Copied!" : "Copy report"}
          </button>
          <button type="button" className="qa-btn" onClick={downloadReport} data-testid="qa-download"><Download size={14} /> .md</button>
          <button type="button" className="qa-btn ghost" onClick={reset} data-testid="qa-reset"><RotateCcw size={14} /> Reset</button>
        </div>
      </header>

      {/* tabs */}
      <div className="qa-tabs">
        <button className={`qa-tab ${tab === "overview" ? "on" : ""}`} onClick={() => setTab("overview")} data-testid="qa-tab-overview">
          <BookOpen size={14} /> Overview
        </button>
        <button className={`qa-tab ${tab === "checklist" ? "on" : ""}`} onClick={() => setTab("checklist")} data-testid="qa-tab-checklist">
          <ListChecks size={14} /> Checklist
        </button>
      </div>

      <div className="qa-body">
        {tab === "overview" ? <Overview /> : (
          <div className="qa-checklist" data-testid="qa-checklist">
            <p className="qa-note">
              Everything you type is saved in <strong>this browser only</strong> (nothing is sent to a server).
              Use <strong>Copy report</strong> when you're done to hand in a Markdown summary.
            </p>

            {/* golden rules */}
            <section className="qa-card">
              <h3>Golden rules</h3>
              <ol className="qa-rules">
                <li>"It loaded" is not "it's correct." Prove the screen works <em>and</em> the data is true against the original source.</li>
                <li>The original BSE/NSE document is the source of truth — not the app, not this page, not memory.</li>
                <li>Never fake evidence. If blocked, write <code>BLOCKED: why</code> — that's a valid result.</li>
                <li>A discrepancy is a finding, not your failure. Log it.</li>
                <li>Known quirks: some filings have blank category/impact (sort last); some old BSE links 404. Log, don't panic.</li>
              </ol>
            </section>

            {/* setup */}
            <section className="qa-card">
              <h3>1 · Setup</h3>
              {SETUP.map((s) => (
                <div className="qa-row check" key={s.id}>
                  <label className="qa-check">
                    <input type="checkbox" checked={a[s.id] === "1"} onChange={(e) => set(s.id, e.target.checked ? "1" : "")}
                           data-testid={`setup-${s.id}`} />
                    <span><strong>{s.id}</strong> {s.label}<em className="qa-hint">{s.hint}</em></span>
                  </label>
                  {s.text && (
                    <input className="qa-text" placeholder={s.text} value={a[`${s.id}_text`] || ""}
                           onChange={(e) => set(`${s.id}_text`, e.target.value)} />
                  )}
                </div>
              ))}
            </section>

            {/* UI */}
            <section className="qa-card">
              <h3>2 · UI functional checklist</h3>
              {UI.map((u) => (
                <div className="qa-row ui" key={u.id}>
                  <div className="qa-row-main">
                    <div className="qa-row-title"><strong>{u.id}</strong> {u.feature}
                      {u.testid !== "—" && <code className="qa-tid">{u.testid}</code>}
                    </div>
                    <div className="qa-exp">Expected: {u.expected}</div>
                    <input className="qa-text" placeholder="Notes / what you saw"
                           value={a[`${u.id}_note`] || ""} onChange={(e) => set(`${u.id}_note`, e.target.value)} />
                  </div>
                  <PassFail value={a[u.id]} onChange={(v) => set(u.id, v)} testid={`pf-${u.id}`} />
                </div>
              ))}
            </section>

            {/* data / source-of-truth */}
            <section className="qa-card">
              <h3>3 · Data / source-of-truth ⭐</h3>
              <p className="qa-exp">
                For 5 filings, open the <strong>original BSE/NSE document</strong> and compare. The PDF wins.
                An AI summary that invents a number not in the PDF is a <strong>data bug</strong> — the whole point.
              </p>
              {FILINGS.map((n) => (
                <div className="qa-filing" key={n} data-testid={`filing-${n}`}>
                  <div className="qa-filing-head">
                    <strong>Filing #{n}</strong>
                    <PassFail value={a[`F${n}_verdict`]} onChange={(v) => set(`F${n}_verdict`, v)} testid={`pf-F${n}`} />
                  </div>
                  {FILING_FIELDS.map((f) => (
                    <div className="qa-field" key={f.id}>
                      <span className="qa-field-label">{f.label}</span>
                      {f.kind === "compare" ? (
                        <>
                          <input className="qa-text sm" placeholder="app shows" value={a[`F${n}_${f.id}_app`] || ""}
                                 onChange={(e) => set(`F${n}_${f.id}_app`, e.target.value)} />
                          <input className="qa-text sm" placeholder="source shows" value={a[`F${n}_${f.id}_src`] || ""}
                                 onChange={(e) => set(`F${n}_${f.id}_src`, e.target.value)} />
                        </>
                      ) : (
                        <MatchToggle value={a[`F${n}_${f.id}`]} onChange={(v) => set(`F${n}_${f.id}`, v)} />
                      )}
                    </div>
                  ))}
                  <input className="qa-text" placeholder="Source-of-truth link (BSE/NSE URL or PDF)"
                         value={a[`F${n}_source`] || ""} onChange={(e) => set(`F${n}_source`, e.target.value)} />
                </div>
              ))}
            </section>

            {/* API */}
            <section className="qa-card">
              <h3>4 · API / DB spot-check</h3>
              <p className="qa-exp">Hit the real endpoint with your session_token and confirm it matches the UI.</p>
              {API.map((x) => (
                <div className="qa-row ui" key={x.id}>
                  <div className="qa-row-main">
                    <div className="qa-row-title"><strong>{x.id}</strong> <code className="qa-tid">{x.endpoint}</code></div>
                    <div className="qa-exp">Check: {x.check}</div>
                    <input className="qa-text" placeholder="Notes / what the response showed"
                           value={a[`${x.id}_note`] || ""} onChange={(e) => set(`${x.id}_note`, e.target.value)} />
                  </div>
                  <PassFail value={a[x.id]} onChange={(v) => set(x.id, v)} testid={`pf-${x.id}`} />
                </div>
              ))}
            </section>

            {/* bugs */}
            <section className="qa-card">
              <h3>5 · Bug / discrepancy log</h3>
              {state.bugs.length === 0 && <p className="qa-exp">No bugs logged yet.</p>}
              {state.bugs.map((b, i) => (
                <div className="qa-bug" key={i} data-testid={`bug-${i}`}>
                  <div className="qa-bug-top">
                    <strong>B{i + 1}</strong>
                    <select className="qa-sev" value={b.severity} onChange={(e) => setBug(i, "severity", e.target.value)}>
                      {["Blocker", "Major", "Minor", "Cosmetic"].map((s) => <option key={s}>{s}</option>)}
                    </select>
                    <button type="button" className="qa-btn ghost sm" onClick={() => delBug(i)} aria-label="remove bug"><Trash2 size={13} /></button>
                  </div>
                  <input className="qa-text" placeholder="Where (U#/Filing#/A#)" value={b.where} onChange={(e) => setBug(i, "where", e.target.value)} />
                  <input className="qa-text" placeholder="What you expected" value={b.expected} onChange={(e) => setBug(i, "expected", e.target.value)} />
                  <input className="qa-text" placeholder="What actually happened" value={b.actual} onChange={(e) => setBug(i, "actual", e.target.value)} />
                  <input className="qa-text" placeholder="Evidence (source link / screenshot name)" value={b.evidence} onChange={(e) => setBug(i, "evidence", e.target.value)} />
                </div>
              ))}
              <button type="button" className="qa-btn" onClick={addBug} data-testid="qa-add-bug"><Plus size={14} /> Add bug</button>
            </section>

            {/* verdict */}
            <section className="qa-card">
              <h3>6 · Verdict &amp; sign-off</h3>
              <div className="qa-tallies" data-testid="qa-tallies">
                <span>UI <strong>{tally.uiPass}</strong>/{UI.length}</span>
                <span>Data <strong>{tally.filingPass}</strong>/{FILINGS.length}</span>
                <span>API <strong>{tally.apiPass}</strong>/{API.length}</span>
                <span>Bugs <strong>{state.bugs.length}</strong></span>
              </div>
              <textarea className="qa-text area" placeholder="One-paragraph summary: what's solid, what's broken, your biggest data-correctness concern."
                        value={a.summary || ""} onChange={(e) => set("summary", e.target.value)} data-testid="qa-summary" />
              <div className="qa-overall">
                {["PASS", "PASS-with-minor-bugs", "FAIL — data ≠ source"].map((o) => (
                  <button type="button" key={o} className={`qa-o-btn ${a.overall === o ? "on" : ""}`} onClick={() => set("overall", o)}>{o}</button>
                ))}
              </div>
              <div className="qa-signoff">
                <input className="qa-text sm" placeholder="Intern name" value={a.internName || ""} onChange={(e) => set("internName", e.target.value)} />
                <input className="qa-text sm" placeholder="Mentor name" value={a.mentorName || ""} onChange={(e) => set("mentorName", e.target.value)} />
                <input className="qa-text sm" placeholder="Date" value={a.date || ""} onChange={(e) => set("date", e.target.value)} />
              </div>
            </section>
          </div>
        )}
      </div>
    </div>
  );
}

/* ── Overview tab (from research-tab-overview.md) ─────────────────────────── */

function Overview() {
  return (
    <div className="qa-overview" data-testid="qa-overview">
      <section className="qa-card">
        <h3>What the Research tab is</h3>
        <p>
          The Research tab (the app calls it <em>"Filings Intelligence"</em>) is where a user reads Indian-market
          corporate filings — board meetings, results, concall transcripts — turned into something readable. It pulls
          the raw filings from the exchanges (BSE/NSE), then layers <strong>AI-derived</strong> help on top: a short
          summary per filing, a "headline metric", a personalised <em>"Read for you today"</em> shortlist, and an
          <em> "in your portfolio"</em> badge.
        </p>
        <p className="qa-key">
          The one idea to hold onto: some of what you see is <strong>raw</strong> (straight from the exchange) and some
          is <strong>derived</strong> (an AI generated it from the PDF). Testing = the UI works <strong>and</strong> the
          derived data is faithful to the original filing.
        </p>
      </section>

      <section className="qa-card">
        <h3>Where it lives</h3>
        <table className="qa-table">
          <tbody>
            <tr><td>URL (staging)</td><td><code>/v5/research</code> (login-gated)</td></tr>
            <tr><td>Frontend</td><td><code>frontend-v5/src/pages/Research/index.tsx</code></td></tr>
            <tr><td>Backend</td><td><code>backend/routes/filings.py</code> (<code>/api/filings/…</code>)</td></tr>
          </tbody>
        </table>
      </section>

      <section className="qa-card">
        <h3>Raw vs derived — what to check against what</h3>
        <table className="qa-table">
          <thead><tr><th>On screen</th><th>Source</th><th>Raw / derived</th></tr></thead>
          <tbody>
            <tr><td>All-filings list, issuer, date, subject</td><td><code>nidp.corporate_announcements</code></td><td>Raw — check vs exchange</td></tr>
            <tr><td>MATERIAL sort, Read-for-you shortlist</td><td><code>/signals</code> over that table</td><td>Derived (selection)</td></tr>
            <tr><td><strong>AI summary + headline metric</strong></td><td><code>nidp.corporate_event_signals</code></td><td><strong>Derived — check hardest</strong></td></tr>
            <tr><td>Original PDF link</td><td><code>nidp.documents.source_url</code></td><td><strong>Raw — the source of truth</strong></td></tr>
            <tr><td>"In your portfolio" badge</td><td><code>/portfolio-held</code> (Mongo)</td><td>Derived (a match)</td></tr>
          </tbody>
        </table>
        <p className="qa-exp">Raw fields → check against the exchange website. Derived fields → check against the PDF's actual content.</p>
      </section>

      <section className="qa-card">
        <h3>How to use it (feature tour)</h3>
        <ul className="qa-tour">
          <li><strong>Read for you today</strong> — top row, up to 3 cards; toggle today ↔ latest; click a card → drawer.</li>
          <li><strong>Portfolio badge</strong> — a pill flags filings from companies you hold.</li>
          <li><strong>Search a company</strong> — narrows the feed to that company (scope chip); clear to go back.</li>
          <li><strong>Thematic starters</strong> — pre-written prompts (Curated / History / Favorites) that run the copilot.</li>
          <li><strong>Ask bar</strong> — plain-English question; answer comes back with clickable source chips.</li>
          <li><strong>All filings</strong> — sort MATERIAL / LATEST; filter with facet chips.</li>
          <li><strong>Expand a filing</strong> — AI-insight panel: summary, sections, page citations.</li>
          <li><strong>Documents</strong> — per-company library; download opens the original PDF.</li>
          <li><strong>Alerts</strong> — pick types/channels. <em>Delivery is intentionally OFF — saving the preference is the only expected behaviour.</em></li>
        </ul>
      </section>

      <section className="qa-card">
        <h3>How to test it (the short version)</h3>
        <p>Two dimensions, always both — the house rule: <strong>the app runs AND the data is real.</strong></p>
        <ol className="qa-rules">
          <li><strong>UI test</strong> — does each feature work (loads, clicks, drawer, sort, search, download)?</li>
          <li><strong>Data / source-of-truth test</strong> — open the original BSE/NSE document and confirm raw fields match the exchange <em>and</em> derived fields (summary, headline metric, page citation) are faithful to the PDF.</li>
          <li><strong>Cross-check</strong> — hit the endpoint and confirm it returns what the screen showed.</li>
        </ol>
        <p className="qa-exp">Switch to the <strong>Checklist</strong> tab to record your run and export a report.</p>
      </section>
    </div>
  );
}
