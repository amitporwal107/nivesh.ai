import React from "react";
import "@/App.css";
import { BrowserRouter, Routes, Route, Navigate } from "react-router-dom";
import { GoogleOAuthProvider } from "@react-oauth/google";
import { AuthProvider, useAuth } from "@/context/AuthContext";
import { ThemeProvider } from "@/context/ThemeContext";
import { NumberFormatProvider } from "@/context/NumberFormatContext";
import { Toaster } from "@/components/ui/sonner";
import Landing from "@/pages/Landing";
import Dashboard from "@/pages/Dashboard";
import CasCallback from "@/pages/CasCallback";
import Privacy from "@/pages/Privacy";

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
      <Route path="/dashboard" element={<ProtectedRoute><Dashboard /></ProtectedRoute>} />
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
    <BrowserRouter>
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
