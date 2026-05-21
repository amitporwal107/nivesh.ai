import React, { useEffect, useRef, useState } from "react";
import { useNavigate, useOutletContext } from "react-router-dom";
import {
  ArrowRight,
  ArrowLeft,
  Check,
  ChevronRight,
  Shield,
  Lock,
  ShieldCheck,
  FileUp,
  Mail,
  Pencil,
  FileText,
} from "lucide-react";
import BrandMark from "../../components/BrandMark";
import PersonaAvatar from "../../components/PersonaAvatar";
import ScreenContainer from "../../components/layout/ScreenContainer";
import { usePersona, PERSONAS, uploadPortfolioFile, pollUploadStatus, apiPatch, apiPost } from "../../adapters";
import { useAuth } from "@/context/AuthContext";
import { GoogleLogin } from "@react-oauth/google";
import { openConnectAndImport } from "../../adapters/connectImport";
import { Briefcase, User, Users } from "lucide-react";

// 5-step state machine for retail; 6-step branch for MFD:
//   welcome → role → (pick → importing → reveal)            [individual]
//   welcome → role → (mfd_setup → importing → reveal)       [mfd]
//
// `stepIndex` for the Pips bar is derived from STEPS_FOR_ROLE.
const STEPS = ["welcome", "role", "pick", "mfd_setup", "importing", "reveal"];
const STEPS_INDIVIDUAL = ["welcome", "role", "pick", "importing", "reveal"];
const STEPS_MFD =        ["welcome", "role", "mfd_setup", "importing", "reveal"];

// Findings stream timing (in ms from start of import).
const FINDINGS_TIMELINE = [
  { key: "pan", label: "Identified PAN holder", value: "RM", at: 600 },
  { key: "mf", label: "Mutual fund folios", value: 11, at: 1500 },
  { key: "equity", label: "Equity holdings", value: 4, at: 2700 },
  { key: "sip", label: "SIP schedule", value: 6, at: 3800 },
];

const IMPORT_DURATION = 4500;

const ONBOARDED_KEY = "v3.onboarded";

export default function Onboarding() {
  const { viewport } = useOutletContext() || { viewport: "mobile" };
  const isDesktop = viewport === "desktop";
  const navigate = useNavigate();
  const { setPersona } = usePersona();
  const { user, loginWithGoogle, authError, googleClientId } = useAuth();

  const [step, setStep] = useState(STEPS[0]);
  const [role, setRole] = useState(null); // "individual" | "mfd"
  const [method, setMethod] = useState(null); // "cas" | "gmail" | "manual"
  const [findings, setFindings] = useState({});
  const [importPct, setImportPct] = useState(8);
  const [detectedPersona, setDetectedPersona] = useState("mf_focused");
  const [picking, setPicking] = useState(false);
  const [casFile, setCasFile] = useState(null);
  const [uploadStatusMsg, setUploadStatusMsg] = useState(null);
  const [mfdFirstClient, setMfdFirstClient] = useState(null); // { profile_id, name }

  const importTimers = useRef([]);

  const activeFlow = role === "mfd" ? STEPS_MFD : STEPS_INDIVIDUAL;
  const stepIndex = Math.max(0, activeFlow.indexOf(step));

  // ── Importing: drive real CAS upload when a file is attached; otherwise run
  // a simulated import that mirrors the same UX. Either path streams findings
  // into the list and advances `importPct`.
  useEffect(() => {
    if (step !== "importing") return undefined;

    setFindings({});
    setImportPct(8);
    setUploadStatusMsg(null);
    let cancelled = false;
    importTimers.current = [];

    const queueFinding = (key, value, delay) => {
      const t = window.setTimeout(() => {
        if (cancelled) return;
        setFindings((prev) => ({ ...prev, [key]: { key, value, done: true } }));
      }, delay);
      importTimers.current.push(t);
    };

    const tickInterval = window.setInterval(() => {
      if (cancelled) return;
      setImportPct((p) => Math.min(p + 4 + Math.random() * 6, 96));
    }, 220);
    importTimers.current.push(tickInterval);

    const finalizeWithPersona = (id) => {
      if (cancelled) return;
      setImportPct(100);
      setDetectedPersona(id);
      setPersona(id);
      setStep("reveal");
    };

    // Real Connect SDK path — opens the same widget V2 uses (PDF upload,
    // Gmail inbox CAS auto-fetch, CDSL OTP — all in-modal). Hint biases the
    // widget toward the tab the user actually picked on screen 2.
    const runConnect = async () => {
      queueFinding("pan", "RM", 400);
      const res = await openConnectAndImport({
        method, // "cas" | "gmail"
        onProgress: setUploadStatusMsg,
      });
      if (cancelled) return;
      if (res.cancelled) {
        setUploadStatusMsg("Cancelled — going back");
        // Send the user back to the picker rather than dead-ending in import.
        setStep("pick");
        return;
      }
      if (!res.ok) {
        setUploadStatusMsg(res.error?.message || "Import failed — showing demo data");
        // Fall through to simulated path so the flow always completes.
        runSimulated();
        return;
      }
      const holdings = res.holdings || [];
      const mf = holdings.filter((h) => (h.asset_type || "").includes("mutual")).length;
      const eq = holdings.filter((h) => (h.asset_type || "") === "equity").length;
      setFindings({
        pan: { key: "pan", value: res.investor || "✓", done: true },
        mf: { key: "mf", value: mf || res.count || 0, done: true },
        equity: { key: "equity", value: eq, done: true },
        sip: { key: "sip", value: holdings.length || res.count || 0, done: true },
      });
      finalizeWithPersona(inferPersonaFromCounts(mf, eq));
    };

    // Legacy direct-upload path — retained as a fallback only for the
    // manually-attached <input type="file"> case. New flows go through
    // runConnect() above.
    const runRealUpload = async () => {
      queueFinding("pan", "RM", 400);
      setUploadStatusMsg("Uploading file…");
      const r = await uploadPortfolioFile(casFile);
      if (cancelled) return;
      if (!r.ok) {
        setUploadStatusMsg(r.error?.message || "Upload failed — switching to demo data");
        runSimulated();
        return;
      }
      if (Array.isArray(r.holdings) && !r.taskId) {
        const mf = r.holdings.filter((h) => (h.asset_type || "").includes("mutual")).length;
        const eq = r.holdings.filter((h) => (h.asset_type || "") === "equity").length;
        queueFinding("mf", mf || 0, 600);
        queueFinding("equity", eq || 0, 1100);
        queueFinding("sip", "—", 1600);
        const t = window.setTimeout(() => finalizeWithPersona(inferPersonaFromCounts(mf, eq)), 2200);
        importTimers.current.push(t);
        return;
      }
      setUploadStatusMsg("Parsing your statement…");
      const polled = await pollUploadStatus(r.taskId, {
        intervalMs: 1500,
        maxMs: 90000,
        onProgress: (p) => {
          if (cancelled) return;
          if (p.message) setUploadStatusMsg(p.message);
          if (p.count != null && p.count > 0) {
            setFindings((prev) => ({ ...prev, mf: { key: "mf", value: p.count, done: true } }));
          }
        },
      });
      if (cancelled) return;
      if (!polled.ok) {
        setUploadStatusMsg(polled.error?.message || "Parsing failed — using demo data");
        runSimulated();
        return;
      }
      const holdings = polled.holdings || [];
      const mf = holdings.filter((h) => (h.asset_type || "").includes("mutual")).length;
      const eq = holdings.filter((h) => (h.asset_type || "") === "equity").length;
      setFindings({
        pan: { key: "pan", value: "RM", done: true },
        mf: { key: "mf", value: mf, done: true },
        equity: { key: "equity", value: eq, done: true },
        sip: { key: "sip", value: holdings.length, done: true },
      });
      finalizeWithPersona(inferPersonaFromCounts(mf, eq));
    };

    const runSimulated = () => {
      FINDINGS_TIMELINE.forEach((f) => queueFinding(f.key, f.value, f.at));
      const t = window.setTimeout(() => finalizeWithPersona(inferPersona(method)), IMPORT_DURATION);
      importTimers.current.push(t);
    };

    if (method === "cas" || method === "gmail") {
      // Connect SDK requires an authenticated session — fall through to
      // simulated import if the user somehow reached importing without one.
      if (user) runConnect();
      else if (method === "cas" && casFile) runRealUpload();
      else runSimulated();
    } else {
      runSimulated();
    }

    return () => {
      cancelled = true;
      importTimers.current.forEach((t) => {
        window.clearTimeout(t);
        window.clearInterval(t);
      });
      importTimers.current = [];
    };
    // findings.mf is intentionally excluded — the polling callback reads the *latest* via setState fn.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [step, method, casFile, user, setPersona]);

  const finish = () => {
    try {
      window.localStorage.setItem(ONBOARDED_KEY, "1");
    } catch {
      /* ignore */
    }
    navigate("/home", { replace: true });
  };

  const onPickMethod = (m) => {
    setMethod(m);
    if (m === "manual") {
      setDetectedPersona("universal");
      setPersona("universal");
      setStep("reveal");
      return;
    }
    // For CAS + Gmail, advance to importing — the importing effect drives the
    // Connect SDK which owns the entire upload / Gmail-OAuth UX in-modal.
    setStep("importing");
  };

  return (
    <div
      style={{
        minHeight: "100vh",
        background: "var(--v3-bg-0)",
        position: "relative",
        overflow: "hidden",
      }}
    >
      {/* Atmospheric background — same as global, repeated here so onboarding fills the viewport even before MobileShell paddings. */}
      <BackgroundAtmosphere />

      <ScreenContainer
        variant={isDesktop ? "desktop" : "mobile"}
        maxWidth={isDesktop ? 560 : undefined}
        style={{ position: "relative", zIndex: 1 }}
      >
        <div
          style={{
            paddingTop: 24,
            paddingBottom: 32,
            display: "flex",
            flexDirection: "column",
            minHeight: "100vh",
          }}
        >
          <TopRow stepIndex={stepIndex} onBack={() => stepIndex > 0 && setStep(STEPS[stepIndex - 1])} />

          {step === "welcome" && (
            <WelcomeStep
              isDesktop={isDesktop}
              user={user}
              googleClientId={googleClientId}
              authError={authError}
              onGoogleSignIn={async (credential) => {
                try {
                  await loginWithGoogle(credential);
                  setStep("role");
                } catch (e) {
                  // authError is set by loginWithGoogle — surfaced in the Welcome UI.
                }
              }}
              onStart={() => setStep("role")}
            />
          )}
          {step === "role" && (
            <RoleStep
              isDesktop={isDesktop}
              onPick={(r) => {
                setRole(r);
                setStep(r === "mfd" ? "mfd_setup" : "pick");
              }}
            />
          )}
          {step === "mfd_setup" && (
            <MFDSetupStep
              isDesktop={isDesktop}
              onComplete={(firstClient) => {
                setMfdFirstClient(firstClient);
                setMethod("cas");
                setStep("importing");
              }}
            />
          )}
          {step === "pick" && <PickStep onPick={onPickMethod} isDesktop={isDesktop} />}
          {step === "importing" && (
            <ImportingStep
              method={method}
              findings={findings}
              importPct={importPct}
              isDesktop={isDesktop}
              file={casFile}
              statusMsg={uploadStatusMsg}
            />
          )}
          {step === "reveal" && (
            <RevealStep
              personaId={detectedPersona}
              findings={findings}
              method={method}
              isDesktop={isDesktop}
              picking={picking}
              onTogglePick={() => setPicking((v) => !v)}
              onChoosePersona={(id) => {
                setDetectedPersona(id);
                setPersona(id);
                setPicking(false);
              }}
              onFinish={finish}
            />
          )}
        </div>
      </ScreenContainer>
    </div>
  );
}

/* ═════════════════════════ TOP CHROME ═════════════════════════ */

function TopRow({ stepIndex, onBack }) {
  return (
    <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", marginBottom: 18 }}>
      <BrandMark withWordmark size={32} />
      <Pips active={stepIndex} total={STEPS.length} />
      <button
        type="button"
        onClick={onBack}
        aria-label="Back"
        disabled={stepIndex === 0}
        style={{
          width: 32,
          height: 32,
          borderRadius: 10,
          background: stepIndex === 0 ? "transparent" : "var(--v3-bg-2)",
          border: stepIndex === 0 ? "1px solid transparent" : "1px solid var(--v3-line)",
          color: stepIndex === 0 ? "transparent" : "var(--v3-ink-3)",
          display: "grid",
          placeItems: "center",
          cursor: stepIndex === 0 ? "default" : "pointer",
        }}
      >
        <ArrowLeft size={14} />
      </button>
    </div>
  );
}

function Pips({ active, total }) {
  return (
    <div style={{ display: "flex", gap: 6 }} aria-label={`Step ${active + 1} of ${total}`}>
      {Array.from({ length: total }).map((_, i) => {
        const state = i < active ? "done" : i === active ? "active" : "pending";
        return (
          <span
            key={i}
            style={{
              width: 22,
              height: 3,
              borderRadius: 2,
              background: state === "pending" ? "var(--v3-bg-3)" : "var(--v3-saffron)",
              animation: state === "active" ? "v3-pip-pulse 1.6s infinite" : undefined,
            }}
          />
        );
      })}
      <style>{`@keyframes v3-pip-pulse { 0%, 100% { opacity: 1; } 50% { opacity: 0.45; } }`}</style>
    </div>
  );
}

/* ═════════════════════════ 1 · WELCOME ═════════════════════════ */

function WelcomeStep({ onStart, isDesktop, user, googleClientId, authError, onGoogleSignIn }) {
  const isSignedIn = !!user;

  return (
    <div style={{ flex: 1, display: "flex", flexDirection: "column", justifyContent: "center", paddingTop: 12 }}>
      <SpeedBadge />

      <Eyebrow text="Built for Indian investors" />

      <h1
        style={{
          fontFamily: "var(--v3-font-display)",
          fontWeight: 600,
          fontSize: isDesktop ? 44 : 36,
          lineHeight: 1.05,
          letterSpacing: "-0.025em",
          color: "var(--v3-ink-1)",
          marginTop: 18,
          marginBottom: 16,
        }}
      >
        Your portfolio,
        <br />
        <em style={{ fontStyle: "italic", fontWeight: 500, color: "var(--v3-saffron)" }}>understood</em>
        <br />
        in seconds.
      </h1>

      <p
        style={{
          fontSize: 15,
          color: "var(--v3-ink-2)",
          lineHeight: 1.55,
          maxWidth: 320,
          marginBottom: 28,
        }}
      >
        Skip the spreadsheets. We read your CAS or Gmail and answer real questions about what you own.
      </p>

      {isSignedIn ? (
        <>
          <div
            style={{
              display: "inline-flex",
              alignItems: "center",
              gap: 10,
              padding: "8px 12px",
              background: "var(--v3-moss-soft)",
              color: "var(--v3-moss)",
              borderRadius: 999,
              alignSelf: "flex-start",
              fontFamily: "var(--v3-font-mono)",
              fontSize: 11,
              letterSpacing: "0.1em",
              marginBottom: 14,
              textTransform: "uppercase",
              fontWeight: 500,
            }}
          >
            <Check size={12} strokeWidth={2.5} />
            Signed in as {user.email || user.name}
          </div>
          <PrimaryCTA label="Get started" onClick={onStart} />
        </>
      ) : (
        <>
          <div style={{ alignSelf: "flex-start" }}>
            {googleClientId ? (
              <GoogleLogin
                onSuccess={(resp) => onGoogleSignIn(resp.credential)}
                onError={() => {}}
                theme="filled_black"
                size="large"
                shape="pill"
                text="continue_with"
              />
            ) : (
              <button
                type="button"
                disabled
                style={{
                  padding: "14px 24px",
                  borderRadius: 999,
                  background: "var(--v3-bg-3)",
                  color: "var(--v3-ink-3)",
                  border: "1px solid var(--v3-line)",
                  fontFamily: "var(--v3-font-sans)",
                  fontSize: 14,
                  cursor: "not-allowed",
                }}
              >
                Loading Google sign-in…
              </button>
            )}
          </div>
          {authError && (
            <div
              style={{
                marginTop: 10,
                padding: "8px 12px",
                background: "var(--v3-crimson-soft)",
                border: "1px solid var(--v3-crimson-soft)",
                borderRadius: 10,
                color: "var(--v3-crimson)",
                fontSize: 12.5,
              }}
            >
              {authError}
            </div>
          )}
          <div style={{ marginTop: 14, fontSize: 13, color: "var(--v3-ink-3)" }}>
            By continuing you agree to the{" "}
            <a href="/v2/privacy" style={{ color: "var(--v3-ink-1)", textDecoration: "underline", textUnderlineOffset: 3 }}>
              privacy policy
            </a>
            . Read-only — we never trade on your behalf.
          </div>
        </>
      )}

      <TrustStrip />
    </div>
  );
}

function SpeedBadge() {
  return (
    <div
      style={{
        alignSelf: "flex-start",
        display: "inline-flex",
        alignItems: "center",
        gap: 10,
        padding: "8px 14px",
        background: "var(--v3-bg-2)",
        border: "1px solid var(--v3-line-strong)",
        borderRadius: 999,
        marginBottom: 24,
      }}
    >
      <span
        aria-hidden
        style={{
          width: 8,
          height: 8,
          borderRadius: 999,
          background: "var(--v3-moss)",
          boxShadow: "0 0 0 4px rgba(123,160,91,0.2)",
          animation: "v3-live-dot 1.4s infinite",
        }}
      />
      <span
        style={{
          fontFamily: "var(--v3-font-mono)",
          fontSize: 11,
          letterSpacing: "0.1em",
          color: "var(--v3-ink-1)",
          fontWeight: 500,
        }}
      >
        SETUP TIME{" "}
        <span style={{ color: "var(--v3-moss)", fontWeight: 600 }}>~10 SEC</span>
      </span>
      <style>{`@keyframes v3-live-dot { 50% { box-shadow: 0 0 0 8px rgba(123,160,91,0); } }`}</style>
    </div>
  );
}

function Eyebrow({ text }) {
  return (
    <div
      style={{
        fontFamily: "var(--v3-font-mono)",
        fontSize: 11,
        color: "var(--v3-saffron)",
        textTransform: "uppercase",
        letterSpacing: "0.18em",
        display: "flex",
        alignItems: "center",
        gap: 10,
      }}
    >
      <span aria-hidden style={{ width: 24, height: 1, background: "var(--v3-saffron)" }} />
      {text}
    </div>
  );
}

function TrustStrip() {
  const items = [
    { icon: ShieldCheck, label: "Bank-grade" },
    { icon: Lock, label: "Read-only" },
    { icon: Shield, label: "SEBI-aware" },
  ];
  return (
    <div style={{ marginTop: "auto", paddingTop: 28 }}>
      <div
        style={{
          display: "flex",
          alignItems: "center",
          justifyContent: "space-between",
          gap: 14,
          paddingTop: 18,
          borderTop: "1px solid var(--v3-line)",
        }}
      >
        {items.map((it) => {
          const Icon = it.icon;
          return (
            <span
              key={it.label}
              style={{
                display: "inline-flex",
                alignItems: "center",
                gap: 6,
                fontFamily: "var(--v3-font-mono)",
                fontSize: 10,
                color: "var(--v3-ink-3)",
                textTransform: "uppercase",
                letterSpacing: "0.08em",
              }}
            >
              <Icon size={12} style={{ color: "var(--v3-moss)" }} strokeWidth={2} />
              {it.label}
            </span>
          );
        })}
      </div>
    </div>
  );
}

/* ═════════════════════════ 2 · PICK METHOD ═════════════════════════ */

function PickStep({ onPick, isDesktop }) {
  return (
    <div style={{ display: "flex", flexDirection: "column", paddingTop: 4 }}>
      <h2
        style={{
          fontFamily: "var(--v3-font-display)",
          fontWeight: 600,
          fontSize: isDesktop ? 32 : 28,
          lineHeight: 1.1,
          letterSpacing: "-0.02em",
          marginBottom: 8,
        }}
      >
        Pick the <em style={{ fontStyle: "italic", color: "var(--v3-saffron)", fontWeight: 500 }}>fastest</em>
        <br />
        way in.
      </h2>
      <p style={{ fontSize: 14, color: "var(--v3-ink-2)", lineHeight: 1.5, marginBottom: 24 }}>
        Both keep your data read-only.
        <br />
        You can disconnect anytime.
      </p>

      <div style={{ display: "flex", flexDirection: "column", gap: 12 }}>
        <MethodCard
          featured
          tag="FASTEST"
          icon={FileUp}
          title="Upload CAS statement"
          desc="Your consolidated NSDL/CDSL statement — all MFs and stocks across AMCs in one PDF."
          meta={[
            { tone: "moss", icon: Check, label: "~6 sec" },
            { label: "PDF · Excel" },
            { label: "No login" },
          ]}
          onClick={() => onPick("cas")}
        />

        <MethodCard
          icon={Mail}
          title="Import from Gmail"
          desc="We read only AMC / CDSL emails to detect your holdings. No personal mail."
          meta={[
            { tone: "moss", icon: Check, label: "~8 sec" },
            { label: "OAuth · revocable" },
          ]}
          onClick={() => onPick("gmail")}
        />

        <OrDivider />

        <MethodCard
          quiet
          icon={Pencil}
          title="Enter holdings manually"
          desc="Type each fund and stock yourself. ~10 minutes."
          onClick={() => onPick("manual")}
        />
      </div>

      <div
        style={{
          marginTop: "auto",
          paddingTop: 22,
          textAlign: "center",
          fontFamily: "var(--v3-font-mono)",
          fontSize: 10,
          letterSpacing: "0.08em",
          color: "var(--v3-ink-4)",
          textTransform: "uppercase",
          display: "flex",
          alignItems: "center",
          gap: 8,
          justifyContent: "center",
        }}
      >
        <Shield size={12} style={{ color: "var(--v3-moss)" }} />
        256-bit · encrypted at rest · DPDP compliant
      </div>
    </div>
  );
}

function MethodCard({ featured, quiet, tag, icon: Icon, title, desc, meta = [], onClick }) {
  const [hover, setHover] = useState(false);
  return (
    <button
      type="button"
      onClick={onClick}
      onMouseEnter={() => setHover(true)}
      onMouseLeave={() => setHover(false)}
      style={{
        textAlign: "left",
        background: featured
          ? "linear-gradient(135deg, #1f1c18, #1c1a17)"
          : quiet
          ? "transparent"
          : "var(--v3-bg-2)",
        border: `1px ${quiet ? "dashed" : "solid"} ${hover ? "var(--v3-line-strong)" : featured ? "var(--v3-line-strong)" : "var(--v3-line)"}`,
        borderRadius: 18,
        padding: quiet ? 14 : 18,
        display: "flex",
        gap: 14,
        alignItems: "flex-start",
        cursor: "pointer",
        position: "relative",
        overflow: "hidden",
        transition: "border-color var(--v3-dur) var(--v3-ease)",
        fontFamily: "inherit",
        color: "inherit",
        width: "100%",
      }}
    >
      {featured && (
        <span
          aria-hidden
          style={{
            position: "absolute",
            top: 14,
            right: 14,
            fontFamily: "var(--v3-font-mono)",
            fontSize: 9,
            letterSpacing: "0.16em",
            color: "var(--v3-saffron)",
            background: "var(--v3-saffron-soft)",
            padding: "4px 8px",
            borderRadius: 6,
            textTransform: "uppercase",
            fontWeight: 600,
          }}
        >
          {tag}
        </span>
      )}
      {featured && (
        <span
          aria-hidden
          style={{
            position: "absolute",
            top: "-40%",
            right: "-20%",
            width: 200,
            height: 200,
            background: "radial-gradient(circle, var(--v3-saffron-soft), transparent 65%)",
            pointerEvents: "none",
          }}
        />
      )}

      <span
        aria-hidden
        style={{
          width: quiet ? 38 : 48,
          height: quiet ? 38 : 48,
          borderRadius: quiet ? 10 : 14,
          background: featured ? "linear-gradient(135deg, var(--v3-saffron), var(--v3-saffron-deep))" : quiet ? "var(--v3-bg-2)" : "var(--v3-bg-3)",
          display: "grid",
          placeItems: "center",
          flexShrink: 0,
          position: "relative",
          zIndex: 1,
        }}
      >
        <Icon
          size={quiet ? 18 : 22}
          color={featured ? "var(--v3-saffron-ink)" : "var(--v3-ink-2)"}
          strokeWidth={2}
        />
      </span>

      <div style={{ flex: 1, minWidth: 0, position: "relative", zIndex: 1 }}>
        <div
          style={{
            fontFamily: quiet ? "var(--v3-font-sans)" : "var(--v3-font-display)",
            fontWeight: quiet ? 500 : 600,
            fontSize: quiet ? 14 : 17,
            color: "var(--v3-ink-1)",
            marginBottom: 4,
            letterSpacing: quiet ? 0 : "-0.01em",
          }}
        >
          {title}
        </div>
        <p style={{ fontSize: quiet ? 12 : 12.5, color: "var(--v3-ink-2)", lineHeight: 1.45, marginBottom: meta.length ? 10 : 0 }}>{desc}</p>
        {meta.length > 0 && (
          <div style={{ display: "flex", alignItems: "center", gap: 10, flexWrap: "wrap" }}>
            {meta.map((m, i) => {
              const Mi = m.icon;
              return (
                <span
                  key={i}
                  style={{
                    display: "inline-flex",
                    alignItems: "center",
                    gap: 5,
                    fontFamily: "var(--v3-font-mono)",
                    fontSize: 10,
                    color: m.tone === "moss" ? "var(--v3-moss)" : "var(--v3-ink-3)",
                    textTransform: "uppercase",
                    letterSpacing: "0.08em",
                  }}
                >
                  {Mi && <Mi size={11} strokeWidth={2.5} />}
                  {m.label}
                </span>
              );
            })}
          </div>
        )}
      </div>

      {!featured && !quiet && (
        <ChevronRight size={16} style={{ color: "var(--v3-ink-3)", alignSelf: "center", flexShrink: 0, position: "relative", zIndex: 1 }} />
      )}
    </button>
  );
}

function OrDivider() {
  return (
    <div
      style={{
        display: "flex",
        alignItems: "center",
        gap: 14,
        padding: "6px 0",
        fontFamily: "var(--v3-font-mono)",
        fontSize: 10,
        color: "var(--v3-ink-4)",
        letterSpacing: "0.14em",
        textTransform: "uppercase",
      }}
    >
      <span style={{ flex: 1, height: 1, background: "var(--v3-line)" }} />
      or take longer
      <span style={{ flex: 1, height: 1, background: "var(--v3-line)" }} />
    </div>
  );
}

/* ═════════════════════════ 3 · IMPORTING ═════════════════════════ */

function ImportingStep({ method, findings, importPct, isDesktop, file, statusMsg }) {
  const fileName = file
    ? file.name
    : method === "cas"
    ? "CAS_NSDL_18MAY2026.pdf"
    : method === "gmail"
    ? "Reading AMC emails"
    : "Manual entries";
  const fileMeta = file
    ? `${formatBytes(file.size)} · ${file.type.includes("pdf") ? "PDF" : "DATA"}`
    : method === "cas"
    ? "14 PAGES · 412 KB"
    : method === "gmail"
    ? "READING AMC EMAILS"
    : "—";

  const checks = FINDINGS_TIMELINE.map((f) => ({
    ...f,
    done: !!findings[f.key]?.done,
  }));
  const inFlightIdx = checks.findIndex((c) => !c.done);

  return (
    <div style={{ display: "flex", flexDirection: "column", paddingTop: 4, position: "relative" }}>
      <span
        aria-hidden
        style={{
          position: "absolute",
          top: 30,
          left: "50%",
          transform: "translateX(-50%)",
          width: 240,
          height: 240,
          borderRadius: 999,
          background: "radial-gradient(circle, var(--v3-saffron-soft), transparent 65%)",
          filter: "blur(10px)",
          zIndex: 0,
        }}
      />

      <div
        style={{
          fontFamily: "var(--v3-font-mono)",
          fontSize: 10,
          color: "var(--v3-ink-3)",
          letterSpacing: "0.18em",
          textTransform: "uppercase",
          marginBottom: 12,
          position: "relative",
          zIndex: 1,
        }}
      >
        Step 3 of 4 ·{" "}
        <span style={{ color: "var(--v3-saffron)" }}>
          {method === "gmail" ? "scanning emails" : "parsing your statement"}
        </span>
      </div>

      <h2
        style={{
          fontFamily: "var(--v3-font-display)",
          fontWeight: 600,
          fontSize: isDesktop ? 26 : 22,
          lineHeight: 1.2,
          letterSpacing: "-0.015em",
          marginBottom: 22,
          position: "relative",
          zIndex: 1,
        }}
      >
        Reading your
        <br />
        portfolio…
      </h2>

      <div
        style={{
          background: "var(--v3-bg-2)",
          border: "1px solid var(--v3-line)",
          borderRadius: 20,
          padding: "26px 20px",
          marginBottom: 16,
          position: "relative",
          zIndex: 1,
        }}
      >
        <div
          style={{
            width: 96,
            height: 96,
            margin: "0 auto 14px",
            position: "relative",
            display: "grid",
            placeItems: "center",
          }}
        >
          {[0, 0.5, 1].map((delay) => (
            <span
              key={delay}
              aria-hidden
              style={{
                position: "absolute",
                inset: 0,
                borderRadius: 999,
                border: "1px solid var(--v3-saffron)",
                animation: `v3-ring 2s ${delay}s infinite`,
                opacity: 0,
              }}
            />
          ))}
          <span
            style={{
              width: 64,
              height: 64,
              borderRadius: 18,
              background: "linear-gradient(135deg, var(--v3-saffron), var(--v3-saffron-deep))",
              display: "grid",
              placeItems: "center",
              boxShadow: "0 12px 30px -10px var(--v3-saffron)",
              position: "relative",
              zIndex: 2,
            }}
            aria-hidden
          >
            {method === "gmail" ? (
              <Mail size={28} color="var(--v3-saffron-ink)" strokeWidth={2.2} />
            ) : (
              <FileText size={28} color="var(--v3-saffron-ink)" strokeWidth={2.2} />
            )}
          </span>
        </div>
        <div
          style={{
            textAlign: "center",
            fontSize: 14,
            color: "var(--v3-ink-1)",
            fontWeight: 500,
            marginBottom: 4,
          }}
        >
          {fileName}
        </div>
        <div
          style={{
            textAlign: "center",
            fontFamily: "var(--v3-font-mono)",
            fontSize: 10.5,
            color: "var(--v3-ink-3)",
            letterSpacing: "0.1em",
            textTransform: "uppercase",
          }}
        >
          {fileMeta}
        </div>
        <style>{`@keyframes v3-ring { 0% { transform: scale(0.5); opacity: 0.6; } 100% { transform: scale(1.45); opacity: 0; } }`}</style>
      </div>

      <div
        style={{
          background: "var(--v3-bg-2)",
          border: "1px solid var(--v3-line)",
          borderRadius: 16,
          padding: 4,
          marginBottom: 16,
          position: "relative",
          zIndex: 1,
        }}
      >
        {checks.map((c, i) => (
          <FindingRow
            key={c.key}
            label={c.label}
            value={c.done ? c.value : i === inFlightIdx ? "scanning…" : "—"}
            state={c.done ? "done" : i === inFlightIdx ? "loading" : "pending"}
            isLast={i === checks.length - 1}
          />
        ))}
      </div>

      <div
        style={{
          height: 4,
          background: "var(--v3-bg-3)",
          borderRadius: 2,
          overflow: "hidden",
          position: "relative",
          zIndex: 1,
        }}
      >
        <div
          style={{
            height: "100%",
            width: `${importPct}%`,
            background: "linear-gradient(90deg, var(--v3-saffron), #ffb380)",
            borderRadius: 2,
            transition: "width 220ms linear",
          }}
        />
      </div>

      <div
        style={{
          marginTop: 14,
          textAlign: "center",
          fontFamily: "var(--v3-font-mono)",
          fontSize: 10,
          color: "var(--v3-ink-4)",
          letterSpacing: "0.12em",
          textTransform: "uppercase",
          position: "relative",
          zIndex: 1,
        }}
      >
        {statusMsg
          ? <span style={{ color: "var(--v3-saffron)" }}>{statusMsg}</span>
          : <>processed locally · <span style={{ color: "var(--v3-moss)" }}>nothing stored yet</span></>}
      </div>
    </div>
  );
}

function formatBytes(n) {
  if (!Number.isFinite(n)) return "—";
  if (n < 1024) return `${n} B`;
  if (n < 1024 * 1024) return `${(n / 1024).toFixed(0)} KB`;
  return `${(n / 1024 / 1024).toFixed(1)} MB`;
}

function FindingRow({ label, value, state, isLast }) {
  return (
    <div
      style={{
        display: "flex",
        alignItems: "center",
        gap: 12,
        padding: "10px 14px",
        borderTop: state === "pending" || !isLast ? "1px solid var(--v3-line)" : "none",
      }}
    >
      {state === "done" && (
        <span
          aria-hidden
          style={{
            width: 18,
            height: 18,
            borderRadius: 999,
            background: "var(--v3-moss-soft)",
            color: "var(--v3-moss)",
            display: "grid",
            placeItems: "center",
            flexShrink: 0,
          }}
        >
          <Check size={11} strokeWidth={3} />
        </span>
      )}
      {state === "loading" && (
        <span
          aria-hidden
          style={{
            width: 18,
            height: 18,
            borderRadius: 999,
            border: "2px solid var(--v3-line-strong)",
            borderTopColor: "var(--v3-saffron)",
            animation: "v3-spin 0.8s linear infinite",
            flexShrink: 0,
          }}
        />
      )}
      {state === "pending" && (
        <span
          aria-hidden
          style={{
            width: 18,
            height: 18,
            borderRadius: 999,
            background: "var(--v3-bg-3)",
            color: "var(--v3-ink-4)",
            display: "grid",
            placeItems: "center",
            flexShrink: 0,
          }}
        >
          <span style={{ width: 4, height: 4, borderRadius: 999, background: "var(--v3-ink-4)" }} />
        </span>
      )}
      <span style={{ fontSize: 13, color: state === "pending" ? "var(--v3-ink-3)" : "var(--v3-ink-1)", flex: 1 }}>
        {label}
      </span>
      <span
        style={{
          fontFamily: "var(--v3-font-mono)",
          fontSize: 12,
          fontWeight: 600,
          color: state === "done" ? "var(--v3-saffron)" : state === "loading" ? "var(--v3-saffron)" : "var(--v3-ink-4)",
        }}
      >
        {value}
      </span>
      <style>{`@keyframes v3-spin { to { transform: rotate(360deg); } }`}</style>
    </div>
  );
}

/* ═════════════════════════ 4 · PERSONA REVEAL ═════════════════════════ */

function RevealStep({ personaId, findings, method, isDesktop, picking, onTogglePick, onChoosePersona, onFinish }) {
  const persona = PERSONAS.find((p) => p.id === personaId) || PERSONAS[0];
  const userName = "Rohan"; // future: pull from intel.user_name

  const fundCount = findings.mf?.value ?? 11;
  const amcCount = 4;
  const invested = "₹18.4";
  const investedSuffix = "L";

  return (
    <div style={{ display: "flex", flexDirection: "column", paddingTop: 4, position: "relative" }}>
      <span
        aria-hidden
        style={{
          position: "absolute",
          top: -40,
          left: "50%",
          transform: "translateX(-50%)",
          width: 360,
          height: 220,
          background: "radial-gradient(ellipse, var(--v3-saffron-soft), transparent 70%)",
          filter: "blur(20px)",
          pointerEvents: "none",
        }}
      />

      <div
        style={{
          fontFamily: "var(--v3-font-mono)",
          fontSize: 11,
          color: "var(--v3-moss)",
          letterSpacing: "0.16em",
          textTransform: "uppercase",
          marginBottom: 10,
          display: "flex",
          alignItems: "center",
          gap: 8,
          position: "relative",
          zIndex: 1,
        }}
      >
        <Check size={14} strokeWidth={2.5} />
        All set, {userName}
      </div>

      <h2
        style={{
          fontFamily: "var(--v3-font-display)",
          fontWeight: 600,
          fontSize: isDesktop ? 30 : 26,
          lineHeight: 1.15,
          letterSpacing: "-0.02em",
          marginBottom: 22,
          position: "relative",
          zIndex: 1,
        }}
      >
        Looks like you're a
        <br />
        <em style={{ fontStyle: "italic", color: "var(--v3-saffron)", fontWeight: 500 }}>{personaShortName(personaId)}</em> investor.
      </h2>

      <div
        style={{
          background: "linear-gradient(135deg, var(--v3-bg-2), var(--v3-bg-3))",
          border: "1px solid var(--v3-line-strong)",
          borderRadius: 20,
          padding: 18,
          marginBottom: 16,
          position: "relative",
          zIndex: 1,
          overflow: "hidden",
        }}
      >
        <span
          aria-hidden
          style={{
            position: "absolute",
            top: 0,
            right: 0,
            width: 140,
            height: 140,
            background: "radial-gradient(circle, var(--v3-saffron-soft), transparent 70%)",
            pointerEvents: "none",
          }}
        />
        <div style={{ display: "flex", alignItems: "center", gap: 12, position: "relative" }}>
          <PersonaAvatar iconKey={persona.avatarIcon} accent={persona.accent} size={44} radius={12} />
          <div>
            <div className="v3-eyebrow" style={{ color: "var(--v3-ink-3)" }}>YOUR PERSONA</div>
            <div style={{ fontFamily: "var(--v3-font-display)", fontWeight: 600, fontSize: 17, color: "var(--v3-ink-1)", letterSpacing: "-0.01em" }}>
              {persona.name}
            </div>
          </div>
        </div>

        <div
          style={{
            marginTop: 16,
            display: "grid",
            gridTemplateColumns: "1fr 1fr 1fr",
            gap: 1,
            background: "var(--v3-line)",
            borderRadius: 12,
            overflow: "hidden",
          }}
        >
          <SnapshotStat num={fundCount} label="Funds" />
          <SnapshotStat num={amcCount} label="AMCs" />
          <SnapshotStat num={invested} suffix={investedSuffix} label="Invested" />
        </div>
      </div>

      <p
        style={{
          fontSize: 13.5,
          color: "var(--v3-ink-2)",
          lineHeight: 1.55,
          marginBottom: 18,
          position: "relative",
          zIndex: 1,
        }}
      >
        We'll focus on{" "}
        <em style={{ color: "var(--v3-saffron)", fontStyle: "normal", fontWeight: 500 }}>
          {pickFocusText(personaId)}
        </em>{" "}
        — and benchmark every answer against the category top quartile.
      </p>

      <div style={{ textAlign: "center", marginBottom: 16, fontSize: 12, color: "var(--v3-ink-3)", position: "relative", zIndex: 1 }}>
        Not quite right?{" "}
        <button
          type="button"
          onClick={onTogglePick}
          style={{
            color: "var(--v3-ink-2)",
            textDecoration: "underline",
            textUnderlineOffset: 3,
            background: "transparent",
            border: "none",
            cursor: "pointer",
            font: "inherit",
            padding: 0,
          }}
        >
          {picking ? "Cancel" : "Change persona"}
        </button>
      </div>

      {picking && (
        <div
          style={{
            display: "grid",
            gridTemplateColumns: isDesktop ? "repeat(2, 1fr)" : "1fr",
            gap: 8,
            marginBottom: 16,
            position: "relative",
            zIndex: 1,
          }}
        >
          {PERSONAS.filter((p) => p.id !== "universal").map((opt) => {
            const active = opt.id === personaId;
            return (
              <button
                type="button"
                key={opt.id}
                onClick={() => onChoosePersona(opt.id)}
                style={{
                  textAlign: "left",
                  background: active ? "var(--v3-bg-3)" : "var(--v3-bg-2)",
                  border: `1px solid ${active ? "var(--v3-saffron)" : "var(--v3-line)"}`,
                  borderRadius: 12,
                  padding: 10,
                  display: "flex",
                  alignItems: "center",
                  gap: 10,
                  cursor: "pointer",
                  fontFamily: "inherit",
                  color: "inherit",
                }}
              >
                <PersonaAvatar iconKey={opt.avatarIcon} accent={opt.accent} size={28} radius={8} />
                <span style={{ flex: 1, minWidth: 0, fontSize: 13, color: "var(--v3-ink-1)", overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
                  {opt.name}
                </span>
                {active && <Check size={14} style={{ color: "var(--v3-saffron)" }} />}
              </button>
            );
          })}
        </div>
      )}

      <PrimaryCTA label="Open Copilot" onClick={onFinish} />
    </div>
  );
}

function SnapshotStat({ num, suffix, label }) {
  return (
    <div style={{ background: "var(--v3-bg-2)", padding: "12px 10px", textAlign: "center" }}>
      <div style={{ fontFamily: "var(--v3-font-display)", fontWeight: 600, fontSize: 20, color: "var(--v3-ink-1)", letterSpacing: "-0.02em", marginBottom: 2 }}>
        {num}
        {suffix && <span style={{ fontSize: 13, color: "var(--v3-ink-3)", marginLeft: 1 }}>{suffix}</span>}
      </div>
      <div className="v3-eyebrow" style={{ color: "var(--v3-ink-3)", fontSize: 9 }}>{label}</div>
    </div>
  );
}

/* ═════════════════════════ SHARED PRIMITIVES ═════════════════════════ */

function PrimaryCTA({ label, onClick }) {
  const [hover, setHover] = useState(false);
  return (
    <button
      type="button"
      onClick={onClick}
      onMouseEnter={() => setHover(true)}
      onMouseLeave={() => setHover(false)}
      style={{
        background: "var(--v3-saffron)",
        color: "var(--v3-saffron-ink)",
        border: "none",
        padding: "16px 22px",
        borderRadius: 16,
        fontFamily: "var(--v3-font-sans)",
        fontSize: 15,
        fontWeight: 600,
        cursor: "pointer",
        width: "100%",
        display: "flex",
        alignItems: "center",
        justifyContent: "space-between",
        boxShadow: hover ? "0 12px 30px -10px rgba(255,140,66,0.6)" : "0 8px 24px -8px rgba(255,140,66,0.5)",
        transition: "box-shadow var(--v3-dur) var(--v3-ease), transform var(--v3-dur) var(--v3-ease)",
        transform: hover ? "translateY(-1px)" : "translateY(0)",
        letterSpacing: "-0.01em",
      }}
    >
      <span>{label}</span>
      <ArrowRight size={18} strokeWidth={2.5} />
    </button>
  );
}

function BackgroundAtmosphere() {
  return (
    <>
      <span
        aria-hidden
        style={{
          position: "absolute",
          top: -200,
          right: -200,
          width: 520,
          height: 520,
          borderRadius: 999,
          background: "radial-gradient(circle, var(--v3-saffron-soft), transparent 60%)",
          filter: "blur(20px)",
          pointerEvents: "none",
        }}
      />
      <span
        aria-hidden
        style={{
          position: "absolute",
          bottom: -180,
          left: -180,
          width: 460,
          height: 460,
          borderRadius: 999,
          background: "radial-gradient(circle, rgba(107,108,255,0.08), transparent 60%)",
          filter: "blur(20px)",
          pointerEvents: "none",
        }}
      />
      <span
        aria-hidden
        style={{
          position: "absolute",
          inset: 0,
          backgroundImage:
            "linear-gradient(rgba(255,140,66,0.035) 1px, transparent 1px), linear-gradient(90deg, rgba(255,140,66,0.035) 1px, transparent 1px)",
          backgroundSize: "28px 28px",
          maskImage: "radial-gradient(circle at 50% 35%, black 30%, transparent 75%)",
          WebkitMaskImage: "radial-gradient(circle at 50% 35%, black 30%, transparent 75%)",
          pointerEvents: "none",
        }}
      />
    </>
  );
}

/* ═════════════════════════ HELPERS ═════════════════════════ */

function inferPersona(method) {
  // Best-effort persona inference. Real version will read holdings counts/ratios
  // and route accordingly; for now, CAS users default to mf_focused, Gmail too,
  // manual defaults to universal until they pick.
  if (method === "manual") return "universal";
  return "mf_focused";
}

/**
 * Pick a persona from the actual parsed holdings.
 *   - 5+ MFs and few stocks → mf_focused
 *   - 6+ stocks and few MFs → direct_equity
 *   - Otherwise → universal (the safest default for a Mixed portfolio)
 */
function inferPersonaFromCounts(mfCount, equityCount) {
  if (mfCount >= 5 && equityCount <= 2) return "mf_focused";
  if (equityCount >= 6 && mfCount <= 2) return "direct_equity";
  if (mfCount === 0 && equityCount === 0) return "universal";
  return "mf_focused";
}

function personaShortName(id) {
  switch (id) {
    case "mf_focused":
      return "Mutual Fund";
    case "direct_equity":
      return "Direct Equity";
    case "hni":
      return "High Net-Worth";
    case "retirement_planner":
      return "Retirement";
    case "parents_for_kids":
      return "Parent";
    case "tax_conscious":
      return "Tax-Conscious";
    case "conservative":
      return "Conservative";
    case "active_trader":
      return "Active Trader";
    case "nri_global":
      return "NRI / Global";
    case "salaried_beginner":
      return "Salaried Beginner";
    default:
      return "Universal";
  }
}

function pickFocusText(id) {
  switch (id) {
    case "mf_focused":
      return "fund overlap, quality scoring, and expense-ratio leakage";
    case "direct_equity":
      return "valuation, concentration risk, and stock fundamentals";
    case "tax_conscious":
      return "unrealized gains, harvest opportunities, and FY-aware planning";
    case "hni":
      return "asset-class allocation, drift, and tax efficiency at scale";
    case "retirement_planner":
      return "withdrawal sustainability, debt allocation, and inflation hedging";
    case "parents_for_kids":
      return "goal-funded SIPs, shortfall surfacing, and time-to-goal";
    case "conservative":
      return "downside risk, debt allocation, and FD-comparable returns";
    case "active_trader":
      return "realized P&L, position sizing, and sector momentum";
    case "nri_global":
      return "geography mix, currency exposure, and treaty-aware tax";
    case "salaried_beginner":
      return "plain-language guidance, FD baseline, and one action at a time";
    default:
      return "diversification, drift, and the single best next action";
  }
}

/* ═════════════════════════ 2 · ROLE PICKER ═════════════════════════ */

function RoleStep({ onPick, isDesktop }) {
  return (
    <div style={{ flex: 1, display: "flex", flexDirection: "column", justifyContent: "center", paddingTop: 12 }}>
      <p className="v3-eyebrow" style={{ fontSize: 11, color: "var(--v3-saffron)", marginBottom: 8 }}>STEP 2 · YOU</p>
      <h1 style={{ fontFamily: "var(--v3-font-display)", fontSize: isDesktop ? 36 : 28, fontWeight: 600, color: "var(--v3-ink-1)", margin: "0 0 8px", lineHeight: 1.15 }}>
        Who are you investing for?
      </h1>
      <p style={{ color: "var(--v3-ink-3)", fontSize: 14, margin: "0 0 22px", lineHeight: 1.45 }}>
        Pick the option that matches you. You can change this later in Settings.
      </p>

      <div style={{ display: "grid", gridTemplateColumns: isDesktop ? "1fr 1fr" : "1fr", gap: 12 }}>
        <RoleCard
          icon={User}
          label="Just for me"
          desc="I'm an individual investor managing my own portfolio."
          onClick={() => onPick("individual")}
        />
        <RoleCard
          icon={Briefcase}
          label="I'm an MFD / Advisor"
          desc="I advise multiple clients and want a workspace to manage them."
          onClick={() => onPick("mfd")}
        />
      </div>
    </div>
  );
}

function RoleCard({ icon: Icon, label, desc, onClick }) {
  return (
    <button
      type="button"
      onClick={onClick}
      style={{
        textAlign: "left",
        background: "var(--v3-bg-2)",
        border: "1px solid var(--v3-line)",
        borderRadius: 14,
        padding: 18,
        cursor: "pointer",
        display: "flex",
        gap: 14,
        alignItems: "flex-start",
        transition: "all 160ms ease",
      }}
      onMouseEnter={(e) => { e.currentTarget.style.borderColor = "var(--v3-saffron)"; }}
      onMouseLeave={(e) => { e.currentTarget.style.borderColor = "var(--v3-line)"; }}
    >
      <span style={{ width: 36, height: 36, borderRadius: 10, background: "var(--v3-saffron)15", display: "grid", placeItems: "center", color: "var(--v3-saffron)", flexShrink: 0 }}>
        <Icon size={18} />
      </span>
      <span style={{ flex: 1 }}>
        <span style={{ display: "block", fontSize: 15, fontWeight: 600, color: "var(--v3-ink-1)", marginBottom: 4 }}>{label}</span>
        <span style={{ display: "block", fontSize: 12, color: "var(--v3-ink-3)", lineHeight: 1.4 }}>{desc}</span>
      </span>
    </button>
  );
}

/* ═════════════════════════ 3 · MFD SETUP ═════════════════════════ */
//
// One-step MFD bootstrap:
//   1. Capture firm name + advisor name + ARN/RIA (PATCH /api/mfd/workspace → ADVISORY mode)
//   2. Add first client (POST /api/mfd/profiles)
//   3. Activate that client (POST /api/mfd/profiles/{id}/activate)
//   4. Hand off to existing importing → reveal flow (which uploads CAS into
//      that activated client's workspace).
//
// More clients can be added later from the Advisor screen — we only require
// one here so the MFD has something to import a CAS into.

function MFDSetupStep({ onComplete, isDesktop }) {
  const [firmName, setFirmName] = React.useState("");
  const [advisorName, setAdvisorName] = React.useState("");
  const [arn, setArn] = React.useState("");
  const [clientName, setClientName] = React.useState("");
  const [clientEmail, setClientEmail] = React.useState("");
  const [clientMobile, setClientMobile] = React.useState("");
  const [submitting, setSubmitting] = React.useState(false);
  const [err, setErr] = React.useState(null);

  const canSubmit = firmName.trim() && advisorName.trim() && arn.trim() && clientName.trim();

  async function handleSubmit(e) {
    e.preventDefault();
    if (!canSubmit || submitting) return;
    setSubmitting(true);
    setErr(null);
    try {
      // 1. Workspace → ADVISORY
      const ws = await apiPatch("/mfd/workspace", {
        mode: "ADVISORY",
        firm_name: firmName.trim(),
        advisor_name: advisorName.trim(),
        arn_or_ria: arn.trim(),
        mfd_onboarding_completed: true,
      });
      if (ws.error) throw new Error(ws.error);

      // 2. First client
      const created = await apiPost("/mfd/profiles", {
        name: clientName.trim(),
        email: clientEmail.trim() || null,
        mobile: clientMobile.trim() || null,
      });
      if (created.error || !created.data) throw new Error(created.error || "Couldn't create client");
      const profileId = created.data.profile_id || created.data.id || created.data._id;
      if (!profileId) throw new Error("Created client missing id");

      // 3. Activate this client so subsequent CAS import lands in their workspace
      await apiPost(`/mfd/profiles/${profileId}/activate`, {});

      onComplete({ profile_id: profileId, name: clientName.trim() });
    } catch (e) {
      setErr(e.message || "Setup failed");
      setSubmitting(false);
    }
  }

  return (
    <div style={{ flex: 1, display: "flex", flexDirection: "column", justifyContent: "center", paddingTop: 12 }}>
      <p className="v3-eyebrow" style={{ fontSize: 11, color: "var(--v3-saffron)", marginBottom: 8 }}>STEP 3 · ADVISOR SETUP</p>
      <h1 style={{ fontFamily: "var(--v3-font-display)", fontSize: isDesktop ? 32 : 24, fontWeight: 600, color: "var(--v3-ink-1)", margin: "0 0 6px", lineHeight: 1.2 }}>
        Set up your workspace
      </h1>
      <p style={{ color: "var(--v3-ink-3)", fontSize: 13, margin: "0 0 20px" }}>
        Add your firm details and your first client. Their latest CAS will import next.
      </p>

      <form onSubmit={handleSubmit} style={{ display: "flex", flexDirection: "column", gap: 18 }}>
        <fieldset style={fieldsetStyle}>
          <legend style={legendStyle}><Briefcase size={12} /> &nbsp;Firm</legend>
          <FieldRow label="Firm name" value={firmName} setValue={setFirmName} placeholder="Acme Wealth Advisors" required />
          <FieldRow label="Advisor name" value={advisorName} setValue={setAdvisorName} placeholder="Your full name" required />
          <FieldRow label="ARN / RIA" value={arn} setValue={setArn} placeholder="ARN-12345 or INA-12345" required />
        </fieldset>

        <fieldset style={fieldsetStyle}>
          <legend style={legendStyle}><Users size={12} /> &nbsp;First client</legend>
          <FieldRow label="Client name" value={clientName} setValue={setClientName} placeholder="Client's full name" required />
          <FieldRow label="Client email (optional)" value={clientEmail} setValue={setClientEmail} type="email" placeholder="name@example.com" />
          <FieldRow label="Client mobile (optional)" value={clientMobile} setValue={setClientMobile} placeholder="+91 9xxxxxxxxx" />
        </fieldset>

        {err && (
          <div style={{ padding: "10px 12px", background: "var(--v3-crimson-soft)", border: "1px solid var(--v3-crimson)40", borderRadius: 8, color: "var(--v3-crimson)", fontSize: 12 }}>
            {err}
          </div>
        )}

        <button
          type="submit"
          disabled={!canSubmit || submitting}
          style={{
            padding: "12px 18px",
            background: canSubmit ? "var(--v3-saffron)" : "var(--v3-bg-3)",
            border: "none",
            borderRadius: 999,
            fontSize: 14,
            fontWeight: 600,
            color: canSubmit ? "#000" : "var(--v3-ink-4)",
            cursor: canSubmit && !submitting ? "pointer" : "not-allowed",
            display: "inline-flex",
            alignItems: "center",
            justifyContent: "center",
            gap: 6,
          }}
        >
          {submitting ? "Setting up…" : "Continue to CAS import"} <ChevronRight size={14} />
        </button>
        <p style={{ fontSize: 11, color: "var(--v3-ink-4)", textAlign: "center", margin: 0 }}>
          You can add more clients from the Advisor screen after setup.
        </p>
      </form>
    </div>
  );
}

const fieldsetStyle = {
  border: "1px solid var(--v3-line)",
  borderRadius: 12,
  padding: "12px 14px 14px",
  background: "var(--v3-bg-2)",
};

const legendStyle = {
  padding: "0 6px",
  fontSize: 10,
  fontFamily: "var(--v3-font-mono)",
  fontWeight: 600,
  color: "var(--v3-ink-3)",
  letterSpacing: "0.08em",
  textTransform: "uppercase",
  display: "inline-flex",
  alignItems: "center",
};

function FieldRow({ label, value, setValue, placeholder, type = "text", required }) {
  return (
    <label style={{ display: "block", marginTop: 10 }}>
      <span style={{ display: "block", fontSize: 11, color: "var(--v3-ink-3)", marginBottom: 4 }}>
        {label} {required && <span style={{ color: "var(--v3-crimson)" }}>*</span>}
      </span>
      <input
        type={type}
        value={value}
        onChange={(e) => setValue(e.target.value)}
        placeholder={placeholder}
        required={required}
        style={{
          width: "100%",
          padding: "9px 12px",
          background: "var(--v3-bg-1)",
          border: "1px solid var(--v3-line)",
          borderRadius: 8,
          fontSize: 13,
          color: "var(--v3-ink-1)",
          outline: "none",
        }}
        onFocus={(e) => (e.target.style.borderColor = "var(--v3-saffron)")}
        onBlur={(e) => (e.target.style.borderColor = "var(--v3-line)")}
      />
    </label>
  );
}
