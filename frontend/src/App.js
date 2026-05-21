import React, { useEffect } from "react";
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

// V3 lives in its own SPA bundle served at /v3/* by nginx. Legacy /v2/v3/*
// links bounce the browser there with a hard redirect so the old bundle does
// not try to render V3 at all.
function V3LegacyRedirect() {
  useEffect(() => {
    const rest = window.location.pathname.replace(/^\/v2\/v3/, "") || "/";
    const target = "/v3" + rest + window.location.search + window.location.hash;
    window.location.replace(target);
  }, []);
  return <div style={{ minHeight: "100vh", background: "#0a0908" }} />;
}

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

function AppRouter() {
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
      {/* V3 is served by its own bundle at /v3/* (see src/index.v3.js +
          nginx.conf). Anyone landing on the legacy /v2/v3/* path is hard-
          redirected one-time so we never pull V3 code into this bundle. */}
      <Route path="/v3/*" element={<V3LegacyRedirect />} />
      <Route path="*" element={<Navigate to="/" replace />} />
    </Routes>
  );
}

function AppInner() {
  const { googleClientId } = useAuth();

  // Wrap in GoogleOAuthProvider once we have the client ID
  if (googleClientId) {
    return (
      <GoogleOAuthProvider clientId={googleClientId}>
        <AppRouter />
        <Toaster position="top-right" richColors />
      </GoogleOAuthProvider>
    );
  }

  // Render without Google provider while loading client ID
  return (
    <>
      <AppRouter />
      <Toaster position="top-right" richColors />
    </>
  );
}

function App() {
  return (
    <BrowserRouter basename="/v2">
      <ThemeProvider>
        <NumberFormatProvider>
          <AuthProvider>
            <AppInner />
          </AuthProvider>
        </NumberFormatProvider>
      </ThemeProvider>
    </BrowserRouter>
  );
}

export default App;
