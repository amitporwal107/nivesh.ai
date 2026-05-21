import React, { Suspense } from "react";
import "@/App.css";
import { BrowserRouter, Routes, Route, Navigate } from "react-router-dom";
import { GoogleOAuthProvider } from "@react-oauth/google";
import { AuthProvider, useAuth } from "@/context/AuthContext";
import { ThemeProvider } from "@/context/ThemeContext";
import { NumberFormatProvider } from "@/context/NumberFormatContext";
import { Toaster } from "@/components/ui/sonner";
import Landing from "@/pages/Landing";
import Dashboard from "@/pages/Dashboard";
import Chat from "@/pages/Chat";
import NidpConsole from "@/pages/NidpConsole";
import NiveshV2 from "@/pages/NiveshV2";
import CasCallback from "@/pages/CasCallback";
import CasConnect from "@/pages/CasConnect";
import Privacy from "@/pages/Privacy";

// V3 redesign — fully isolated under /v3, lazy-loaded so V2 bundle is unaffected.
const V3App = React.lazy(() => import("@/v3"));

const ProtectedRoute = ({ children }) => {
  const { user, loading } = useAuth();
  if (loading) {
    return (
      <div className="min-h-screen flex items-center justify-center bg-[#F8FAFC] dark:bg-slate-950">
        <div className="w-10 h-10 border-3 border-emerald-600 border-t-transparent rounded-full animate-spin" />
      </div>
    );
  }
  if (!user) return <Navigate to="/" replace />;
  return children;
};

// Legacy /v2/v3/* → /v3/* redirect. Crosses the basename boundary so it
// must be a hard navigation (window.location), not a React-Router <Navigate>.
function LegacyV3Redirect() {
  if (typeof window !== "undefined") {
    const { pathname, search, hash } = window.location;
    // pathname is e.g. /v2/v3/home — strip the /v2 prefix.
    const cleaned = pathname.replace(/^\/v2/, "");
    window.location.replace(cleaned + search + hash);
  }
  return null;
}

function V2Routes() {
  return (
    <Routes>
      <Route path="/" element={<Landing />} />
      <Route path="/privacy" element={<Privacy />} />
      <Route path="/cas-callback" element={<CasCallback />} />
      <Route path="/cas-connect/:token" element={<CasConnect />} />
      <Route path="/dashboard" element={<ProtectedRoute><Dashboard /></ProtectedRoute>} />
      <Route path="/chat" element={<ProtectedRoute><Chat /></ProtectedRoute>} />
      <Route path="/chat/:threadId" element={<ProtectedRoute><Chat /></ProtectedRoute>} />
      <Route path="/nidp" element={<ProtectedRoute><NidpConsole /></ProtectedRoute>} />
      <Route path="/app" element={<ProtectedRoute><NiveshV2 /></ProtectedRoute>} />
      <Route path="/v2" element={<Navigate to="/app" replace />} />
      {/* Old /v2/v3/* bookmarks → clean /v3/* — must be a hard nav. */}
      <Route path="/v3/*" element={<LegacyV3Redirect />} />
      <Route path="*" element={<Navigate to="/" replace />} />
    </Routes>
  );
}

function AppInner({ isV3 }) {
  const { googleClientId } = useAuth();
  // V3 mounts the V3 SPA directly (it has its own <Routes>); V2 keeps its
  // current route table. The choice of basename happens one level up,
  // so each path tree is independent and URLs stay clean.
  const tree = isV3 ? (
    <Suspense fallback={<div style={{ minHeight: "100vh", background: "#0a0908" }} />}>
      <V3App />
    </Suspense>
  ) : (
    <V2Routes />
  );

  if (googleClientId) {
    return (
      <GoogleOAuthProvider clientId={googleClientId}>
        {tree}
        <Toaster position="top-right" richColors />
      </GoogleOAuthProvider>
    );
  }
  return (
    <>
      {tree}
      <Toaster position="top-right" richColors />
    </>
  );
}

// Single-time URL sniff at module load. We deliberately do NOT subscribe to
// route changes here — switching between V2 and V3 means a full page reload
// (different bundles of providers, different basename). React Router never
// crosses the basename boundary on its own, so a hard reload is correct.
function detectAppMode() {
  if (typeof window === "undefined") return "v2";
  return window.location.pathname.startsWith("/v3") ? "v3" : "v2";
}

function App() {
  const mode = detectAppMode();
  const basename = mode === "v3" ? "/v3" : "/v2";

  return (
    <BrowserRouter basename={basename}>
      <ThemeProvider>
        <NumberFormatProvider>
          <AuthProvider>
            <AppInner isV3={mode === "v3"} />
          </AuthProvider>
        </NumberFormatProvider>
      </ThemeProvider>
    </BrowserRouter>
  );
}

export default App;
