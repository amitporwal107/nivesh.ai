// V3 bundle entry — completely separate React app from V2.
//
// Built by `yarn build:v3` with PUBLIC_URL=/v3 and BUILD_PATH=build/v3, then
// served by nginx at /v3/* with its own index.html, its own JS bundle, and
// its own /v3/static/* asset paths.  Zero V2 code is shipped to this bundle
// (App.js, Landing, Dashboard, Chat, NidpConsole, etc. are not imported).
//
// Auth and theme contexts are reused from src/context/* so a user signed
// in via /v3 stays signed in if they ever cross over to /v2 (cookies are
// path-agnostic by default).

import React from "react";
import ReactDOM from "react-dom/client";
import { BrowserRouter } from "react-router-dom";
import { GoogleOAuthProvider } from "@react-oauth/google";
import "@/index.css";
import { AuthProvider, useAuth } from "@/context/AuthContext";
import { ThemeProvider } from "@/context/ThemeContext";
import { NumberFormatProvider } from "@/context/NumberFormatContext";
import { Toaster } from "@/components/ui/sonner";
import V3App from "@/v3";
import { bootstrapNative } from "@/native/bootstrap";

bootstrapNative();

if (typeof window !== "undefined") {
  window.addEventListener(
    "error",
    (e) => {
      if (e && e.message === "Script error." && !e.filename) {
        e.preventDefault();
        e.stopImmediatePropagation();
        return false;
      }
    },
    true
  );
  window.addEventListener("unhandledrejection", (e) => {
    const msg = String(e?.reason?.message || e?.reason || "");
    if (msg.includes("401") || msg.includes("Network Error")) {
      e.preventDefault();
    }
  });
}

function V3Shell() {
  const { googleClientId } = useAuth();
  const body = <V3App />;
  return (
    <>
      {googleClientId ? (
        <GoogleOAuthProvider clientId={googleClientId}>{body}</GoogleOAuthProvider>
      ) : (
        body
      )}
      <Toaster position="top-right" richColors />
    </>
  );
}

const root = ReactDOM.createRoot(document.getElementById("root"));
root.render(
  <React.StrictMode>
    <BrowserRouter basename="/v3">
      <ThemeProvider>
        <NumberFormatProvider>
          <AuthProvider>
            <V3Shell />
          </AuthProvider>
        </NumberFormatProvider>
      </ThemeProvider>
    </BrowserRouter>
  </React.StrictMode>
);
