import React, { useCallback, useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import { GoogleLogin } from "@react-oauth/google";
import { useAuth } from "@/context/AuthContext";
import api from "../../api/client";
import {
  runCasIngestion,
  getActivePortfolio,
  resetCurrentUser,
} from "../../api/portfolioIngestion";

/**
 * COCKPIT_PATH — where "Take me to the cockpit" / "Skip for now" sends a
 * fresh-snapshot user. Relative to BrowserRouter basename="/v4".
 */
const COCKPIT_PATH = "/landing";

/**
 * Snapshot is "stale" when today's calendar month is strictly after the
 * statement's calendar month. CAS statements are monthly, so once a new month
 * begins there is likely a newer CAS available — we prompt the user to refresh.
 */
function isSnapshotStale(snapshot) {
  if (!snapshot || !snapshot.statement_to) return false;
  const iso =
    snapshot.statement_to.length === 10
      ? `${snapshot.statement_to}T00:00:00Z`
      : snapshot.statement_to;
  const stmt = new Date(iso);
  if (Number.isNaN(stmt.getTime())) return false;
  const now = new Date();
  const stmtYM = stmt.getUTCFullYear() * 12 + stmt.getUTCMonth();
  const nowYM = now.getUTCFullYear() * 12 + now.getUTCMonth();
  return nowYM > stmtYM;
}

/**
 * Backend (V3 portfolio_ingestion.assemble) returns:
 *   allocation: [{ asset_class, value, pct }, …]   ← canonical
 * Tolerate dict-of-pcts too (some response paths may flatten it) so the V4
 * adapter never breaks if either shape lands.
 */
function normaliseAllocation(alloc) {
  if (!alloc) return [];
  if (Array.isArray(alloc)) {
    return alloc
      .map((row) => ({
        label: String(row.asset_class || row.label || "—"),
        value: Number(row.value ?? 0),
        pct: row.pct != null ? Number(row.pct) : null,
      }))
      .filter((r) => r.value > 0 || (r.pct != null && r.pct > 0));
  }
  if (typeof alloc === "object") {
    return Object.entries(alloc)
      .map(([label, v]) => ({
        label,
        value: typeof v === "number" ? v : Number(v) || 0,
        pct: null,
      }))
      .filter((r) => r.value > 0);
  }
  return [];
}

function hasMeaningfulAllocation(alloc) {
  return normaliseAllocation(alloc).length > 0;
}

function toNumberOrNull(v) {
  if (v == null || v === "") return null;
  const n = Number(v);
  return Number.isFinite(n) ? n : null;
}

/**
 * V4 Onboarding — 3-mode CAS ingestion entry point.
 *
 * Flow:
 *   1. Auth gate: if user isn't signed in, render a Google sign-in card.
 *   2. Mode pick: user clicks CAS-PDF / Gmail / CDSL card.
 *   3. runCasIngestion(mode) — opens the @cas-parser/connect widget, lazy-
 *      loaded; the V4 service mints a CASParser token + posts the SDK output
 *      to /api/cas/sdk-callback under the hood.
 *   4. Success: show the imported portfolio summary + CTA into the app.
 *
 * Status states: idle | importing | done | error
 * On cancel (widget closed) we fall back to idle silently.
 */

const MODES = [
  {
    id: "gmail",
    title: "Import CAS from Gmail",
    body:
      "Nivesh finds your CAS statement email and reads it — no file, no password.",
    badge: "Fastest",
    footer: "Read-only · scans only CAS emails · revoke anytime.",
    accent: "var(--v4-saffron)",
  },
  {
    id: "cas",
    title: "Upload CAS statement",
    body:
      "Already have the CAS PDF from CAMS, KFintech, NSDL or CDSL? Drop it in.",
    badge: null,
    footer: "Encrypted in transit. PDF password collected by the widget.",
    accent: "var(--v4-indigo)",
  },
  {
    id: "cdsl",
    title: "Fetch from CDSL (OTP)",
    body:
      "Get the latest demat position straight from CDSL — verify with an OTP.",
    badge: null,
    footer: "OTP sent to your CDSL-registered mobile · no PDF download.",
    accent: "var(--v4-moss)",
  },
];

export default function Onboarding() {
  const {
    user,
    loading: authLoading,
    loginWithGoogle,
    setAuthError,
    googleClientId,
    checkAuth,
  } = useAuth();
  const navigate = useNavigate();
  const [status, setStatus] = useState("idle"); // idle | importing | done | error
  const [statusMessage, setStatusMessage] = useState(null);
  const [result, setResult] = useState(null);
  const [activePortfolio, setActivePortfolio] = useState(null);
  const [loadingPortfolio, setLoadingPortfolio] = useState(false);
  const [forceReimport, setForceReimport] = useState(false);
  const [error, setError] = useState(null);

  // On mount (once signed in) AND after every successful ingest, fetch the
  // active portfolio. This drives the "already set up" vs "show import cards"
  // routing AND the stale-snapshot banner.
  useEffect(() => {
    if (!user) return;
    let cancelled = false;
    setLoadingPortfolio(true);
    getActivePortfolio()
      .then((data) => {
        if (!cancelled) setActivePortfolio(data);
      })
      .catch(() => {
        if (!cancelled) setActivePortfolio(null);
      })
      .finally(() => {
        if (!cancelled) setLoadingPortfolio(false);
      });
    return () => {
      cancelled = true;
    };
    // Re-fetch when the user signs in or status flips to done.
  }, [user, status]);

  // On first successful ingest, flip the V2 onboarding_completed flag so the
  // user is no longer routed back here on subsequent visits. Best-effort — if
  // the call fails we still show the success card, since the snapshot is in.
  useEffect(() => {
    if (status !== "done") return;
    let cancelled = false;
    (async () => {
      try {
        await api.post("/api/user/complete-onboarding", undefined);
        if (!cancelled && typeof checkAuth === "function") {
          await checkAuth();
        }
      } catch {
        /* non-fatal — the snapshot is already active server-side */
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [status, checkAuth]);

  const handleConnect = useCallback(async (mode) => {
    setStatus("importing");
    setStatusMessage(null);
    setError(null);
    setResult(null);

    const out = await runCasIngestion({
      mode,
      onStatus: setStatusMessage,
    });

    if (out.cancelled) {
      setStatus("idle");
      setStatusMessage(null);
      return;
    }
    if (!out.ok) {
      setStatus("error");
      setError(out.error?.message || "Something went wrong. Please retry.");
      return;
    }

    setResult(out.response);
    setStatus("done");
  }, []);

  const handleGoogleSuccess = useCallback(
    async (credentialResponse) => {
      try {
        await loginWithGoogle(credentialResponse.credential);
        resetCurrentUser(); // adapter cache: pick up the new user_id on next call
      } catch {
        /* authError surfaced inside loginWithGoogle */
      }
    },
    [loginWithGoogle],
  );

  // ───────────────────────────── Render ─────────────────────────────

  if (authLoading) {
    return <Centered>Loading…</Centered>;
  }

  if (!user) {
    return (
      <Shell>
        <Header />
        <main style={mainCenteredStyle}>
          <div style={authCardStyle}>
            <div style={eyebrowStyle}>STEP 1 OF 2</div>
            <h1 style={authHeroStyle}>
              Sign in to bring<br />
              <em style={{ color: "var(--v4-saffron)", fontStyle: "italic" }}>
                your portfolio
              </em>{" "}
              in.
            </h1>
            <p style={authSubStyle}>
              We use Google sign-in so you never set another password. Your
              account is keyed to the email you sign in with.
            </p>
            <div style={{ display: "flex", justifyContent: "center", marginTop: 24 }}>
              {googleClientId ? (
                <GoogleLogin
                  onSuccess={handleGoogleSuccess}
                  onError={() =>
                    setAuthError("Google sign-in was cancelled or failed.")
                  }
                  size="large"
                  shape="pill"
                  theme="filled_black"
                  text="signin_with"
                />
              ) : (
                <div style={{ color: "var(--v4-ink-mute)", fontSize: 13 }}>
                  Loading sign-in…
                </div>
              )}
            </div>
            <div style={complianceStyle}>Bank-grade encryption · SEBI-aware</div>
          </div>
        </main>
      </Shell>
    );
  }

  // Authenticated. Decide what to show:
  //   1. status === "done"   → success card (just finished an import)
  //   2. has fresh portfolio + not forcing re-import → "already set up" card
  //   3. has stale portfolio → stale banner above 3 mode cards
  //   4. no portfolio (first-time / not onboarded) → just 3 mode cards
  const snapshot = activePortfolio?.snapshot;
  const hasActivePortfolio = !!(snapshot && snapshot.is_active !== false);
  const stale = hasActivePortfolio && isSnapshotStale(snapshot);
  const showAlreadySetUp =
    status === "idle" && hasActivePortfolio && !stale && !forceReimport;

  return (
    <Shell>
      <Header email={user.email} />
      <main style={mainStyle}>
        {showAlreadySetUp ? (
          <>
            <div style={eyebrowStyle}>YOU'RE SET UP</div>
            <h1 style={heroStyle}>
              Your portfolio<br />
              is <em style={{ color: "var(--v4-saffron)", fontStyle: "italic" }}>ready</em>.
            </h1>
            <p style={subStyle}>
              Latest CAS — {snapshot.period || "current"} — is live in your
              account. Jump into the cockpit, or import a newer statement.
            </p>
            <AlreadySetUpCard
              snapshot={snapshot}
              portfolio={activePortfolio?.portfolio}
              onContinue={() => (navigate(COCKPIT_PATH))}
              onReimport={() => setForceReimport(true)}
            />
          </>
        ) : (
          <>
            <div style={eyebrowStyle}>
              {stale ? "REFRESH YOUR CAS" : "BRING YOUR PORTFOLIO IN"}
            </div>
            <h1 style={heroStyle}>
              {stale ? (
                <>
                  Your CAS is from<br />
                  <em style={{ color: "var(--v4-saffron)", fontStyle: "italic" }}>
                    {snapshot.period}
                  </em>{" "}— time to refresh.
                </>
              ) : (
                <>
                  Pick the path<br />
                  that's{" "}
                  <em style={{ color: "var(--v4-saffron)", fontStyle: "italic" }}>fastest</em>{" "}
                  for you.
                </>
              )}
            </h1>
            <p style={subStyle}>
              {stale
                ? `A newer CAS is likely available now that ${monthYearLabel(new Date())} has started. Import the latest one to keep your insights accurate.`
                : "We read your CAS once. Everything you see after that — health, risk, actions — is grounded in what you actually own."}
            </p>

            {stale && (
              <StaleSnapshotBanner
                period={snapshot.period}
                onSkip={() => (navigate(COCKPIT_PATH))}
              />
            )}

            {status === "error" && (
              <ErrorBanner message={error} onDismiss={() => setStatus("idle")} />
            )}

            {status === "done" && result ? (
              <SuccessCard
                result={result}
                activePortfolio={activePortfolio}
                onContinue={() => (navigate(COCKPIT_PATH))}
                onRetry={() => {
                  setStatus("idle");
                  setResult(null);
                }}
              />
            ) : (
              <ModeGrid
                disabled={status === "importing"}
                onPick={handleConnect}
              />
            )}

            {status === "importing" && (
              <ImportingOverlay message={statusMessage || "Working…"} />
            )}

            {forceReimport && status === "idle" && (
              <div style={{ marginTop: 16, textAlign: "center" }}>
                <button
                  type="button"
                  onClick={() => setForceReimport(false)}
                  style={inlineLinkStyle}
                >
                  ← Back to your current portfolio
                </button>
              </div>
            )}
          </>
        )}

        <div style={footerStrapStyle}>
          🔒 Bank-grade encryption · 🛡️ Read-only · ⚖️ SEBI-aware
        </div>
      </main>
    </Shell>
  );
}

function monthYearLabel(d) {
  return d.toLocaleDateString("en-IN", { month: "long", year: "numeric" });
}

/* ───────── Sub-components ───────── */

function Shell({ children }) {
  return <div style={pageStyle}>{children}</div>;
}

function Header({ email }) {
  return (
    <header style={navStyle}>
      <div style={brandStyle}>
        <div style={markStyle}>न</div>
        <div>
          <div
            style={{
              fontFamily: "var(--v4-display)",
              fontWeight: 600,
              fontSize: 17,
              color: "var(--v4-ink)",
            }}
          >
            Nivesh
          </div>
          <div
            style={{
              fontFamily: "var(--v4-mono)",
              fontSize: 9,
              letterSpacing: 1.4,
              color: "var(--v4-ink-faint)",
            }}
          >
            AI COPILOT
          </div>
        </div>
      </div>
      {email ? (
        <div style={signedInPillStyle}>
          <span style={{ width: 6, height: 6, borderRadius: "50%", background: "var(--v4-moss)" }} />
          Signed in as <span style={{ color: "var(--v4-ink)" }}>{email}</span>
        </div>
      ) : null}
    </header>
  );
}

function ModeGrid({ disabled, onPick }) {
  return (
    <section style={gridStyle}>
      {MODES.map((m) => (
        <button
          key={m.id}
          type="button"
          disabled={disabled}
          onClick={() => onPick(m.id)}
          style={{
            ...modeCardStyle,
            opacity: disabled ? 0.5 : 1,
            cursor: disabled ? "not-allowed" : "pointer",
          }}
        >
          <div style={{ display: "flex", alignItems: "flex-start", gap: 12 }}>
            <div
              style={{
                ...modeIconStyle,
                background: m.accent,
                color: "#160e07",
              }}
            >
              {m.id === "gmail" ? "✉" : m.id === "cas" ? "📄" : "🔐"}
            </div>
            {m.badge ? <span style={badgeStyle}>{m.badge}</span> : null}
          </div>
          <div style={{ fontFamily: "var(--v4-display)", fontSize: 19, color: "var(--v4-ink)", marginTop: 16 }}>
            {m.title}
          </div>
          <div style={{ fontSize: 13, color: "var(--v4-ink-mute)", lineHeight: 1.55, marginTop: 8 }}>
            {m.body}
          </div>
          <div
            style={{
              fontFamily: "var(--v4-mono)",
              fontSize: 9,
              letterSpacing: 1.1,
              color: "var(--v4-ink-faint)",
              textTransform: "uppercase",
              marginTop: 18,
            }}
          >
            {m.footer}
          </div>
        </button>
      ))}
    </section>
  );
}

function ImportingOverlay({ message }) {
  return (
    <div style={overlayStyle}>
      <div style={overlayCardStyle}>
        <div style={spinnerStyle} />
        <div style={overlayMsgStyle}>{message}</div>
      </div>
      <style>{`@keyframes v4-spin-o { to { transform: rotate(360deg); } }`}</style>
    </div>
  );
}

function ErrorBanner({ message, onDismiss }) {
  return (
    <div style={errorBannerStyle}>
      <div style={{ display: "flex", gap: 12, alignItems: "flex-start" }}>
        <span style={{ fontSize: 18 }}>⚠️</span>
        <div>
          <div style={{ fontFamily: "var(--v4-display)", fontSize: 15, color: "var(--v4-ink)", marginBottom: 4 }}>
            Couldn't bring that one in
          </div>
          <div style={{ fontSize: 13, color: "var(--v4-ink-dim)", lineHeight: 1.5 }}>
            {message}
          </div>
        </div>
        <button onClick={onDismiss} style={dismissBtnStyle}>
          Retry
        </button>
      </div>
    </div>
  );
}

/**
 * Shown when the user already has a fresh active portfolio and lands on the
 * onboarding URL. Default action is "Open the cockpit" — they can still
 * trigger a re-import via the secondary CTA, which flips forceReimport and
 * reveals the 3 mode cards.
 */
function AlreadySetUpCard({ snapshot, portfolio, onContinue, onReimport }) {
  const period = snapshot?.period;
  const holdingsCount = portfolio?.holdings_count;
  const totalValue = toNumberOrNull(portfolio?.total_value ?? snapshot?.total_value);
  const allocation = portfolio?.allocation;
  const topHoldings = portfolio?.top_holdings;
  return (
    <section style={successCardStyle}>
      <div style={{ display: "flex", alignItems: "center", gap: 10, marginBottom: 18 }}>
        <span style={{ width: 8, height: 8, borderRadius: "50%", background: "var(--v4-moss)" }} />
        <span style={{ fontFamily: "var(--v4-mono)", fontSize: 10, letterSpacing: 1.2, color: "var(--v4-moss)" }}>
          ACTIVE SNAPSHOT
        </span>
      </div>
      <div style={{ fontFamily: "var(--v4-display)", fontSize: 26, color: "var(--v4-ink)", marginBottom: 8 }}>
        Latest CAS — {period || "current"}
      </div>
      <div style={{ fontSize: 14, color: "var(--v4-ink-dim)", marginBottom: 24 }}>
        Your portfolio is live in Nivesh. Open the cockpit to see your health
        score, actions, and goals.
      </div>

      <div style={statRowStyle}>
        <Stat label="Period" value={period || "—"} />
        <Stat label="Holdings" value={holdingsCount != null ? String(holdingsCount) : "—"} />
        <Stat label="Total value" value={formatInr(totalValue)} />
      </div>

      {hasMeaningfulAllocation(allocation) ? (
        <div style={{ marginTop: 24 }}>
          <div style={eyebrowStyle}>ALLOCATION</div>
          <AllocationStrip allocation={allocation} />
        </div>
      ) : null}

      <TopHoldings holdings={topHoldings} />

      <div style={{ display: "flex", gap: 12, marginTop: 28, flexWrap: "wrap" }}>
        <button style={ctaPrimaryStyle} onClick={onContinue}>
          Open the cockpit →
        </button>
        <button style={ctaGhostStyle} onClick={onReimport}>
          Import a newer CAS
        </button>
      </div>
    </section>
  );
}

/**
 * Amber soft-warning banner shown above the 3 mode cards when the active
 * snapshot's calendar month is older than the current month — likely a newer
 * CAS is available.
 */
function StaleSnapshotBanner({ period, onSkip }) {
  return (
    <div style={staleBannerStyle}>
      <div style={{ display: "flex", gap: 12, alignItems: "flex-start" }}>
        <span style={{ fontSize: 18 }}>🟡</span>
        <div style={{ flex: 1 }}>
          <div style={{ fontFamily: "var(--v4-display)", fontSize: 15, color: "var(--v4-ink)", marginBottom: 4 }}>
            Your snapshot is from {period}
          </div>
          <div style={{ fontSize: 13, color: "var(--v4-ink-dim)", lineHeight: 1.5 }}>
            Insights are still computed off this snapshot — but a newer monthly
            CAS is almost certainly available. Import it now so your numbers
            reflect today's portfolio.
          </div>
        </div>
        <button onClick={onSkip} style={dismissBtnStyle}>
          Skip for now
        </button>
      </div>
    </div>
  );
}

function SuccessCard({ result, activePortfolio, onContinue, onRetry }) {
  const period = result?.period || activePortfolio?.snapshot?.period;
  // Total value: prefer the freshly-activated portfolio.total_value, fall back
  // to the snapshot row. Both arrive as Pydantic Decimal → JSON string, so
  // coerce.
  const holdingsCount =
    activePortfolio?.portfolio?.holdings_count ??
    (Array.isArray(result?.portfolio?.top_holdings)
      ? result.portfolio.top_holdings.length
      : null);
  const totalValue = toNumberOrNull(
    activePortfolio?.portfolio?.total_value ??
      result?.portfolio?.total_value ??
      activePortfolio?.snapshot?.total_value,
  );
  const allocation =
    activePortfolio?.portfolio?.allocation || result?.portfolio?.allocation;
  const topHoldings =
    activePortfolio?.portfolio?.top_holdings || result?.portfolio?.top_holdings;
  const isActive = result?.is_active !== false;

  return (
    <section style={successCardStyle}>
      <div style={{ display: "flex", alignItems: "center", gap: 10, marginBottom: 18 }}>
        <span style={{ width: 8, height: 8, borderRadius: "50%", background: "var(--v4-moss)" }} />
        <span style={{ fontFamily: "var(--v4-mono)", fontSize: 10, letterSpacing: 1.2, color: "var(--v4-moss)" }}>
          {isActive ? "ACTIVE SNAPSHOT" : "STORED — INACTIVE"}
        </span>
      </div>
      <div style={{ fontFamily: "var(--v4-display)", fontSize: 28, color: "var(--v4-ink)", marginBottom: 8 }}>
        We've got it.
      </div>
      <div style={{ fontSize: 14, color: "var(--v4-ink-dim)", marginBottom: 24 }}>
        {period ? `Your latest CAS — ${period} — is in.` : "Your portfolio is in."}
      </div>

      <div style={statRowStyle}>
        <Stat label="Period" value={period || "—"} />
        <Stat label="Holdings" value={holdingsCount != null ? String(holdingsCount) : "—"} />
        <Stat label="Total value" value={formatInr(totalValue)} />
      </div>

      {hasMeaningfulAllocation(allocation) ? (
        <div style={{ marginTop: 24 }}>
          <div style={eyebrowStyle}>ALLOCATION</div>
          <AllocationStrip allocation={allocation} />
        </div>
      ) : null}

      <TopHoldings holdings={topHoldings} />

      <div style={{ display: "flex", gap: 12, marginTop: 28, flexWrap: "wrap" }}>
        <button style={ctaPrimaryStyle} onClick={onContinue}>
          Take me to the cockpit →
        </button>
        <button style={ctaGhostStyle} onClick={onRetry}>
          Import another statement
        </button>
      </div>
    </section>
  );
}

function Stat({ label, value }) {
  return (
    <div style={statBoxStyle}>
      <div
        style={{
          fontFamily: "var(--v4-mono)",
          fontSize: 9,
          letterSpacing: 1.1,
          color: "var(--v4-ink-faint)",
          textTransform: "uppercase",
          marginBottom: 6,
        }}
      >
        {label}
      </div>
      <div style={{ fontFamily: "var(--v4-display)", fontSize: 22, color: "var(--v4-ink)" }}>
        {value}
      </div>
    </div>
  );
}

function AllocationStrip({ allocation }) {
  const rows = normaliseAllocation(allocation)
    .sort((a, b) => b.value - a.value)
    .slice(0, 6);
  if (!rows.length) return null;
  const total = rows.reduce((s, r) => s + r.value, 0);
  return (
    <div>
      <div style={{ display: "flex", height: 10, borderRadius: 5, overflow: "hidden", marginTop: 10 }}>
        {rows.map((r, i) => {
          const pct = r.pct != null ? r.pct : total > 0 ? (r.value / total) * 100 : 0;
          return (
            <div
              key={r.label}
              style={{
                width: `${pct}%`,
                background: ALLOC_COLOURS[i % ALLOC_COLOURS.length],
              }}
              title={`${prettyLabel(r.label)}: ${pct.toFixed(1)}% (${formatInr(r.value)})`}
            />
          );
        })}
      </div>
      <div style={{ display: "flex", gap: 14, flexWrap: "wrap", marginTop: 12 }}>
        {rows.map((r, i) => {
          const pct = r.pct != null ? r.pct : total > 0 ? (r.value / total) * 100 : 0;
          return (
            <div key={r.label} style={{ display: "flex", alignItems: "center", gap: 6 }}>
              <div style={{ width: 8, height: 8, borderRadius: 2, background: ALLOC_COLOURS[i % ALLOC_COLOURS.length] }} />
              <div style={{ fontSize: 12, color: "var(--v4-ink-dim)" }}>
                <span style={{ textTransform: "capitalize" }}>{prettyLabel(r.label)}</span>{" "}
                <span style={{ color: "var(--v4-ink-mute)" }}>{pct.toFixed(0)}%</span>{" "}
                <span style={{ color: "var(--v4-ink-faint)" }}>· {formatInr(r.value)}</span>
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
}

const ASSET_CLASS_LABELS = {
  equity: "Equity",
  mf: "Mutual funds",
  mutual_fund: "Mutual funds",
  bond: "Bonds",
  aif: "AIF",
  g_sec: "G-Sec",
  insurance: "Insurance",
  nps: "NPS",
};

function prettyLabel(s) {
  if (!s) return "—";
  const k = String(s).toLowerCase();
  return ASSET_CLASS_LABELS[k] || k.replace(/_/g, " ");
}

/**
 * Lets the user line up the imported portfolio against their CAS PDF line by
 * line — surfaces the top N positions with rupee value and % of total. Pulled
 * from /api/portfolio/me.portfolio.top_holdings (canonical shape).
 */
function TopHoldings({ holdings }) {
  if (!Array.isArray(holdings) || !holdings.length) return null;
  return (
    <div style={{ marginTop: 24 }}>
      <div style={eyebrowStyle}>TOP HOLDINGS</div>
      <div style={topHoldingsListStyle}>
        {holdings.slice(0, 10).map((h, i) => {
          const name = h.name || h.scheme || h.asset_name || "—";
          const value = toNumberOrNull(h.value);
          const pct = h.pct != null ? Number(h.pct) : null;
          return (
            <div key={`${name}-${i}`} style={topHoldingRowStyle}>
              <div
                style={{
                  fontFamily: "var(--v4-mono)",
                  fontSize: 10,
                  color: "var(--v4-ink-faint)",
                  width: 18,
                  flex: "none",
                }}
              >
                {i + 1}
              </div>
              <div style={{ flex: 1, minWidth: 0 }}>
                <div
                  style={{
                    color: "var(--v4-ink)",
                    fontSize: 13,
                    whiteSpace: "nowrap",
                    overflow: "hidden",
                    textOverflow: "ellipsis",
                  }}
                  title={name}
                >
                  {name}
                </div>
                <div
                  style={{
                    fontFamily: "var(--v4-mono)",
                    fontSize: 10,
                    letterSpacing: 0.6,
                    color: "var(--v4-ink-faint)",
                    textTransform: "uppercase",
                    marginTop: 2,
                  }}
                >
                  {prettyLabel(h.asset_class)}
                </div>
              </div>
              <div style={{ textAlign: "right", flex: "none" }}>
                <div style={{ fontFamily: "var(--v4-display)", fontSize: 14, color: "var(--v4-ink)" }}>
                  {formatInr(value)}
                </div>
                {pct != null ? (
                  <div style={{ fontFamily: "var(--v4-mono)", fontSize: 10, color: "var(--v4-ink-faint)" }}>
                    {pct.toFixed(1)}%
                  </div>
                ) : null}
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
}

const ALLOC_COLOURS = ["#ff9248", "#88ab66", "#d9b64a", "#7d7eff", "#df5d5d", "#c2b8a8"];

function Centered({ children }) {
  return (
    <Shell>
      <div style={{ minHeight: "100vh", display: "grid", placeItems: "center", color: "var(--v4-ink-mute)" }}>
        {children}
      </div>
    </Shell>
  );
}

function formatInr(n) {
  // Pydantic Decimal → JSON string in V3 responses; coerce safely.
  if (n == null || n === "") return "—";
  const v = typeof n === "number" ? n : Number(String(n).replace(/,/g, ""));
  if (!Number.isFinite(v)) return "—";
  if (v >= 1e7) return `₹${(v / 1e7).toFixed(2)} Cr`;
  if (v >= 1e5) return `₹${(v / 1e5).toFixed(2)} L`;
  if (v >= 1e3) return `₹${(v / 1e3).toFixed(1)} K`;
  return `₹${Math.round(v).toLocaleString("en-IN")}`;
}

/* ───────── Styles (inline to keep the file self-contained) ───────── */

const pageStyle = {
  minHeight: "100vh",
  background: "var(--v4-bg)",
  color: "var(--v4-ink)",
};

const navStyle = {
  display: "flex",
  alignItems: "center",
  justifyContent: "space-between",
  padding: "18px 32px",
  borderBottom: "1px solid var(--v4-line)",
  position: "sticky",
  top: 0,
  background: "rgba(11,10,8,0.92)",
  backdropFilter: "blur(10px)",
  zIndex: 20,
};

const brandStyle = { display: "flex", alignItems: "center", gap: 12 };

const markStyle = {
  width: 36,
  height: 36,
  borderRadius: 9,
  background: "linear-gradient(150deg, var(--v4-saffron), var(--v4-saffron-lo))",
  display: "grid",
  placeItems: "center",
  fontFamily: "var(--v4-display)",
  fontWeight: 600,
  color: "#2a1605",
  fontSize: 19,
};

const signedInPillStyle = {
  fontFamily: "var(--v4-mono)",
  fontSize: 10,
  letterSpacing: 0.6,
  color: "var(--v4-ink-mute)",
  background: "var(--v4-s2)",
  border: "1px solid var(--v4-line)",
  padding: "6px 12px",
  borderRadius: 999,
  display: "flex",
  alignItems: "center",
  gap: 8,
  textTransform: "uppercase",
};

const mainStyle = {
  maxWidth: 1080,
  margin: "0 auto",
  padding: "60px 32px 80px",
  position: "relative",
};

const mainCenteredStyle = {
  maxWidth: 560,
  margin: "0 auto",
  padding: "100px 32px",
  textAlign: "center",
};

const authCardStyle = {
  background: "linear-gradient(168deg, var(--v4-hero-a), var(--v4-hero-b))",
  border: "1px solid var(--v4-line-strong)",
  borderRadius: "var(--v4-r-xl)",
  padding: "44px 36px",
};

const authHeroStyle = {
  fontFamily: "var(--v4-display)",
  fontWeight: 500,
  fontSize: "clamp(28px, 4.5vw, 44px)",
  lineHeight: 1.1,
  marginBottom: 18,
};

const authSubStyle = {
  fontSize: 15,
  color: "var(--v4-ink-dim)",
  lineHeight: 1.55,
  maxWidth: 440,
  margin: "0 auto",
};

const heroStyle = {
  fontFamily: "var(--v4-display)",
  fontWeight: 500,
  fontSize: "clamp(32px, 5vw, 52px)",
  lineHeight: 1.1,
  marginTop: 14,
  marginBottom: 16,
};

const subStyle = {
  fontSize: 16,
  color: "var(--v4-ink-dim)",
  lineHeight: 1.55,
  maxWidth: 600,
  marginBottom: 48,
};

const eyebrowStyle = {
  fontFamily: "var(--v4-mono)",
  fontSize: 9,
  letterSpacing: 1.8,
  color: "var(--v4-saffron)",
  textTransform: "uppercase",
  marginBottom: 16,
};

const gridStyle = {
  display: "grid",
  gridTemplateColumns: "repeat(auto-fit, minmax(280px, 1fr))",
  gap: 18,
  marginBottom: 36,
};

const modeCardStyle = {
  background: "linear-gradient(165deg, var(--v4-s2), var(--v4-s1))",
  border: "1px solid var(--v4-line)",
  borderRadius: "var(--v4-r-lg)",
  padding: "24px 22px",
  textAlign: "left",
  color: "inherit",
  transition: "border-color .15s var(--v4-ease), transform .15s var(--v4-ease)",
};

const modeIconStyle = {
  width: 38,
  height: 38,
  borderRadius: 9,
  display: "grid",
  placeItems: "center",
  fontSize: 17,
};

const badgeStyle = {
  marginLeft: "auto",
  fontFamily: "var(--v4-mono)",
  fontSize: 9,
  letterSpacing: 1.2,
  color: "var(--v4-saffron)",
  background: "rgba(255,146,72,0.12)",
  border: "1px solid rgba(255,146,72,0.32)",
  padding: "4px 9px",
  borderRadius: 6,
  textTransform: "uppercase",
};

const footerStrapStyle = {
  fontFamily: "var(--v4-mono)",
  fontSize: 10,
  letterSpacing: 1.2,
  color: "var(--v4-ink-faint)",
  textTransform: "uppercase",
  textAlign: "center",
  marginTop: 32,
};

const complianceStyle = {
  fontFamily: "var(--v4-mono)",
  fontSize: 10,
  letterSpacing: 1.2,
  color: "var(--v4-ink-faint)",
  textTransform: "uppercase",
  marginTop: 24,
};

const overlayStyle = {
  position: "fixed",
  inset: 0,
  background: "rgba(11,10,8,0.78)",
  display: "grid",
  placeItems: "center",
  zIndex: 50,
  backdropFilter: "blur(6px)",
};

const overlayCardStyle = {
  background: "linear-gradient(168deg, var(--v4-hero-a), var(--v4-hero-b))",
  border: "1px solid var(--v4-line-strong)",
  borderRadius: "var(--v4-r-lg)",
  padding: "32px 36px",
  display: "grid",
  placeItems: "center",
  gap: 18,
  minWidth: 320,
};

const spinnerStyle = {
  width: 28,
  height: 28,
  borderRadius: "50%",
  border: "2px solid var(--v4-line-strong)",
  borderTopColor: "var(--v4-saffron)",
  animation: "v4-spin-o 0.9s linear infinite",
};

const overlayMsgStyle = {
  fontSize: 14,
  color: "var(--v4-ink-dim)",
  textAlign: "center",
};

const errorBannerStyle = {
  background: "rgba(223,93,93,0.08)",
  border: "1px solid rgba(223,93,93,0.32)",
  borderRadius: "var(--v4-r-md)",
  padding: "16px 20px",
  marginBottom: 24,
};

const dismissBtnStyle = {
  marginLeft: "auto",
  fontSize: 12,
  fontWeight: 600,
  color: "var(--v4-rust)",
  background: "transparent",
  border: "1px solid var(--v4-rust)",
  padding: "7px 14px",
  borderRadius: 8,
};

const successCardStyle = {
  background: "linear-gradient(168deg, var(--v4-hero-a), var(--v4-hero-b))",
  border: "1px solid var(--v4-line-strong)",
  borderRadius: "var(--v4-r-xl)",
  padding: "32px 30px",
};

const statRowStyle = {
  display: "grid",
  gridTemplateColumns: "repeat(auto-fit, minmax(140px, 1fr))",
  gap: 14,
  marginTop: 10,
};

const statBoxStyle = {
  background: "var(--v4-s2)",
  border: "1px solid var(--v4-line)",
  borderRadius: "var(--v4-r-md)",
  padding: "16px 16px",
};

const ctaPrimaryStyle = {
  fontSize: 14,
  fontWeight: 600,
  background: "linear-gradient(150deg, var(--v4-saffron), var(--v4-saffron-dk))",
  color: "#2a1605",
  padding: "13px 22px",
  borderRadius: 10,
};

const ctaGhostStyle = {
  fontSize: 14,
  fontWeight: 500,
  background: "var(--v4-s2)",
  color: "var(--v4-ink-dim)",
  border: "1px solid var(--v4-line)",
  padding: "13px 22px",
  borderRadius: 10,
};

const staleBannerStyle = {
  background: "rgba(217,182,74,0.08)",
  border: "1px solid rgba(217,182,74,0.32)",
  borderRadius: "var(--v4-r-md)",
  padding: "16px 20px",
  marginBottom: 24,
};

const inlineLinkStyle = {
  fontFamily: "var(--v4-mono)",
  fontSize: 11,
  letterSpacing: 1,
  color: "var(--v4-ink-mute)",
  background: "transparent",
  border: "none",
  cursor: "pointer",
  textTransform: "uppercase",
};

const topHoldingsListStyle = {
  display: "flex",
  flexDirection: "column",
  marginTop: 10,
  border: "1px solid var(--v4-line)",
  borderRadius: "var(--v4-r-md)",
  overflow: "hidden",
};

const topHoldingRowStyle = {
  display: "flex",
  gap: 14,
  alignItems: "center",
  padding: "12px 16px",
  borderBottom: "1px solid var(--v4-line)",
  background: "var(--v4-s1)",
};
